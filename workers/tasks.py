import os
import uuid
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

@celery_app.task(name="workers.tasks.process_video_search_task")
def process_video_search_task(video_id_str: str, session_id_str: str, threshold: float = 0.45, interval: float = 1.0):
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

            ref_embedding = np.array(session.selfie_embedding)
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
                    faces = face_rec_service.extract_faces(frame_bytes)
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
