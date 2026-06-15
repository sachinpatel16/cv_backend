import os
import uuid
import logging

logger = logging.getLogger(__name__)
import cv2
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
    return asyncio.run(coro)

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
def index_peoplecount_task(media_source_id_str: str, filepath: str, media_type: str):
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
                # Process photo
                frame = cv2.imread(filepath)
                if frame is None:
                    await repo.update_media_status(media_id, "failed")
                    await db.commit()
                    return
                
                # YOLO detection (filter classes)
                results = model(frame, conf=0.35, iou=0.5, device=device, verbose=False)
                person_count = 0
                if results:
                    result = results[0]
                    boxes = result.boxes
                    for box in boxes:
                        cls_id = int(box.cls[0].item())
                        class_name = model.names.get(cls_id, "unknown")
                        if class_name == "person":
                            person_count += 1
                
                # Update DB
                await repo.update_media_results(
                    media_id=media_id,
                    status="completed",
                    total_people_count=person_count,
                    peak_people_count=person_count,
                    average_people_count=float(person_count),
                    video_duration_seconds=0.0,
                    processed_filepath=None
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
                    track_thresh=0.35,
                    match_thresh=0.8,
                    track_buffer=150,
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
                
                # Apply noise filter: only count tracks active for >= 300 frames (matches POC config.yaml)
                min_track_frames = 300
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
