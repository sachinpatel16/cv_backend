import os
import uuid
import cv2
import torch
# Prevent OpenCV multi-threading conflicts with Celery fork
cv2.setNumThreads(0)
# Prevent PyTorch thread conflicts
torch.set_num_threads(1)

import numpy as np
from sqlalchemy import select
from ultralytics import YOLO
import supervision as sv

from workers.celery import celery_app
from database.session import SessionLocal
from workers.utils import run_async
from modules.peopleanalytics.model import PeopleAnalyticsSession
from modules.employees.repository import EmployeeRepository
from services.ai.face_recognition import face_rec_service
from services.ai.math_utils import map_similarity_threshold, find_best_match_in_cache
from modules.employees.cache import get_cached_employee_embeddings

@celery_app.task(name="modules.employees.tasks.process_employee_attendance_video_task")
def process_employee_attendance_video_task(
    session_id_str: str,
    filepath: str,
    output_path: str,
    similarity_threshold: float = 0.85,
    confidence_threshold: float = 0.3
):
    """
    Celery background task for standalone employee video attendance tracking.
    """
    session_id = uuid.UUID(session_id_str)

    async def run():
        async with SessionLocal() as db:
            # 1. Fetch the session
            stmt = select(PeopleAnalyticsSession).where(
                PeopleAnalyticsSession.id == session_id,
                PeopleAnalyticsSession.is_delete == False
            )
            res = await db.execute(stmt)
            session = res.scalars().first()
            if not session:
                return

            # Update session status to processing
            session.status = "processing"
            await db.commit()

            try:
                # 2. Open input video
                cap = cv2.VideoCapture(filepath)
                if not cap.isOpened():
                    raise ValueError("Could not open input video file.")

                orig_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                orig_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

                # Initialize video writer
                os.makedirs(os.path.dirname(output_path), exist_ok=True)
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                output_writer = cv2.VideoWriter(output_path, fourcc, fps, (orig_width, orig_height))

                # Initialize AI tools
                # Initialize Redis client if needed
                from database.redis import get_redis_client, init_redis
                if get_redis_client() is None:
                    await init_redis()
                # Load employee embeddings from cache (or DB)
                employee_cache = await get_cached_employee_embeddings(db, session.tenant_id)

                from configs.base import settings
                model = YOLO(settings.YOLO_MODEL)
                tracker = sv.ByteTrack(
                    frame_rate=int(fps),
                    lost_track_buffer=int(fps * 10)  # Keep lost tracks in memory for up to 10 seconds (default 30 frames)
                )
                emp_repo = EmployeeRepository(db)

                # Tracking states
                active_tracks = {}
                frame_idx = 0
                unique_employees = set()

                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break

                    timestamp_sec = frame_idx / fps
                    frame_idx += 1

                    # Run person-only inference
                    results = model(
                        frame,
                        conf=float(confidence_threshold),
                        classes=[0],
                        imgsz=settings.YOLO_IMGSZ,
                        verbose=False
                    )
                    detections = sv.Detections.from_ultralytics(results[0])
                    detections = tracker.update_with_detections(detections)

                    if detections.tracker_id is not None:
                        for xyxy, tracker_id in zip(detections.xyxy, detections.tracker_id):
                            if tracker_id is None:
                                continue

                            x1, y1, x2, y2 = map(int, xyxy)
                            x1, y1 = max(0, x1), max(0, y1)
                            x2, y2 = min(frame.shape[1], x2), min(frame.shape[0], y2)

                            if tracker_id not in active_tracks:
                                from datetime import datetime, timezone
                                now_ts = datetime.now(timezone.utc)
                                crop = frame[y1:y2, x1:x2]
                                active_tracks[tracker_id] = {
                                    "type": "visitor",
                                    "id": None,
                                    "first_seen": timestamp_sec,
                                    "last_seen": timestamp_sec,
                                    "first_seen_timestamp": now_ts,
                                    "last_seen_timestamp": now_ts,
                                    "occurrences": 1,
                                    "best_crop": crop if crop is not None and crop.size > 0 else None,
                                    "best_crop_area": (x2 - x1) * (y2 - y1) if crop is not None and crop.size > 0 else 0,
                                    "matched": False,
                                    "frames_since_start": 1,
                                    "face_attempts": 0,
                                    "label": f"Track #{tracker_id}",
                                    "color": (200, 200, 200)
                                }
                            else:
                                from datetime import datetime, timezone
                                track_info = active_tracks[tracker_id]
                                track_info["last_seen"] = timestamp_sec
                                track_info["last_seen_timestamp"] = datetime.now(timezone.utc)
                                track_info["frames_since_start"] += 1
                                
                                crop = frame[y1:y2, x1:x2]
                                if crop is not None and crop.size > 0:
                                    area = (x2 - x1) * (y2 - y1)
                                    if area > track_info["best_crop_area"]:
                                        track_info["best_crop_area"] = area
                                        track_info["best_crop"] = crop

                            track_info = active_tracks[tracker_id]
                            
                            # Match track when it reaches at least 3 frames, check every 5 frames (cap at 100 attempts)
                            if not track_info["matched"] and track_info.get("face_attempts", 0) < 100 and track_info["frames_since_start"] >= 3 and (track_info["frames_since_start"] % 5 == 0 or track_info["frames_since_start"] == 3):
                                crop = frame[y1:y2, x1:x2]
                                if crop is not None and crop.size > 0:
                                    track_info["face_attempts"] = track_info.get("face_attempts", 0) + 1
                                    _, encoded_img = cv2.imencode(".jpg", crop)
                                    crop_bytes = encoded_img.tobytes()
                                    faces = face_rec_service.extract_faces(crop_bytes)
                                    if faces:
                                        largest_face = max(faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
                                        embedding = np.array(largest_face["embedding"], dtype=np.float32)
                                        mapped_threshold = map_similarity_threshold(similarity_threshold)
                                        match_emp = find_best_match_in_cache(embedding, employee_cache, mapped_threshold)
                                        if match_emp:
                                            employee, sim = match_emp
                                            track_info.update({
                                                "type": "employee",
                                                "id": employee.id,
                                                "label": f"{employee.first_name} (EMP)",
                                                "color": (0, 255, 0),
                                                "matched": True
                                            })
                                            unique_employees.add(employee.id)

                            # Draw overlays on the frame
                            label = track_info["label"]
                            color = track_info["color"]
                            cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                            cv2.putText(frame, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

                    # Draw basic HUD on the frame
                    hud_w, hud_h = 325, 95
                    if orig_width > hud_w + 20 and orig_height > hud_h + 20:
                        sub_img = frame[10:10+hud_h, 10:10+hud_w]
                        rect = np.zeros(sub_img.shape, dtype=np.uint8) + 20
                        blended = cv2.addWeighted(sub_img, 0.4, rect, 0.6, 0)
                        frame[10:10+hud_h, 10:10+hud_w] = blended
                        cv2.putText(frame, "EMPLOYEE ATTENDANCE VIDEO", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (0, 255, 255), 2)
                        cv2.putText(frame, f"Employees Checked In: {len(unique_employees)}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                    output_writer.write(frame)

                cap.release()
                output_writer.release()

                # 3. Log employee attendance day-wise
                for tracker_id, track in active_tracks.items():
                    if track["id"] is not None and track["type"] == "employee":
                        await emp_repo.log_employee_attendance(
                            tenant_id=session.tenant_id,
                            employee_id=track["id"],
                            session_id=session.id,
                            first_seen_sec=track["first_seen"],
                            last_seen_sec=track["last_seen"],
                            occurrence_increment=track["occurrences"],
                            detection_time=track.get("first_seen_timestamp")
                        )

                # Update session table details
                from datetime import datetime, timezone
                session.status = "completed"
                session.output_video_path = output_path
                session.total_person_count = len(unique_employees)
                session.unique_person_count = len(unique_employees)
                session.completed_at = datetime.now(timezone.utc)
                await db.commit()

            except Exception as e:
                import traceback
                traceback.print_exc()
                session.status = "failed"
                await db.commit()

    run_async(run())
