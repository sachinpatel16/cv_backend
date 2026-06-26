import os
import uuid
import cv2
import numpy as np
from sqlalchemy import select

from workers.celery import celery_app
from database.session import SessionLocal
from modules.activity.model import ActivityMedia, ActivityConfig, ActivityAlert
from modules.activity.repository import ActivityRepository
from services.ai.activity_detection import activity_detection_service
from workers.utils import run_async

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
            stmt = select(ActivityMedia).where(
                ActivityMedia.id == media_id,
                ActivityMedia.is_delete == False
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
                ActivityConfig.activity_media_id == media.id,
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

            try:
                # 3. Process video frame-by-frame
                for alert in activity_detection_service.process_video(
                    video_path=media.filepath,
                    polygon_points=polygon_points,
                    detect_fall=detect_fall,
                    detect_aggression=detect_aggression,
                    detect_intrusion=detect_intrusion,
                    detect_loitering=detect_loitering,
                    loitering_threshold=loitering_threshold,
                    detect_occupancy=detect_occupancy,
                    occupancy_limit=occupancy_limit,
                    detect_sleeping=detect_sleeping,
                    detect_walking=detect_walking,
                    interval=interval
                ):
                    orig_frame = alert["frame"]
                    bbox = alert["bbox"]
                    activity_type = alert["activity_type"]
                    timestamp = alert["timestamp"]
                    track_id = alert["track_id"]
                    severity = alert["severity"]

                    # Generate a unique path for the alert snapshot
                    snapshot_filename = f"{media.id}_{activity_type}_track{track_id}_{int(timestamp * 1000)}.jpg"
                    snapshot_path = os.path.join(ALERT_SNAPSHOTS_DIR, snapshot_filename)

                    # Generate the snapshot image based on alert type
                    if activity_type == "roi_intrusion" and bbox:
                        # Apply black mask except for the bounding box of the intruder (Theft Detection requirement)
                        mask = np.zeros_like(orig_frame)
                        x1, y1, x2, y2 = bbox
                        cv2.rectangle(mask, (x1, y1), (x2, y2), (255, 255, 255), -1)
                        masked_frame = cv2.bitwise_and(orig_frame, mask)
                        
                        # Add red bounding box and label
                        cv2.rectangle(masked_frame, (x1, y1), (x2, y2), (0, 0, 255), 3)
                        cv2.putText(masked_frame, "INTRUDER", (x1, max(y1 - 10, 20)),
                                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 255), 2)
                        
                        # Draw ROI boundary polygon on the snapshot if config exists
                        if polygon_points and len(polygon_points) >= 3:
                            pts = np.array(polygon_points, dtype=np.int32)
                            cv2.polylines(masked_frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                        
                        cv2.imwrite(snapshot_path, masked_frame)
                    else:
                        # Draw bounding box and label on the copy of the original frame
                        vis_frame = orig_frame.copy()
                        if bbox:
                            x1, y1, x2, y2 = bbox
                            if activity_type == "sleeping":
                                color = (255, 120, 0)  # cyan/blue in BGR
                            elif activity_type == "walking":
                                color = (0, 255, 0)    # green in BGR
                            else:
                                color = (0, 0, 255) if severity == "critical" else (0, 255, 255)
                            
                            cv2.rectangle(vis_frame, (x1, y1), (x2, y2), color, 3)
                            label = f"{activity_type.upper()} ID {track_id}"
                            cv2.putText(vis_frame, label, (x1, max(y1 - 10, 20)),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, color, 2)
                        else:
                            # General alert (e.g. occupancy_overlimit)
                            color = (0, 0, 255) if severity == "critical" else (0, 255, 255)
                            cv2.rectangle(vis_frame, (10, 10), (320, 50), (0, 0, 0), -1)
                            cv2.putText(vis_frame, "OCCUPANCY LIMIT EXCEEDED", (15, 38),
                                        cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                        
                        # Draw ROI boundary polygon on the snapshot if config exists
                        if polygon_points and len(polygon_points) >= 3:
                            pts = np.array(polygon_points, dtype=np.int32)
                            cv2.polylines(vis_frame, [pts], isClosed=True, color=(0, 255, 0), thickness=2)
                        
                        cv2.imwrite(snapshot_path, vis_frame)

                    # Save the alert in database
                    await repo.create_activity_alert(
                        tenant_id=media.tenant_id,
                        media_id=media.id,
                        track_id=track_id,
                        activity_type=activity_type,
                        timestamp=timestamp,
                        bbox=bbox,
                        snapshot_path=snapshot_path,
                        severity=severity
                    )
                
                media.status = "completed"
                await db.commit()

            except Exception as e:
                print(f"Error executing activity detection task for media {media.id}: {e}")
                media.status = "failed"
                await db.commit()

    run_async(run())
