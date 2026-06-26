import os
import uuid
import logging

logger = logging.getLogger(__name__)
import cv2
cv2.setNumThreads(0)
import torch
torch.set_num_threads(1)
import asyncio
import numpy as np
from sqlalchemy import select
from sklearn.metrics.pairwise import cosine_similarity

from workers.celery import celery_app
from database.session import SessionLocal
from modules.peoplefind.model import FaceSearchSession, MediaSource, FaceSearchResult
from modules.peoplefind.repository import PeopleFindRepository
from services.ai.face_recognition import face_rec_service

VIDEO_MATCHES_DIR = os.path.join("storage", "video_matches")
os.makedirs(VIDEO_MATCHES_DIR, exist_ok=True)

def run_async(coro):
    """Utility helper to run async coroutines inside synchronous Celery tasks."""
    async def wrapper():
        try:
            return await coro
        finally:
            from database.session import engine
            await engine.dispose()
    return asyncio.run(wrapper())

def format_time(seconds: float) -> str:
    """Formats float seconds into HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def group_timestamps(seconds_list: list, max_gap: float) -> list:
    """Groups consecutive detection seconds into continuous intervals."""
    if not seconds_list:
        return []
    sorted_secs = sorted(seconds_list)
    intervals = []
    start = sorted_secs[0]
    prev = sorted_secs[0]
    for sec in sorted_secs[1:]:
        if sec - prev <= max_gap:
            prev = sec
        else:
            intervals.append((start, prev))
            start = sec
            prev = sec
    intervals.append((start, prev))
    return intervals

def check_segment_intersection(p1, p2, q1, q2):
    """
    Checks if segment p1p2 intersects with segment q1q2.
    """
    def ccw(A, B, C):
        return (C[1] - A[1]) * (B[0] - A[0]) > (B[1] - A[1]) * (C[0] - A[0])
        
    return ccw(p1, q1, q2) != ccw(p2, q1, q2) and ccw(p1, p2, q1) != ccw(p1, p2, q2)


def draw_bbox_on_image(img, bbox, similarity, timestamp_str):
    """Draws a green bounding box and match details on the frame."""
    vis = img.copy()
    x1, y1, x2, y2 = bbox
    cv2.rectangle(vis, (x1, y1), (x2, y2), (0, 255, 0), 3)
    
    label = f"Sim: {similarity:.3f} | {timestamp_str}"
    (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.rectangle(vis, (x1, max(y1 - 30, 0)), (x1 + w, max(y1, 30)), (0, 255, 0), -1)
    cv2.putText(vis, label, (x1, max(y1 - 8, 22)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return vis

@celery_app.task(name="workers.tasks.index_video_task")
def index_video_task(media_source_id_str: str, filepath: str, interval: float = 1.0):
    """
    Celery task to index a video's faces asynchronously.
    """
    media_id = uuid.UUID(media_source_id_str)
    
    async def run():
        async with SessionLocal() as db:
            from modules.peoplefind.service import PeopleFindService
            service = PeopleFindService(db)
            await service._index_video_sync(media_id, filepath, interval)
            
    run_async(run())

@celery_app.task(name="workers.tasks.index_photo_task")
def index_photo_task(media_source_id_str: str, filepath: str):
    """
    Celery task to index a photo's faces asynchronously.
    """
    media_id = uuid.UUID(media_source_id_str)
    
    async def run():
        async with SessionLocal() as db:
            from modules.peoplefind.service import PeopleFindService
            service = PeopleFindService(db)
            await service._index_photo_sync(media_id, filepath)
            
    run_async(run())


@celery_app.task(name="workers.tasks.process_video_search_task")
def process_video_search_task(
    video_id_str: str, 
    session_id_str: str, 
    threshold: float = 0.45, 
    interval: float = 1.0, 
    model_name: str = "buffalo_l"
):
    """
    Celery task to search a target video file on-demand for a target face, 
    annotating and saving keyframes and generating a summary presence report.
    """
    video_id = uuid.UUID(video_id_str)
    session_id = uuid.UUID(session_id_str)

    async def run():
        async with SessionLocal() as db:
            # 1. Load entities from DB without tenant checks for celery background runner
            stmt_session = select(FaceSearchSession).where(
                FaceSearchSession.id == session_id,
                FaceSearchSession.is_delete == False
            )
            res_session = await db.execute(stmt_session)
            session = res_session.scalars().first()
            if not session:
                return

            stmt_media = select(MediaSource).where(
                MediaSource.id == video_id,
                MediaSource.is_delete == False
            )
            res_media = await db.execute(stmt_media)
            media = res_media.scalars().first()
            if not media:
                session.status = "failed"
                await db.commit()
                return

            # Setup matching directories
            session_out_dir = os.path.join(VIDEO_MATCHES_DIR, str(session.id))
            os.makedirs(session_out_dir, exist_ok=True)

            # Load all face embeddings from the reference selfie image if possible
            group_embeddings = []
            if session.selfie_path and os.path.exists(session.selfie_path):
                try:
                    with open(session.selfie_path, "rb") as sf:
                        selfie_content = sf.read()
                    selfie_faces = face_rec_service.extract_faces(selfie_content, model_name=model_name)
                    group_embeddings = [np.array(face["embedding"]) for face in selfie_faces]
                except Exception as e:
                    print(f"Failed to extract group faces from {session.selfie_path}: {e}")

            # Fallback to the single stored database embedding if group extraction failed or detected no faces
            if not group_embeddings:
                group_embeddings = [np.array(session.selfie_embedding)]

            cap = cv2.VideoCapture(media.filepath)
            if not cap.isOpened():
                session.status = "failed"
                await db.commit()
                return

            fps = cap.get(cv2.CAP_PROP_FPS)
            if fps <= 0:
                fps = 30.0

            frame_step = max(1, int(fps * interval))
            f_idx = 0
            matched_seconds = []
            repo = PeopleFindRepository(db)

            while True:
                if f_idx % frame_step == 0:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break

                    # Downscale for CPU speedups
                    h_orig, w_orig = frame.shape[:2]
                    max_dim = 640
                    if max(h_orig, w_orig) > max_dim:
                        scale = max_dim / max(h_orig, w_orig)
                        frame_small = cv2.resize(frame, (int(w_orig * scale), int(h_orig * scale)))
                    else:
                        scale = 1.0
                        frame_small = frame

                    # Encode to bytes
                    _, encoded_img = cv2.imencode(".jpg", frame_small)
                    frame_bytes = encoded_img.tobytes()

                    # Extract face embeddings
                    faces = face_rec_service.extract_faces(frame_bytes, model_name=model_name)

                    if len(faces) > 0:
                        sec = f_idx / fps
                        time_str = format_time(sec)

                        # Match faces in the current frame
                        frame_embeddings = np.array([face["embedding"] for face in faces])
                        similarities = cosine_similarity([ref_embedding], frame_embeddings)[0]

                        best_sim = -1.0
                        best_face = None

                        for idx, sim in enumerate(similarities):
                            if sim >= threshold and sim > best_sim:
                                best_sim = sim
                                best_face = faces[idx]

                        if best_face is not None:
                            # We found a match in the video frame!
                            # Restore coordinates back to original video size
                            x1 = max(0, min(int(best_face["bbox"][0] / scale), w_orig - 1))
                            y1 = max(0, min(int(best_face["bbox"][1] / scale), h_orig - 1))
                            x2 = max(0, min(int(best_face["bbox"][2] / scale), w_orig - 1))
                            y2 = max(0, min(int(best_face["bbox"][3] / scale), h_orig - 1))
                            orig_bbox = [x1, y1, x2, y2]

                            matched_seconds.append(sec)

                            # Save FaceSearchResult in database
                            await repo.create_search_result(
                                session_id=session.id,
                                media_source_id=media.id,
                                similarity=best_sim,
                                bbox=orig_bbox,
                                timestamp=sec
                            )

                            # Annotate frame and save keyframe image
                            vis_frame = draw_bbox_on_image(frame, orig_bbox, best_sim, time_str)
                            time_filename = time_str.replace(":", "_")
                            out_img_path = os.path.join(session_out_dir, f"frame_{time_filename}.jpg")
                            cv2.imwrite(out_img_path, vis_frame)

                    # Fast grab skip
                    for _ in range(frame_step - 1):
                        ret = cap.grab()
                        if not ret:
                            break
                        f_idx += 1
                else:
                    ret = cap.grab()
                    if not ret:
                        break

                f_idx += 1

            cap.release()

            # Group matches into intervals
            max_gap = interval * 2.0
            intervals = group_timestamps(matched_seconds, max_gap)

            # Generate and write txt report
            report_path = os.path.join(session_out_dir, "report.txt")
            with open(report_path, "w") as rf:
                rf.write("=====================================================\n")
                rf.write("  ON-DEMAND VIDEO SEARCH REPORT\n")
                rf.write("=====================================================\n")
                rf.write(f"Video File ID    : {media.id}\n")
                rf.write(f"Original Name    : {media.filename}\n")
                rf.write(f"Search Session   : {session.id}\n")
                rf.write(f"Threshold        : {threshold}\n")
                rf.write(f"Sample Interval  : {interval}s\n")
                rf.write(f"Total Matches    : {len(matched_seconds)} frame(s)\n")
                rf.write("-----------------------------------------------------\n\n")

                if intervals:
                    rf.write("Detected Timestamps (Intervals):\n")
                    for start, end in intervals:
                        if start == end:
                            rf.write(f"  • {format_time(start)}\n")
                        else:
                            rf.write(f"  • {format_time(start)} to {format_time(end)}\n")
                else:
                    rf.write("No matching face detected in the video.\n")

            # Update session status
            session.status = "completed"
            await db.commit()

    run_async(run())


@celery_app.task(name="workers.tasks.index_peoplecount_task")
def index_peoplecount_task(
    media_source_id_str: str,
    filepath: str,
    media_type: str,
    min_track_frames: int = 300,
    track_buffer: int = 150,
    confidence_threshold: float = 0.35
):
    """
    Celery task to run YOLO + ByteTrack to detect, track, and count people in media (photo or video).
    """
    media_id = uuid.UUID(media_source_id_str)
    
    async def run():
        async with SessionLocal() as db:
            from modules.peoplecount.repository import PeopleCountRepository
            from modules.peoplecount.tracker import BYTETracker, STrack
            from modules.peoplecount.reid_model import ReIDExtractor
            from ultralytics import YOLO
            import torch
            
            repo = PeopleCountRepository(db)
            
            # Load weights
            weights_path = os.path.join("storage", "yolo26n.pt")
            if not os.path.exists(weights_path):
                # Fallback to standard yolov8n if yolo26n.pt is missing
                weights_path = "yolov8n.pt"

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = YOLO(weights_path)
            model.to(device)
            
            # Initialize Re-ID Appearance Feature Extractor
            try:
                reid_extractor = ReIDExtractor(device=device)
            except Exception as e:
                logger.error(f"Failed to initialize Re-ID Extractor: {e}. Falling back to spatial tracking.")
                reid_extractor = None

            # Reset ByteTrack static ID counter
            STrack.reset_id_counter()

            if media_type == "photo":
                # Decode image using Pillow for maximum compatibility (HEIC, PNG, JPEG, WEBP, etc.)
                from PIL import Image
                import io
                import pillow_heif
                
                frame = None
                try:
                    pillow_heif.register_heif_opener()
                    with open(filepath, "rb") as f:
                        content = f.read()
                    image = Image.open(io.BytesIO(content))
                    if image.mode != "RGB":
                        image = image.convert("RGB")
                    img_rgb = np.array(image)
                    # Convert RGB to BGR for OpenCV
                    frame = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                except Exception as e:
                    logger.error(f"Pillow image decoding failed: {e}. Falling back to OpenCV.")
                    frame = cv2.imread(filepath)
                
                if frame is None:
                    await repo.update_media_status(media_id, "failed")
                    await db.commit()
                    return
                
                # YOLO detection (filter classes)
                results = model(frame, conf=confidence_threshold, iou=0.5, device=device, verbose=False)
                person_count = 0
                annotated_frame = frame.copy()
                
                if results:
                    result = results[0]
                    boxes = result.boxes
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        class_name = model.names.get(cls_id, "unknown")
                        if class_name == "person":
                            person_count += 1
                            x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy().tolist())
                            # Draw bounding box and label
                            cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                            cv2.putText(annotated_frame, f"Person {person_count}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                
                # Save annotated frame to disk
                out_filename = f"processed_{media_id}.jpg"
                processed_filepath = os.path.join("storage", "peoplecount_outputs", out_filename)
                os.makedirs(os.path.dirname(processed_filepath), exist_ok=True)
                cv2.imwrite(processed_filepath, annotated_frame)
                
                # Update DB
                await repo.update_media_results(
                    media_id=media_id,
                    status="completed",
                    total_people_count=person_count,
                    peak_people_count=person_count,
                    average_people_count=float(person_count),
                    video_duration_seconds=0.0,
                    processed_filepath=processed_filepath
                )
                await db.commit()
                
            elif media_type == "video":
                # Process video
                cap = cv2.VideoCapture(filepath)
                if not cap.isOpened():
                    await repo.update_media_status(media_id, "failed")
                    await db.commit()
                    return
                
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps <= 0:
                    fps = 30.0
                
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                
                # Output video setup
                out_filename = f"processed_{media_id}.mp4"
                processed_filepath = os.path.join("storage", "peoplecount_outputs", out_filename)
                
                # Use mp4v codec
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(processed_filepath, fourcc, fps, (width, height))
                
                tracker = BYTETracker(
                    track_thresh=confidence_threshold,
                    match_thresh=0.8,
                    track_buffer=track_buffer,
                    reid_alpha=0.5,
                    reid_max_dist=0.55
                )
                
                # Track statistics: track_id -> { "first_frame": int, "last_frame": int, "total_frames": int }
                tracks_history = {}
                frame_people_counts = []
                frame_idx = 0
                
                while True:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break
                    
                    # Run YOLO detection with a lower confidence threshold for ByteTrack
                    results = model(frame, conf=0.10, iou=0.5, device=device, verbose=False)
                    detections = []
                    
                    if results:
                        result = results[0]
                        boxes = result.boxes
                        for box in boxes:
                            cls_id = int(box.cls[0].item())
                            class_name = model.names.get(cls_id, "unknown")
                            
                            # ONLY filter for "person"
                            if class_name == "person":
                                conf = float(box.conf[0].item())
                                xyxy = box.xyxy[0].cpu().numpy().tolist()
                                detections.append({
                                    "box": xyxy,
                                    "confidence": conf
                                })
                    
                    # Extract Re-ID appearance features for cropped boxes on scheduled frames
                    is_reid_frame = (frame_idx % 1 == 0)
                    if reid_extractor and detections and is_reid_frame:
                        crops = []
                        valid_indices = []
                        h, w, _ = frame.shape
                        for idx, det in enumerate(detections):
                            x1, y1, x2, y2 = map(int, det["box"])
                            x1 = max(0, min(x1, w - 1))
                            y1 = max(0, min(y1, h - 1))
                            x2 = max(0, min(x2, w - 1))
                            y2 = max(0, min(y2, h - 1))
                            
                            if (x2 - x1) > 0 and (y2 - y1) > 0:
                                crop = frame[y1:y2, x1:x2]
                                crops.append(crop)
                                valid_indices.append(idx)
                            else:
                                det["feature"] = None
                        
                        if crops:
                            try:
                                features = reid_extractor.extract(crops)
                                for f_idx, det_idx in enumerate(valid_indices):
                                    detections[det_idx]["feature"] = features[f_idx]
                            except Exception as e:
                                logger.error(f"Error during Re-ID feature extraction: {e}")
                                for det_idx in valid_indices:
                                    detections[det_idx]["feature"] = None
                    
                    # Update ByteTracker
                    active_tracks = tracker.update(detections, "person")
                    
                    # Track statistics update
                    frame_people_counts.append(len(active_tracks))
                    for track in active_tracks:
                        tid = track.track_id
                        if tid not in tracks_history:
                            tracks_history[tid] = {
                                "first_frame": frame_idx,
                                "last_frame": frame_idx,
                                "total_frames": 1
                            }
                        else:
                            tracks_history[tid]["last_frame"] = frame_idx
                            tracks_history[tid]["total_frames"] += 1
                        
                        # Draw bounding box and track ID on the frame
                        x1, y1, x2, y2 = [int(v) for v in track.tlbr]
                        cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                        cv2.putText(frame, f"Person {tid}", (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)
                    
                    writer.write(frame)
                    frame_idx += 1
                
                cap.release()
                writer.release()
                
                # Apply noise filter
                filtered_tracks = {tid: info for tid, info in tracks_history.items() if info["total_frames"] >= min_track_frames}
                
                total_unique_people = len(filtered_tracks)
                peak_people = max(frame_people_counts) if frame_people_counts else 0
                avg_people = sum(frame_people_counts) / len(frame_people_counts) if frame_people_counts else 0.0
                video_duration = frame_idx / fps if fps > 0 else 0.0
                
                # Save results in PeopleCountResult table
                for tid, info in filtered_tracks.items():
                    start_time = info["first_frame"] / fps if fps > 0 else 0.0
                    end_time = info["last_frame"] / fps if fps > 0 else 0.0
                    await repo.create_result(
                        media_id=media_id,
                        track_id=tid,
                        first_frame=info["first_frame"],
                        last_frame=info["last_frame"],
                        total_frames=info["total_frames"],
                        start_time=start_time,
                        end_time=end_time,
                        class_name="person"
                    )
                
                # Update media details
                await repo.update_media_results(
                    media_id=media_id,
                    status="completed",
                    total_people_count=total_unique_people,
                    peak_people_count=peak_people,
                    average_people_count=avg_people,
                    video_duration_seconds=video_duration,
                    processed_filepath=processed_filepath
                )
                await db.commit()
                
    run_async(run())


@celery_app.task(name="workers.tasks.index_objectcount_task")
def index_objectcount_task(
    media_source_id_str: str,
    filepath: str,
    media_type: str,
    configs: dict
):
    """
    Celery task to run YOLO + BoT-SORT to detect, track, and count general objects in media.
    """
    media_id = uuid.UUID(media_source_id_str)
    
    async def run():
        async with SessionLocal() as db:
            from modules.objectcount.repository import ObjectCountRepository
            from modules.objectcount.tracker import BoTSORTTracker, STrack
            from modules.objectcount.gender_classifier import InsightFaceGenderClassifier
            from modules.objectcount.reid_model import ReIDExtractor
            from ultralytics import YOLO
            import torch
            
            repo = ObjectCountRepository(db)
            
            # Load weights
            weights_path = os.path.join("storage", "yolo26n.pt")
            if not os.path.exists(weights_path):
                weights_path = "yolov8n.pt"

            device = "cuda" if torch.cuda.is_available() else "cpu"
            model = YOLO(weights_path)
            model.to(device)
            
            # Initialize Re-ID Appearance Feature Extractor
            reid_extractor = None
            if configs.get("use_reid", True):
                try:
                    reid_extractor = ReIDExtractor(device=device)
                except Exception as e:
                    logger.error(f"Failed to initialize Re-ID Extractor: {e}. Falling back to spatial tracking.")
                    reid_extractor = None

            # Initialize Gender Classifier
            gender_classifier = None
            if configs.get("classify_gender", False):
                try:
                    gender_classifier = InsightFaceGenderClassifier(
                        model_path="storage/models/insightface/genderage.onnx"
                    )
                except Exception as e:
                    logger.error(f"Failed to initialize InsightFace Gender Classifier: {e}. Gender classification will be disabled.")
                    gender_classifier = None

            # Reset BoT-SORT static ID counter
            STrack.reset_id_counter()

            # Global Motion Compensation (GMC)
            gmc = None
            gmc_method = configs.get("gmc_method", "sparseOptFlow")
            if gmc_method and gmc_method.lower() != "none":
                try:
                    from ultralytics.trackers.utils.gmc import GMC
                    gmc = GMC(method=gmc_method)
                except Exception as e:
                    logger.error(f"Failed to initialize GMC: {e}. Camera motion compensation will be disabled.")
                    gmc = None

            confidence_threshold = configs.get("confidence_threshold", 0.35)
            min_track_frames = configs.get("min_track_frames", 100)
            track_buffer = configs.get("track_buffer", 150)
            classes_to_track = configs.get("classes_to_track")
            classify_vehicle = configs.get("classify_vehicle", False)
            classify_gender = configs.get("classify_gender", False)
            reid_classes = configs.get("reid_classes", ["person"])
            imgsz = configs.get("imgsz", 480)

            if media_type == "photo":
                # Decode image using Pillow for maximum compatibility (HEIC, PNG, JPEG, WEBP, etc.)
                from PIL import Image
                import io
                import pillow_heif
                
                frame = None
                try:
                    pillow_heif.register_heif_opener()
                    with open(filepath, "rb") as f:
                        content = f.read()
                    image = Image.open(io.BytesIO(content))
                    if image.mode != "RGB":
                        image = image.convert("RGB")
                    img_rgb = np.array(image)
                    # Convert RGB to BGR for OpenCV
                    frame = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
                except Exception as e:
                    logger.error(f"Pillow image decoding failed: {e}. Falling back to OpenCV.")
                    frame = cv2.imread(filepath)
                
                if frame is None:
                    await repo.update_media_status(media_id, "failed")
                    await db.commit()
                    return
                
                # YOLO detection
                results = model(frame, conf=confidence_threshold, iou=0.5, device=device, verbose=False)
                
                detected_counts = {}
                total_detected = 0
                
                vehicle_classes = {"car", "bus", "truck", "motorcycle", "bicycle"}
                
                gender_counts = {
                    "male": 0,
                    "female": 0,
                    "unknown": 0
                }
                
                CLASS_COLORS = {
                    "person": (0, 255, 0),       # Green
                    "vehicle": (255, 0, 0),      # Blue
                    "car": (255, 0, 0),          # Blue
                    "bus": (255, 255, 0),        # Cyan
                    "truck": (255, 0, 255),      # Magenta
                    "motorcycle": (0, 165, 255), # Orange
                    "bicycle": (0, 255, 255),    # Yellow
                }
                
                annotated_frame = frame.copy()
                
                if results:
                    result = results[0]
                    boxes = result.boxes
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        class_name = model.names.get(cls_id, "unknown")
                        
                        if classes_to_track and class_name not in classes_to_track:
                            continue
                            
                        if not classify_vehicle and class_name in vehicle_classes:
                            class_name = "vehicle"
                            
                        detected_counts[class_name] = detected_counts.get(class_name, 0) + 1
                        total_detected += 1
                        
                        # Bounding box coordinates
                        x1, y1, x2, y2 = map(int, box.xyxy[0].cpu().numpy().tolist())
                        
                        # Gender classification for "person" class if enabled
                        resolved_gender = None
                        if class_name == "person" and classify_gender:
                            h, w, _ = frame.shape
                            rx1 = max(0, min(x1, w - 1))
                            ry1 = max(0, min(y1, h - 1))
                            rx2 = max(0, min(x2, w - 1))
                            ry2 = max(0, min(y2, h - 1))
                            
                            box_h = ry2 - ry1
                            if (rx2 - rx1) > 0 and box_h > 0:
                                # Approximate the head region (top 25% of the body box)
                                head_ry2 = ry1 + int(box_h * 0.25)
                                head_ry2 = max(ry1 + 1, min(head_ry2, ry2))
                                head_crop = frame[ry1:head_ry2, rx1:rx2]
                                
                                # Use high-quality face detector to find and align faces in the head region
                                try:
                                    _, encoded_head = cv2.imencode(".jpg", head_crop)
                                    head_bytes = encoded_head.tobytes()
                                    detected_faces = face_rec_service.extract_faces(head_bytes)
                                    
                                    if detected_faces:
                                        valid_faces = []
                                        for face in detected_faces:
                                            fx1, fy1, fx2, fy2 = map(int, face["bbox"])
                                            # Relaxed size and confidence filters for small/distant faces in group photos
                                            if (fx2 - fx1) >= 15 and (fy2 - fy1) >= 15 and face.get("det_score", 0.0) >= 0.40:
                                                valid_faces.append(face)
                                                
                                        if valid_faces:
                                            largest_face = max(valid_faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
                                            gender_val = largest_face.get("gender")
                                            if gender_val is not None:
                                                resolved_gender = "Male" if gender_val == 1 else "Female"
                                except Exception as g_err:
                                    logger.error(f"Face-based gender prediction failed on photo: {g_err}")
                            
                            if not resolved_gender:
                                resolved_gender = "unknown"
                                
                            if resolved_gender == "Male":
                                gender_counts["male"] += 1
                            elif resolved_gender == "Female":
                                gender_counts["female"] += 1
                            else:
                                gender_counts["unknown"] += 1
                        
                        # Draw bounding box and label on annotated frame
                        color = CLASS_COLORS.get(class_name, (0, 255, 0))
                        cv2.rectangle(annotated_frame, (x1, y1), (x2, y2), color, 2)
                        
                        label = class_name
                        if resolved_gender:
                            label += f" ({resolved_gender})"
                        cv2.putText(annotated_frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
                
                # Save annotated frame to disk
                out_filename = f"processed_{media_id}.jpg"
                processed_filepath = os.path.join("storage", "objectcount_outputs", out_filename)
                os.makedirs(os.path.dirname(processed_filepath), exist_ok=True)
                cv2.imwrite(processed_filepath, annotated_frame)
                
                report_summary = {
                    "total_unique_objects": total_detected,
                    "peak_objects_count": total_detected,
                    "average_objects_count": float(total_detected),
                    "unique_counts": detected_counts,
                    "gender_breakdown": gender_counts
                }
                
                # Update DB
                await repo.update_media_results(
                    media_id=media_id,
                    status="completed",
                    total_objects_count=total_detected,
                    peak_objects_count=total_detected,
                    average_objects_count=float(total_detected),
                    video_duration_seconds=0.0,
                    processed_filepath=processed_filepath,
                    classify_gender=classify_gender,
                    classify_vehicle=classify_vehicle,
                    classes_to_track=classes_to_track,
                    report_summary=report_summary
                )
                await db.commit()
                
            elif media_type == "video":
                # Process video
                cap = cv2.VideoCapture(filepath)
                if not cap.isOpened():
                    await repo.update_media_status(media_id, "failed")
                    await db.commit()
                    return
                
                fps = cap.get(cv2.CAP_PROP_FPS)
                if fps <= 0:
                    fps = 30.0
                
                width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                logger.info(f"Processing video: {width}x{height} @ {fps} fps, total {total_frames} frames.")
                
                # Output video setup
                out_filename = f"processed_{media_id}.mp4"
                processed_filepath = os.path.join("storage", "objectcount_outputs", out_filename)
                
                # Use mp4v codec
                fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                writer = cv2.VideoWriter(processed_filepath, fourcc, fps, (width, height))
                
                # Trackers cache class-wise
                trackers = {}
                
                # Track statistics
                tracks_history = {}
                frame_objects_counts = []
                frame_idx = 0
                
                # Line crossing variables
                entry_exit_report = configs.get("entry_exit_report", False)
                line_coords_raw = configs.get("line_coords")
                line_coords = None
                line_crossing_entries = 0
                line_crossing_exits = 0
                line_crossing_class_counts = {}

                if entry_exit_report:
                    if line_coords_raw and len(line_coords_raw) == 2:
                        try:
                            line_coords = [tuple(map(int, p)) for p in line_coords_raw]
                        except Exception as e:
                            logger.error(f"Failed to parse line_coords: {e}")
                            line_coords = [(0, height // 2), (width, height // 2)]
                    else:
                        # Default to middle horizontal line
                        line_coords = [(0, height // 2), (width, height // 2)]
                
                CLASS_COLORS = {
                    "person": (0, 255, 0),       # Green
                    "vehicle": (255, 0, 0),      # Blue
                    "car": (255, 0, 0),          # Blue
                    "bus": (255, 255, 0),        # Cyan
                    "truck": (255, 0, 255),      # Magenta
                    "motorcycle": (0, 165, 255), # Orange
                    "bicycle": (0, 255, 255),    # Yellow
                }
                
                vehicle_classes = {"car", "bus", "truck", "motorcycle", "bicycle"}
                
                while True:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break
                    
                    if frame_idx % 10 == 0:
                        logger.info(f"Processing frame {frame_idx}/{total_frames}...")
                        if total_frames > 0:
                            progress = int((frame_idx / total_frames) * 100)
                            try:
                                import redis.asyncio as aioredis
                                from configs.base import settings
                                r_client = aioredis.Redis.from_url(settings.REDIS_URL, decode_responses=True)
                                await r_client.setex(f"objectcount:progress:{media_id}", 3600, str(progress))
                                await r_client.close()
                            except Exception as re_err:
                                logger.error(f"Failed to update progress in Redis: {re_err}")
                    
                    results = model(frame, conf=0.10, iou=0.5, imgsz=imgsz, device=device, verbose=False)
                    detections = []
                    
                    if results:
                        result = results[0]
                        boxes = result.boxes
                        for box in boxes:
                            cls_id = int(box.cls[0].item())
                            class_name = model.names.get(cls_id, "unknown")
                            
                            if classes_to_track and class_name not in classes_to_track:
                                continue
                                
                            if not classify_vehicle and class_name in vehicle_classes:
                                class_name = "vehicle"
                                
                            conf = float(box.conf[0].item())
                            xyxy = box.xyxy[0].cpu().numpy().tolist()
                            detections.append({
                                "box": xyxy,
                                "confidence": conf,
                                "class_name": class_name
                            })
                            
                    # GMC warp matrix
                    H = np.eye(2, 3)
                    if gmc is not None:
                        try:
                            gmc_dets = np.array([d["box"] for d in detections]) if detections else None
                            H = gmc.apply(frame, gmc_dets)
                        except Exception as e:
                            logger.error(f"Error computing GMC: {e}")
                            H = np.eye(2, 3)

                    # Extract Re-ID appearance features (filtered by reid_classes to match POC)
                    reid_interval = configs.get("reid_interval", 2)
                    is_reid_frame = (frame_idx % reid_interval == 0)
                    if reid_extractor and detections and is_reid_frame:
                        crops = []
                        valid_indices = []
                        h_f, w_f, _ = frame.shape
                        for idx, det in enumerate(detections):
                            # Only extract ReID features for specified classes (e.g. person)
                            # osnet is a person-ReID model, applying it to vehicles produces
                            # garbage features that corrupt tracking association
                            if reid_classes and det["class_name"] not in reid_classes:
                                det["feature"] = None
                                continue

                            x1, y1, x2, y2 = map(int, det["box"])
                            x1 = max(0, min(x1, w_f - 1))
                            y1 = max(0, min(y1, h_f - 1))
                            x2 = max(0, min(x2, w_f - 1))
                            y2 = max(0, min(y2, h_f - 1))
                            
                            if (x2 - x1) > 0 and (y2 - y1) > 0:
                                crops.append(frame[y1:y2, x1:x2])
                                valid_indices.append(idx)
                            else:
                                det["feature"] = None
                                
                        if crops:
                            try:
                                features = reid_extractor.extract(crops)
                                for f_idx, det_idx in enumerate(valid_indices):
                                    detections[det_idx]["feature"] = features[f_idx]
                            except Exception as e:
                                logger.error(f"Error during Re-ID extraction: {e}")
                                for det_idx in valid_indices:
                                    detections[det_idx]["feature"] = None
                    else:
                        for det in detections:
                            if "feature" not in det:
                                det["feature"] = None

                    # Class-wise update of BoT-SORT trackers
                    frame_tracks = []
                    present_classes = set(d["class_name"] for d in detections)
                    active_trackers = set(trackers.keys())
                    all_classes_to_update = present_classes.union(active_trackers)
                    
                    for class_name in all_classes_to_update:
                        if class_name not in trackers:
                            trackers[class_name] = BoTSORTTracker(
                                track_thresh=confidence_threshold,
                                match_thresh=0.8,
                                track_buffer=max(track_buffer, 300),
                                reid_alpha=0.5,
                                reid_max_dist=0.55
                            )
                        class_dets = [d for d in detections if d["class_name"] == class_name]
                        active_tracks = trackers[class_name].update(class_dets, H, class_name)
                        frame_tracks.extend(active_tracks)

                    # Dynamic Gender Classification
                    if configs.get("classify_gender", False) and frame_tracks:
                        h_f, w_f, _ = frame.shape
                        for track in frame_tracks:
                            if track.class_name == "person":
                                if track.visible_frames >= 30 and len(track.gender_history) < 10:
                                    if track.visible_frames % 3 == 0:
                                        box = track.tlbr
                                        if box is not None:
                                            x1, y1, x2, y2 = map(int, box)
                                            x1 = max(0, min(x1, w_f - 1))
                                            y1 = max(0, min(y1, h_f - 1))
                                            x2 = max(0, min(x2, w_f - 1))
                                            y2 = max(0, min(y2, h_f - 1))
                                            
                                            box_h = y2 - y1
                                            if (x2 - x1) > 0 and box_h > 0:
                                                head_y2 = y1 + int(box_h * 0.25)
                                                head_y2 = max(y1 + 1, min(head_y2, y2))
                                                head_crop = frame[y1:head_y2, x1:x2]
                                                
                                                # Use the high-quality face detector to verify if a face is actually visible
                                                _, encoded_head = cv2.imencode(".jpg", head_crop)
                                                head_bytes = encoded_head.tobytes()
                                                detected_faces = face_rec_service.extract_faces(head_bytes)
                                                
                                                if detected_faces:
                                                    valid_faces = []
                                                    for face in detected_faces:
                                                        fx1, fy1, fx2, fy2 = map(int, face["bbox"])
                                                        
                                                        # 1. Relaxed size filter (ignores tiny/distant blurry faces)
                                                        if (fx2 - fx1) < 28 or (fy2 - fy1) < 28:
                                                            continue
                                                            
                                                        # 2. Relaxed confidence filter (ignores false face detections)
                                                        if face.get("det_score", 0.0) < 0.60:
                                                            continue
                                                            
                                                        # 3. Keypoints containment filter (ensures full face is visible)
                                                        kps = face.get("kps")
                                                        is_full_face = True
                                                        if kps:
                                                            margin_x = int((fx2 - fx1) * 0.05)
                                                            margin_y = int((fy2 - fy1) * 0.05)
                                                            limit_x1 = fx1 - margin_x
                                                            limit_x2 = fx2 + margin_x
                                                            limit_y1 = fy1 - margin_y
                                                            limit_y2 = fy2 + margin_y
                                                            
                                                            for kp in kps:
                                                                kp_x, kp_y = kp
                                                                if not (limit_x1 <= kp_x <= limit_x2 and limit_y1 <= kp_y <= limit_y2):
                                                                    is_full_face = False
                                                                    break
                                                        if not is_full_face:
                                                            continue
                                                            
                                                        # (Occlusion filter removed to prevent false-positives on beards/shadows)
                                                        valid_faces.append(face)
                                                    
                                                    if valid_faces:
                                                        # Use the highly accurate built-in landmark-aligned gender prediction
                                                        largest_face = max(valid_faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
                                                        gender_val = largest_face.get("gender")
                                                        if gender_val is not None:
                                                            gender_label = "Male" if gender_val == 1 else "Female"
                                                            track.gender_history.append((gender_label, largest_face.get("det_score", 0.90)))
                                                            
                                                            genders = [g for g, c in track.gender_history]
                                                            from collections import Counter
                                                            track.gender = Counter(genders).most_common(1)[0][0]
                                                            matching_confs = [c for g, c in track.gender_history if g == track.gender]
                                                            track.gender_conf = sum(matching_confs) / len(matching_confs) if matching_confs else 0.0

                    # Accumulate frame counts and track histories
                    frame_objects_counts.append(len(frame_tracks))
                    for track in frame_tracks:
                        tid = track.track_id
                        g_lbl = getattr(track, "gender", None)
                        
                        # Get bounding box center
                        x1, y1, x2, y2 = [int(v) for v in track.tlbr]
                        cx = int(x1 + (x2 - x1) / 2)
                        cy = int(y1 + (y2 - y1) / 2)
                        current_pos = (cx, cy)
                        
                        if tid not in tracks_history:
                            side_val = None
                            if line_coords is not None:
                                p_a, p_b = line_coords
                                side_val_num = (p_b[0] - p_a[0]) * (cy - p_a[1]) - (p_b[1] - p_a[1]) * (cx - p_a[0])
                                side_val = 1 if side_val_num >= 0 else -1

                            tracks_history[tid] = {
                                "class_name": track.class_name,
                                "gender": g_lbl,
                                "first_frame": frame_idx,
                                "last_frame": frame_idx,
                                "total_frames": 1,
                                "last_position": current_pos,
                                "last_side": side_val
                            }
                        else:
                            prev_pos = tracks_history[tid].get("last_position")
                            tracks_history[tid]["last_frame"] = frame_idx
                            tracks_history[tid]["total_frames"] += 1
                            if g_lbl:
                                tracks_history[tid]["gender"] = g_lbl

                            # Line crossing check
                            if line_coords is not None and prev_pos is not None:
                                p_a, p_b = line_coords
                                side_val_num = (p_b[0] - p_a[0]) * (cy - p_a[1]) - (p_b[1] - p_a[1]) * (cx - p_a[0])
                                current_side = 1 if side_val_num >= 0 else -1
                                
                                last_side = tracks_history[tid].get("last_side")
                                if last_side is not None and last_side != current_side:
                                    if check_segment_intersection(prev_pos, current_pos, p_a, p_b):
                                        cname_mapped = track.class_name
                                        if last_side == -1 and current_side == 1:
                                            line_crossing_entries += 1
                                            if cname_mapped not in line_crossing_class_counts:
                                                line_crossing_class_counts[cname_mapped] = {"entry": 0, "exit": 0}
                                            line_crossing_class_counts[cname_mapped]["entry"] += 1
                                        elif last_side == 1 and current_side == -1:
                                            line_crossing_exits += 1
                                            if cname_mapped not in line_crossing_class_counts:
                                                line_crossing_class_counts[cname_mapped] = {"entry": 0, "exit": 0}
                                            line_crossing_class_counts[cname_mapped]["exit"] += 1
                                        
                                        tracks_history[tid]["last_side"] = current_side
                                elif last_side is None:
                                    tracks_history[tid]["last_side"] = current_side
                            
                            tracks_history[tid]["last_position"] = current_pos
                                
                        # Visual drawing
                        color = CLASS_COLORS.get(track.class_name, (200, 200, 200))
                        
                        # Draw bounding box
                        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                        
                        # Label construction
                        label = f"{track.class_name.capitalize()} #{tid}"
                        if track.class_name == "person" and g_lbl:
                            label += f" ({g_lbl})"
                            
                        cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                    # Visual drawing of the line if enabled
                    if line_coords is not None:
                        # Draw main crossing line in gold/orange color
                        cv2.line(frame, line_coords[0], line_coords[1], (0, 165, 255), 3)
                        # End point markers
                        cv2.circle(frame, line_coords[0], 6, (0, 0, 255), -1)
                        cv2.circle(frame, line_coords[1], 6, (0, 0, 255), -1)
                        
                        # Draw directional labels near the midpoint of the line
                        p_a, p_b = line_coords
                        mid_x = (p_a[0] + p_b[0]) // 2
                        mid_y = (p_a[1] + p_b[1]) // 2
                        
                        dx = p_b[0] - p_a[0]
                        dy = p_b[1] - p_a[1]
                        length = np.sqrt(dx*dx + dy*dy)
                        if length > 0:
                            nx = -dy / length
                            ny = dx / length
                            
                            # Offset labels 25 pixels normal to the line
                            in_x = int(mid_x + 25 * nx)
                            in_y = int(mid_y + 25 * ny)
                            out_x = int(mid_x - 25 * nx)
                            out_y = int(mid_y - 25 * ny)
                            
                            font = cv2.FONT_HERSHEY_SIMPLEX
                            cv2.putText(frame, "IN", (in_x - 10, in_y + 5), font, 0.5, (0, 255, 0), 2, cv2.LINE_AA)
                            cv2.putText(frame, "OUT", (out_x - 15, out_y + 5), font, 0.5, (0, 0, 255), 2, cv2.LINE_AA)

                    # Compute live counts for HUD
                    live_counts = {}
                    for track in frame_tracks:
                        cname = track.class_name
                        live_counts[cname] = live_counts.get(cname, 0) + 1
                        
                    unique_counts_live = {}
                    for tid, info in tracks_history.items():
                        if info["total_frames"] >= min_track_frames:
                            cname = info["class_name"]
                            unique_counts_live[cname] = unique_counts_live.get(cname, 0) + 1

                    # Overlay HUD Dashboard
                    hud_y = 30
                    for cname, u_cnt in sorted(unique_counts_live.items()):
                        l_cnt = live_counts.get(cname, 0)
                        hud_text = f"Unique {cname.capitalize()}: {u_cnt} | Live: {l_cnt}"
                        cv2.putText(frame, hud_text, (20, hud_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2)
                        hud_y += 25

                    if line_coords is not None:
                        hud_text = f"Total Entries: {line_crossing_entries} | Exits: {line_crossing_exits}"
                        cv2.putText(frame, hud_text, (20, hud_y), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 165, 255), 2)
                        hud_y += 25

                    writer.write(frame)
                    frame_idx += 1
                    
                cap.release()
                writer.release()
                
                # Apply noise filter to get final results
                filtered_tracks = {tid: info for tid, info in tracks_history.items() if info["total_frames"] >= min_track_frames}
                
                # Calculate aggregated metrics
                total_unique_objects = len(filtered_tracks)
                peak_objects = max(frame_objects_counts) if frame_objects_counts else 0
                avg_objects = sum(frame_objects_counts) / len(frame_objects_counts) if frame_objects_counts else 0.0
                video_duration = frame_idx / fps if fps > 0 else 0.0
                
                unique_counts = {}
                male_count = 0
                female_count = 0
                unknown_count = 0
                
                for tid, info in filtered_tracks.items():
                    cname = info["class_name"]
                    unique_counts[cname] = unique_counts.get(cname, 0) + 1
                    
                    if cname == "person":
                        g_lbl = info.get("gender")
                        if g_lbl == "Male":
                            male_count += 1
                        elif g_lbl == "Female":
                            female_count += 1
                        else:
                            unknown_count += 1
                            
                    # Save details in database ObjectCountResult table
                    start_time = info["first_frame"] / fps if fps > 0 else 0.0
                    end_time = info["last_frame"] / fps if fps > 0 else 0.0
                    await repo.create_result(
                        media_id=media_id,
                        track_id=tid,
                        class_name=cname,
                        gender=info.get("gender"),
                        first_frame=info["first_frame"],
                        last_frame=info["last_frame"],
                        total_frames=info["total_frames"],
                        start_time=start_time,
                        end_time=end_time
                    )
                    
                report_summary = {
                    "total_unique_objects": total_unique_objects,
                    "peak_objects_count": peak_objects,
                    "average_objects_count": avg_objects,
                    "unique_counts": unique_counts,
                    "gender_breakdown": {
                        "male": male_count,
                        "female": female_count,
                        "unknown": unknown_count
                    }
                }
                
                if line_coords is not None:
                    report_summary["line_crossing_analytics"] = {
                        "line_coords": line_coords,
                        "total_entries": line_crossing_entries,
                        "total_exits": line_crossing_exits,
                        "class_breakdown": line_crossing_class_counts
                    }
                
                # Update media details
                await repo.update_media_results(
                    media_id=media_id,
                    status="completed",
                    total_objects_count=total_unique_objects,
                    peak_objects_count=peak_objects,
                    average_objects_count=avg_objects,
                    video_duration_seconds=video_duration,
                    processed_filepath=processed_filepath,
                    classify_gender=classify_gender,
                    classify_vehicle=classify_vehicle,
                    classes_to_track=classes_to_track,
                    report_summary=report_summary
                )
                await db.commit()
                
    run_async(run())

