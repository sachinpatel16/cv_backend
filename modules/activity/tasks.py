import os
import uuid
import cv2
import numpy as np
from sqlalchemy import select

from workers.celery import celery_app
from database.session import SessionLocal
from modules.gallery.model import GalleryMedia
from modules.activity.model import ActivityConfig, ActivityAlert
from modules.activity.repository import ActivityRepository
from services.ai.activity_detection import activity_detection_service
from workers.utils import run_async
from shared.utils.video_format import videoFormatChanger

ALERT_SNAPSHOTS_DIR = os.path.join("storage", "activity_alerts")
os.makedirs(ALERT_SNAPSHOTS_DIR, exist_ok=True)


@celery_app.task(name="modules.activity.tasks.process_activity_media_task")
def process_activity_media_task(media_id_str: str, interval: float = 0.033):
    """
    Celery task to run activity and theft detection on an uploaded media file in the background.
    """
    media_id = uuid.UUID(media_id_str)

    async def run():
        async with SessionLocal() as db:
            repo = ActivityRepository(db)
            
            # 1. Fetch media
            media = await repo.get_activity_media_by_id(media_id, media_id) # bypass tenant scope by using media_id as tenant_id in Celery
            # Wait, Celery bypasses tenant checks by loading directly, let's fetch by simple ID:
            stmt = select(GalleryMedia).where(
                GalleryMedia.id == media_id,
                GalleryMedia.is_delete == False
            )
            res = await db.execute(stmt)
            media = res.scalars().first()
            if not media:
                return

            # Update status to processing
            media.status = "processing"
            await db.commit()

            # 2. Fetch config
            stmt_cfg = select(ActivityConfig).where(
                ActivityConfig.gallery_media_id == media.id,
                ActivityConfig.is_delete == False
            )
            res_cfg = await db.execute(stmt_cfg)
            config = res_cfg.scalars().first()
            
            polygon_points = None
            detect_fall = True
            detect_aggression = True
            detect_intrusion = True
            detect_loitering = True
            loitering_threshold = 15.0
            detect_occupancy = True
            occupancy_limit = 5
            detect_sleeping = True
            detect_walking = True
            selected_activities = None

            if config:
                polygon_points = config.polygon_points
                detect_fall = config.detect_fall
                detect_aggression = config.detect_aggression
                detect_intrusion = config.detect_intrusion
                detect_loitering = config.detect_loitering
                loitering_threshold = config.loitering_threshold
                detect_occupancy = config.detect_occupancy
                occupancy_limit = config.occupancy_limit
                detect_sleeping = config.detect_sleeping
                detect_walking = config.detect_walking
                selected_activities = config.selected_activities

            output_filepath = None
            if media.media_type == "video":
                output_filepath = os.path.join(
                    "storage", "activity_media", f"output_{media.id}.mp4"
                )
            else:
                output_filepath = os.path.join(
                    "storage", "activity_media", f"output_{media.id}.jpg"
                )

            try:
                # 3. Process media
                if media.media_type == "photo":
                    # For photos, run simple single frame inference
                    img = cv2.imread(media.filepath)
                    if img is not None:
                        h_orig, w_orig = img.shape[:2]
                        # Downscale for processing speed similar to VideoFrameExtractor
                        max_dim = 640
                        scale = 1.0
                        if max(h_orig, w_orig) > max_dim:
                            scale = max_dim / max(h_orig, w_orig)
                            img_small = cv2.resize(img, (int(w_orig * scale), int(h_orig * scale)))
                        else:
                            img_small = img
                            
                        # Lazy load TF model
                        activity_detection_service._lazy_init_tf()
                        frame_exp = np.expand_dims(img_small, axis=0)
                        
                        output_dict = activity_detection_service.tf_sess.run(
                            activity_detection_service.tf_output_tensors,
                            feed_dict={activity_detection_service.tf_input_tensor: frame_exp}
                        )
                        
                        num_detections = int(output_dict['num_detections'][0])
                        detection_classes = output_dict['detection_classes'][0].astype(np.uint8)
                        detection_boxes = output_dict['detection_boxes'][0]
                        detection_scores = output_dict['detection_scores'][0]
                        
                        # Target activities
                        target_labels = None
                        if selected_activities and len(selected_activities) > 0:
                            target_labels = {lbl.lower().strip() for lbl in selected_activities}
                        else:
                            target_labels = set()
                            if detect_fall:
                                target_labels.add("fall down")
                                target_labels.add("get up")
                            if detect_sleeping:
                                target_labels.add("lie/sleep")
                            if detect_walking:
                                target_labels.add("walk")
                                target_labels.add("run/jog")
                                target_labels.add("stand")
                                target_labels.add("crouch/kneel")
                                target_labels.add("bend/bow (at the waist)")
                            if not target_labels:
                                exclusions = {1, 3, 17, 37, 43, 45, 46, 47, 59, 65, 74, 77, 78, 79, 80}
                                target_labels = {
                                    activity_detection_service.tf_labels[idx].lower().strip()
                                    for idx in range(len(activity_detection_service.tf_labels))
                                    if (idx + 1) not in exclusions and activity_detection_service.tf_labels[idx] != "N/A"
                                }
                                
                        polygon_np = None
                        if polygon_points and len(polygon_points) >= 3:
                            polygon_np = np.array(polygon_points, dtype=np.int32)
                            
                        colors = np.random.uniform(0, 255, size=(len(activity_detection_service.tf_labels) + 1, 3))
                        img_annotated = img.copy()
                        
                        if polygon_np is not None:
                            cv2.polylines(img_annotated, [polygon_np], isClosed=True, color=(0, 255, 0), thickness=2)
                            
                        for i in range(num_detections):
                            score = float(detection_scores[i])
                            if score < 0.5:
                                continue
                                
                            class_idx = int(detection_classes[i]) - 1
                            if class_idx < 0 or class_idx >= len(activity_detection_service.tf_labels):
                                continue
                                
                            label = activity_detection_service.tf_labels[class_idx]
                            label_clean = label.lower().strip()
                            
                            if label == "N/A" or label_clean not in target_labels:
                                continue
                                
                            bbox_norm = detection_boxes[i]
                            ymin = int(bbox_norm[0] * h_orig)
                            xmin = int(bbox_norm[1] * w_orig)
                            ymax = int(bbox_norm[2] * h_orig)
                            xmax = int(bbox_norm[3] * w_orig)
                            
                            center_x = (xmin + xmax) // 2
                            center_y = (ymin + ymax) // 2
                            if polygon_np is not None:
                                is_inside = cv2.pointPolygonTest(polygon_np, (float(center_x), float(center_y)), False) >= 0
                                if not is_inside:
                                    continue
                                    
                            severity = "info"
                            if label_clean in ["fall down", "fight/hit (a person)", "push (another person)", "grab (a person)"]:
                                severity = "critical"
                            elif label_clean in ["run/jog", "crouch/kneel", "get up", "jump/leap"]:
                                severity = "warning"
                                
                            # Annotate frame
                            color = colors[class_idx + 1]
                            cv2.rectangle(img_annotated, (xmin, ymin), (xmax, ymax), color, 2)
                            text = f"{label} ({score:.2f})"
                            cv2.putText(img_annotated, text, (xmin, max(ymin - 10, 20)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                                        
                            # Save alert snapshot
                            snapshot_filename = f"{media.id}_{label.replace('/', '_')}_trackNone_0.jpg"
                            snapshot_path = os.path.join(ALERT_SNAPSHOTS_DIR, snapshot_filename)
                            cv2.imwrite(snapshot_path, img_annotated)
                            
                            await repo.create_activity_alert(
                                tenant_id=media.tenant_id,
                                gallery_media_id=media.id,
                                track_id=None,
                                activity_type=label,
                                timestamp=0.0,
                                bbox=[xmin, ymin, xmax, ymax],
                                snapshot_path=snapshot_path,
                                severity=severity
                            )
                        # Save main output image
                        cv2.imwrite(output_filepath, img_annotated)
                else:
                    # For videos, call the TF video processing generator
                    for alert in activity_detection_service.process_video_tf(
                        video_path=media.filepath,
                        output_video_path=output_filepath,
                        polygon_points=polygon_points,
                        selected_activities=selected_activities,
                        detect_fall=detect_fall,
                        detect_sleeping=detect_sleeping,
                        detect_walking=detect_walking,
                        interval=interval
                    ):
                        orig_frame = alert["frame"]
                        bbox = alert["bbox"]
                        activity_type = alert["activity_type"]
                        timestamp = alert["timestamp"]
                        severity = alert["severity"]
                        
                        # Generate alert snapshot
                        snapshot_filename = f"{media.id}_{activity_type.replace('/', '_')}_trackNone_{int(timestamp * 1000)}.jpg"
                        snapshot_path = os.path.join(ALERT_SNAPSHOTS_DIR, snapshot_filename)
                        
                        # Write the annotated keyframe
                        vis_frame = orig_frame.copy()
                        if bbox:
                            x1, y1, x2, y2 = bbox
                            color = (0, 0, 255) if severity == "critical" else (0, 255, 255)
                            cv2.rectangle(vis_frame, (x1, y1), (x2, y2), color, 3)
                            cv2.putText(vis_frame, f"{activity_type.upper()}", (x1, max(y1 - 10, 20)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                        if polygon_points and len(polygon_points) >= 3:
                            pts = np.array(polygon_points, dtype=np.int32)
                            cv2.polylines(vis_frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                            
                        cv2.imwrite(snapshot_path, vis_frame)
                        
                        # Save the alert in database
                        await repo.create_activity_alert(
                            tenant_id=media.tenant_id,
                            gallery_media_id=media.id,
                            track_id=None,
                            activity_type=activity_type,
                            timestamp=timestamp,
                            bbox=bbox,
                            snapshot_path=snapshot_path,
                            severity=severity
                        )

                if media.media_type == "video" and output_filepath:
                    # Transcode output video to browser-compatible H.264 format using shared video utility
                    try:
                        videoFormatChanger(output_filepath, formats="h264", overwrite_input=True)
                    except Exception as e:
                        print(f"Video transcoding failed (falling back to raw mp4v): {e}")

                media.processed_filepath = output_filepath
                media.status = "completed"
                await db.commit()

            except Exception as e:
                print(f"Error executing activity detection task for media {media.id}: {e}")
                media.status = "failed"
                await db.commit()

    run_async(run())
