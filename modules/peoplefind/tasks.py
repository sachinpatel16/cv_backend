import os
import uuid
import cv2
import numpy as np
from sqlalchemy import select

from workers.celery import celery_app
from database.session import SessionLocal
from modules.peoplefind.model import FaceSearchSession, MediaSource, FaceSearchResult
from modules.peoplefind.repository import PeopleFindRepository
from services.ai.face_recognition import face_rec_service
from services.ai.math_utils import group_timestamps
from services.ai.visualization import draw_bbox_on_image, format_time
from workers.utils import run_async

VIDEO_MATCHES_DIR = os.path.join("storage", "video_matches")
os.makedirs(VIDEO_MATCHES_DIR, exist_ok=True)


@celery_app.task(name="modules.peoplefind.tasks.index_video_task")
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

@celery_app.task(name="modules.peoplefind.tasks.index_photo_task")
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


@celery_app.task(name="modules.peoplefind.tasks.process_video_search_task")
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
            group_embeddings = face_rec_service.load_search_embeddings(
                session.selfie_path, session.selfie_embedding, model_name=model_name
            )

            matched_seconds = []
            repo = PeopleFindRepository(db)

            try:
                for match in face_rec_service.search_face_in_video(
                    media.filepath, group_embeddings, threshold, interval, model_name
                ):
                    sec = match["timestamp"]
                    best_sim = match["similarity"]
                    orig_bbox = match["bbox"]
                    frame = match["frame"]

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
                    time_str = format_time(sec)
                    label = f"Sim: {best_sim:.3f} | {time_str}"
                    vis_frame = draw_bbox_on_image(frame, orig_bbox, label)
                    time_filename = time_str.replace(":", "_")
                    out_img_path = os.path.join(session_out_dir, f"frame_{time_filename}.jpg")
                    cv2.imwrite(out_img_path, vis_frame)
            except Exception as e:
                print(f"Error during video search execution: {e}")
                session.status = "failed"
                await db.commit()
                return

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
