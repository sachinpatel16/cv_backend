from shared.utils.video_format import videoFormatChanger
import os
import uuid
import cv2
from datetime import datetime, timezone, timedelta
# Prevent OpenCV multi-threading conflicts with Celery fork
cv2.setNumThreads(0)

import torch
# Prevent PyTorch thread conflicts and CPU spinning in Celery child processes
torch.set_num_threads(1)

import numpy as np
from sqlalchemy import select, delete
from collections import defaultdict
from ultralytics import YOLO
import supervision as sv

from workers.celery import celery_app
from database.session import SessionLocal
from workers.utils import run_async
from modules.peopleanalytics.model import PeopleAnalyticsSession, PersonIdentity, PersonEmbedding
from modules.employees.model import Employee
from modules.peopleanalytics.repository import PeopleAnalyticsRepository
from services.ai.people_analytics import LineCrossingCounter
from services.ai.face_recognition import face_rec_service
from services.ai.math_utils import map_similarity_threshold, find_best_match_in_cache, is_face_occluded
from modules.employees.cache import get_cached_employee_embeddings

ANALYTICS_OUTPUTS_DIR = os.path.join("storage", "people_analytics_outputs")
os.makedirs(ANALYTICS_OUTPUTS_DIR, exist_ok=True)

VISITOR_CROPS_DIR = os.path.join("storage", "visitor_crops")
os.makedirs(VISITOR_CROPS_DIR, exist_ok=True)

@celery_app.task(name="modules.peopleanalytics.tasks.process_people_analytics_task")
def process_people_analytics_task(
    session_id_str: str,
    filepath: str,
    line_start: list[int] | None = None,
    line_end: list[int] | None = None,
    similarity_threshold: float = 0.85,
    confidence_threshold: float = 0.3,
    user_id_str: str | None = None,
    track_employees: bool = True,
    register_new_visitors: bool = True,
    track_repeat_visitors: bool = True,
    line_crossing_analysis: bool = True,
    track_occupancy: bool = True
):
    """
    Celery background task for full People Analytics Suite.
    """
    session_id = uuid.UUID(session_id_str)

    async def run():
        async with SessionLocal() as db:
            repo = PeopleAnalyticsRepository(db)
            
            # Fetch the session
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
                # Check if file is image or video
                file_ext = os.path.splitext(filepath)[1].lower()
                is_image = file_ext in {".jpg", ".jpeg", ".png", ".heic", ".heif"}

                # Initialize Redis client if needed
                from database.redis import get_redis_client, init_redis
                if get_redis_client() is None:
                    await init_redis()
                # Load employee embeddings from cache (or DB)
                employee_cache = await get_cached_employee_embeddings(db, session.tenant_id)

                # Instantiate visual tools
                from configs.base import settings
                from shared.utils.model_loader import get_model_path
                model_filename = os.path.basename(settings.YOLO_MODEL)
                weights_path = get_model_path("attendance", model_filename)
                model = YOLO(weights_path)

                if is_image:
                    await _process_image_job(
                        db=db,
                        repo=repo,
                        session=session,
                        filepath=filepath,
                        model=model,
                        employee_cache=employee_cache,
                        similarity_threshold=similarity_threshold,
                        confidence_threshold=confidence_threshold,
                        user_id_str=user_id_str,
                        track_employees=track_employees,
                        register_new_visitors=register_new_visitors,
                        track_repeat_visitors=track_repeat_visitors,
                        track_occupancy=track_occupancy
                    )
                else:
                    await _process_video_job(
                        db=db,
                        repo=repo,
                        session=session,
                        filepath=filepath,
                        model=model,
                        employee_cache=employee_cache,
                        line_start=line_start,
                        line_end=line_end,
                        similarity_threshold=similarity_threshold,
                        confidence_threshold=confidence_threshold,
                        user_id_str=user_id_str,
                        track_employees=track_employees,
                        register_new_visitors=register_new_visitors,
                        track_repeat_visitors=track_repeat_visitors,
                        line_crossing_analysis=line_crossing_analysis,
                        track_occupancy=track_occupancy
                    )

            except Exception as e:
                import traceback
                traceback.print_exc()
                session.status = "failed"
                await db.commit()

    run_async(run())


async def _process_image_job(
    db, repo, session, filepath, model, employee_cache, similarity_threshold, confidence_threshold, user_id_str=None,
    track_employees: bool = True,
    register_new_visitors: bool = True,
    track_repeat_visitors: bool = True,
    track_occupancy: bool = True
):
    # Process static image
    img = cv2.imread(filepath)
    if img is None:
        raise ValueError("Could not read image file.")

    h_orig, w_orig = img.shape[:2]
    
    # Run YOLO (Person only = Class 0)
    results = model(img, conf=float(confidence_threshold), classes=[0], verbose=False)
    boxes = results[0].boxes

    unique_person_count = 0
    first_time_visitor_count = 0
    total_person_count = len(boxes)

    is_face_analysis_needed = track_employees or register_new_visitors or track_repeat_visitors
    seen_identities = set()

    for idx, box in enumerate(boxes):
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        # Validate coordinates
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w_orig, x2), min(h_orig, y2)

        # Find matching face inside the localized person crop
        matched_face = None
        if is_face_analysis_needed:
            crop = img[y1:y2, x1:x2]
            if crop is not None and crop.size > 0:
                _, encoded_crop = cv2.imencode(".jpg", crop)
                crop_bytes = encoded_crop.tobytes()
                try:
                    faces = face_rec_service.extract_faces(crop_bytes)
                except Exception:
                    faces = []

                # Apply the 4 face visibility/quality filters
                valid_faces = []
                for face in faces:
                    fx1, fy1, fx2, fy2 = map(int, face["bbox"])
                    # 1. Size filter
                    if (fx2 - fx1) < 45 or (fy2 - fy1) < 45:
                        continue
                    # 2. Confidence filter
                    if face.get("det_score", 0.0) < 0.70:
                        continue
                    # 3. Keypoints containment filter
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
                    # 4. Occlusion filter
                    if is_face_occluded(crop, kps):
                        continue
                    valid_faces.append(face)

                if valid_faces:
                    matched_face = max(valid_faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))

        identity_id = None
        label = "Person" if not is_face_analysis_needed else "Visitor"
        color = (200, 200, 200) # Gray for face-less/anonymous visitors

        if is_face_analysis_needed and matched_face is not None:
            face_embedding = np.array(matched_face["embedding"], dtype=np.float32)
            mapped_threshold = map_similarity_threshold(similarity_threshold)

            # 1. Check Employees cache
            match_emp = None
            if track_employees:
                match_emp = find_best_match_in_cache(face_embedding, employee_cache, mapped_threshold)
            
            if match_emp:
                employee, sim = match_emp
                identity_id = employee.id
                label = f"{employee.first_name} (EMP)"
                color = (0, 255, 0)
                seen_identities.add(f"employee:{employee.id}")
                
                # Log employee attendance
                await repo.create_employee_attendance(
                    session_id=session.id,
                    employee_id=employee.id,
                    first_seen=0.0,
                    last_seen=0.0,
                    occurrence_count=1
                )
            else:
                # 2. Check Face Visitors
                match_vis = None
                if track_repeat_visitors:
                    match_vis = await repo.find_similar_visitor(session.tenant_id, face_embedding.tolist(), mapped_threshold, class_id=1)
                
                if match_vis:
                    visitor, sim = match_vis
                    identity_id = visitor.id
                    label = f"Visitor #{str(visitor.id)[:4]}"
                    color = (0, 180, 255)
                    seen_identities.add(f"visitor:{visitor.id}")
                    await repo.create_person_embedding(
                        identity_id=visitor.id,
                        embedding=face_embedding.tolist(),
                        bbox=matched_face["bbox"],
                        timestamp=0.0
                    )
                elif register_new_visitors:
                    # 3. Create new Face Visitor
                    visitor = await repo.create_person_identity(session.tenant_id, class_id=1)
                    await repo.create_person_embedding(
                        identity_id=visitor.id,
                        embedding=face_embedding.tolist(),
                        bbox=matched_face["bbox"],
                        timestamp=0.0
                    )
                    identity_id = visitor.id
                    label = "New Visitor"
                    color = (0, 0, 255)
                    seen_identities.add(f"visitor:{visitor.id}")
                    first_time_visitor_count += 1

                # Log visitor occurrence if identity registered
                if identity_id:
                    crop_path = None
                    crop_img = img[y1:y2, x1:x2]
                    if crop_img is not None and crop_img.size > 0:
                        crop_filename = f"{uuid.uuid4()}.jpg"
                        user_crops_dir = os.path.join(VISITOR_CROPS_DIR, user_id_str) if user_id_str else VISITOR_CROPS_DIR
                        os.makedirs(user_crops_dir, exist_ok=True)
                        crop_path = os.path.join(user_crops_dir, crop_filename)
                        cv2.imwrite(crop_path, crop_img)

                    await repo.create_person_occurrence(
                        session_id=session.id,
                        identity_id=identity_id,
                        tracker_id=idx,
                        first_seen=0.0,
                        last_seen=0.0,
                        crop_path=crop_path
                    )
                    # Log visitor daily attendance
                    await repo.log_visitor_attendance(
                        session_id=session.id,
                        identity_id=identity_id,
                        first_seen_sec=0.0,
                        last_seen_sec=0.0,
                        occurrence_increment=1
                    )
        
        # Draw overlays
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    unique_person_count = len(seen_identities)

    # Draw HUD on static image
    if track_occupancy:
        hud_w, hud_h = 320, 140
        if w_orig > hud_w + 20 and h_orig > hud_h + 20:
            sub_img = img[10:10+hud_h, 10:10+hud_w]
            rect = np.zeros(sub_img.shape, dtype=np.uint8) + 20  # dark background
            blended = cv2.addWeighted(sub_img, 0.4, rect, 0.6, 0)
            img[10:10+hud_h, 10:10+hud_w] = blended

            cv2.putText(img, "PEOPLE ANALYTICS SUMMARY", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(img, f"Total Detected: {total_person_count}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            if is_face_analysis_needed:
                cv2.putText(img, f"Unique People: {unique_person_count}", (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(img, f"New Visitors: {first_time_visitor_count}", (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            else:
                cv2.putText(img, "Unique People: N/A", (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(img, "New Visitors: N/A", (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Save output annotated image
    output_filename = f"{uuid.uuid4()}_annotated.jpg"
    user_outputs_dir = os.path.join(ANALYTICS_OUTPUTS_DIR, user_id_str) if user_id_str else ANALYTICS_OUTPUTS_DIR
    os.makedirs(user_outputs_dir, exist_ok=True)
    output_path = os.path.join(user_outputs_dir, output_filename)
    cv2.imwrite(output_path, img)

    # Generate flat occupancy timeline for static image (just 1 frame)
    occupancy_timeline = [{"time_sec": 0, "occupancy": total_person_count}] if track_occupancy else None

    # Update DB Session results
    await repo.update_session_results(
        session_id=session.id,
        unique_person_count=unique_person_count if is_face_analysis_needed else None,
        total_person_count=total_person_count if track_occupancy else None,
        first_time_visitor_count=first_time_visitor_count if is_face_analysis_needed else None,
        peak_occupancy=total_person_count if track_occupancy else None,
        average_occupancy=float(total_person_count) if track_occupancy else None,
        entry_count=None,
        exit_count=None,
        occupancy_timeline=occupancy_timeline if track_occupancy else None,
        output_video_path=output_path
    )
    await db.commit()


async def _process_video_job(
    db, repo, session, filepath, model, employee_cache, line_start, line_end, similarity_threshold, confidence_threshold, user_id_str=None,
    track_employees: bool = True,
    register_new_visitors: bool = True,
    track_repeat_visitors: bool = True,
    line_crossing_analysis: bool = True,
    track_occupancy: bool = True
):
    cap = cv2.VideoCapture(filepath)
    if not cap.isOpened():
        raise ValueError("Could not open video file.")

    orig_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    orig_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

    # Initialize video writer
    output_filename = f"{uuid.uuid4()}_annotated.mp4"
    user_outputs_dir = os.path.join(ANALYTICS_OUTPUTS_DIR, user_id_str) if user_id_str else ANALYTICS_OUTPUTS_DIR
    os.makedirs(user_outputs_dir, exist_ok=True)
    output_path = os.path.join(user_outputs_dir, output_filename)
    fourcc = cv2.VideoWriter_fourcc(*'mp4v')
    output_writer = cv2.VideoWriter(output_path, fourcc, fps, (orig_width, orig_height))

    # Initialize tracker and line crossing
    tracker = sv.ByteTrack(
        frame_rate=int(fps),
        lost_track_buffer=int(fps * 10)  # Keep lost tracks in memory for up to 10 seconds (aligns with employee module)
    )
    line_counter = None
    if line_crossing_analysis and line_start and line_end and len(line_start) == 2 and len(line_end) == 2 and line_start != line_end:
        line_counter = LineCrossingCounter(line_start, line_end)

    # Tracking states
    # tracker_id -> {"type": "employee"|"visitor", "id": UUID, "first_seen": float, "last_seen": float, "occurrences": int, "label": str, "color": tuple}
    active_tracks = {}
    
    # Store complete session records for bulk inserts at the end
    completed_occurrences = []  # List of dicts
    completed_attendance = []   # List of dicts
    completed_visitor_attendance = [] # List of dicts
    completed_crossings = []    # List of dicts
    track_crossings = []        # Temp list of all raw crossing events

    occupancy_history = []
    unique_seen_identities = set()
    first_time_visitors_count = 0
    entry_count = None
    exit_count = None
    peak_occupancy_so_far = 0

    frame_step = max(1, int(fps / 5))  # Process face recognition 5 times per second
    frame_idx = 0
    
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret or frame is None:
            break

        timestamp_sec = frame_idx / fps
        frame_idx += 1

        # Run inference (Person Class only = class 0)
        results = model(frame, conf=float(confidence_threshold), classes=[0], verbose=False)
        detections = sv.Detections.from_ultralytics(results[0])
        detections = tracker.update_with_detections(detections)

        current_occupancy = len(detections) if detections.tracker_id is not None else 0
        occupancy_history.append({"time_sec": round(timestamp_sec, 2), "occupancy": current_occupancy})
        if current_occupancy > peak_occupancy_so_far:
            peak_occupancy_so_far = current_occupancy

        is_face_analysis_needed = track_employees or register_new_visitors or track_repeat_visitors

        if detections.tracker_id is not None:
            for xyxy, class_id, tracker_id in zip(detections.xyxy, detections.class_id, detections.tracker_id):
                if tracker_id is None:
                    continue

                x1, y1, x2, y2 = map(int, xyxy)
                x1, y1 = max(0, x1), max(0, y1)
                x2, y2 = min(orig_width, x2), min(orig_height, y2)

                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2

                # If this is a brand new track
                if tracker_id not in active_tracks:
                    crop = frame[y1:y2, x1:x2]
                    now_ts = datetime.now(timezone.utc)
                    active_tracks[tracker_id] = {
                        "type": "visitor",
                        "id": None,
                        "first_seen": timestamp_sec,
                        "last_seen": timestamp_sec,
                        "first_seen_timestamp": now_ts,
                        "last_seen_timestamp": now_ts,
                        "occurrences": 1,
                        "label": f"Track #{tracker_id}",
                        "color": (200, 200, 200),
                        "best_crop": crop if crop is not None and crop.size > 0 else None,
                        "best_crop_area": (x2 - x1) * (y2 - y1) if crop is not None and crop.size > 0 else 0,
                        "matched": False,
                        "last_match_area": 0,
                        "frames_since_start": 1
                    }
                else:
                    # Update last seen timestamp and best crop info
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
                
                # Check for face inside the localized person crop
                matched_face = None
                # Run face detection periodically if face analysis is needed and track is not fully employee-matched yet
                if is_face_analysis_needed and (not track_info["matched"] or track_info["type"] == "visitor") and frame_idx % frame_step == 0:
                    crop = frame[y1:y2, x1:x2]
                    if crop is not None and crop.size > 0:
                        _, encoded_img = cv2.imencode(".jpg", crop)
                        crop_bytes = encoded_img.tobytes()
                        try:
                            faces = face_rec_service.extract_faces(crop_bytes)
                        except Exception:
                            faces = []

                        # Apply the 4 face visibility/quality filters
                        valid_faces = []
                        for face in faces:
                            fx1, fy1, fx2, fy2 = map(int, face["bbox"])
                            # 1. Size filter
                            if (fx2 - fx1) < 45 or (fy2 - fy1) < 45:
                                continue
                            # 2. Confidence filter
                            if face.get("det_score", 0.0) < 0.70:
                                continue
                            # 3. Keypoints containment filter
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
                            # 4. Occlusion filter
                            if is_face_occluded(crop, kps):
                                continue
                            valid_faces.append(face)

                        if valid_faces:
                            # Take the largest face detected in the crop
                            matched_face = max(valid_faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))

                # Match if face analysis is needed, face is found, and person is not employee-matched
                if is_face_analysis_needed and (not track_info["matched"] or track_info["type"] == "visitor") and matched_face is not None:
                    face_embedding = np.array(matched_face["embedding"], dtype=np.float32)
                    mapped_threshold = map_similarity_threshold(similarity_threshold)

                    # 1. Match against registered employees
                    match_emp = None
                    if track_employees:
                        match_emp = find_best_match_in_cache(face_embedding, employee_cache, mapped_threshold)
                    
                    if match_emp:
                        employee, sim = match_emp
                        
                        # UPGRADE: If they were previously matched as a visitor, clean it up!
                        if track_info["type"] == "visitor" and track_info["id"] is not None:
                            old_visitor_id = track_info["id"]
                            unique_seen_identities.discard(f"visitor:{old_visitor_id}")
                            
                            if track_info.get("is_new_visitor"):
                                first_time_visitors_count = max(0, first_time_visitors_count - 1)
                                track_info["is_new_visitor"] = False
                            
                            try:
                                await db.execute(delete(PersonEmbedding).where(PersonEmbedding.identity_id == old_visitor_id))
                                await db.execute(delete(PersonIdentity).where(PersonIdentity.id == old_visitor_id))
                                await db.commit()
                            except Exception as db_err:
                                print(f"Error cleaning up upgraded visitor: {db_err}")
                        
                        track_info.update({
                            "type": "employee",
                            "id": employee.id,
                            "label": f"{employee.first_name} (EMP)",
                            "color": (0, 255, 0),
                             "matched": True
                        })
                        unique_seen_identities.add(f"employee:{employee.id}")
                    else:
                        # 2. Match against generic visitors
                        if track_info["type"] == "visitor" and track_info["id"] is not None:
                            pass
                        else:
                            match_vis = None
                            if track_repeat_visitors:
                                match_vis = await repo.find_similar_visitor(session.tenant_id, face_embedding.tolist(), mapped_threshold, class_id=1)
                            
                            if match_vis:
                                visitor, sim = match_vis
                                if visitor.first_name or visitor.last_name:
                                    label_name = f"{visitor.first_name or ''} {visitor.last_name or ''}".strip()
                                else:
                                    label_name = f"Visitor #{str(visitor.id)[:4]}"
                                track_info.update({
                                    "type": "visitor",
                                    "id": visitor.id,
                                    "label": label_name,
                                    "color": (0, 180, 255)
                                })
                                unique_seen_identities.add(f"visitor:{visitor.id}")
                                await repo.create_person_embedding(identity_id=visitor.id, embedding=face_embedding.tolist(), bbox=matched_face["bbox"], timestamp=timestamp_sec)
                            elif register_new_visitors:
                                # 3. Create new Face Visitor
                                visitor = await repo.create_person_identity(session.tenant_id, class_id=1)
                                await repo.create_person_embedding(identity_id=visitor.id, embedding=face_embedding.tolist(), bbox=matched_face["bbox"], timestamp=timestamp_sec)
                                track_info.update({
                                    "type": "visitor",
                                    "id": visitor.id,
                                    "label": "New Visitor",
                                    "color": (0, 0, 255),
                                    "is_new_visitor": True
                                })
                                unique_seen_identities.add(f"visitor:{visitor.id}")
                                first_time_visitors_count += 1

                # Update line crossing
                if line_counter:
                    crossing = line_counter.update(tracker_id, (center_x, center_y))
                    if crossing:
                        track_crossings.append({
                            "tracker_id": tracker_id,
                            "direction": crossing,
                            "timestamp": timestamp_sec
                        })

                # Draw overlay annotation
                track_info = active_tracks[tracker_id]
                label_text = track_info["label"]
                if not is_face_analysis_needed:
                    label_text = f"Person #{tracker_id}"
                    track_info["color"] = (255, 255, 0)
                cv2.rectangle(frame, (x1, y1), (x2, y2), track_info["color"], 2)
                cv2.putText(frame, label_text, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, track_info["color"], 2)

        # Draw HUD on video frame
        hud_w, hud_h = 320, 220
        if orig_width > hud_w + 20 and orig_height > hud_h + 20:
            sub_img = frame[10:10+hud_h, 10:10+hud_w]
            rect = np.zeros(sub_img.shape, dtype=np.uint8) + 20  # dark background
            blended = cv2.addWeighted(sub_img, 0.4, rect, 0.6, 0)
            frame[10:10+hud_h, 10:10+hud_w] = blended

            cv2.putText(frame, "PEOPLE ANALYTICS HUD", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            if track_occupancy:
                cv2.putText(frame, f"Live Occupancy: {current_occupancy}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(frame, f"Peak Occupancy: {peak_occupancy_so_far}", (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            else:
                cv2.putText(frame, "Live Occupancy: N/A", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(frame, "Peak Occupancy: N/A", (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            if is_face_analysis_needed:
                cv2.putText(frame, f"Unique People: {len(unique_seen_identities)}", (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(frame, f"New Visitors: {first_time_visitors_count}", (20, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            else:
                cv2.putText(frame, "Unique People: N/A", (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                cv2.putText(frame, "New Visitors: N/A", (20, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

            cv2.putText(frame, f"Total Tracks: {len(active_tracks)}", (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            if line_counter:
                cv2.putText(frame, f"Entry Count (In): {sum(1 for c in track_crossings if c['direction'] == 'in')}", (20, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.putText(frame, f"Exit Count (Out): {sum(1 for c in track_crossings if c['direction'] == 'out')}", (20, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)
            else:
                cv2.putText(frame, "Entry Count: N/A", (20, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)
                cv2.putText(frame, "Exit Count: N/A", (20, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (128, 128, 128), 1)

        # Draw the line coordinates
        if line_counter and line_start and line_end and len(line_start) == 2 and len(line_end) == 2 and line_start != line_end:
            cv2.line(frame, tuple(line_start), tuple(line_end), (255, 0, 255), 2)

        output_writer.write(frame)

    cap.release()
    output_writer.release()

    # Transcode output video to browser-compatible H.264 format using shared video utility
    try:
        videoFormatChanger(output_path, formats="h264", overwrite_input=True)
    except Exception as e:
        print(f"Video transcoding failed (falling back to raw mp4v): {e}")

    # Filter out very short, spurious tracks (e.g. tracks that lasted less than 10 frames)
    # BUT keep those that crossed the line so we can resolve their identity for crossing logs
    MIN_TRACK_FRAMES = 10
    crossing_tracker_ids = {c["tracker_id"] for c in track_crossings}
    discarded_tracker_ids = set()
    for tracker_id, track_info in list(active_tracks.items()):
        if track_info["frames_since_start"] < MIN_TRACK_FRAMES:
            if tracker_id not in crossing_tracker_ids:
                discarded_tracker_ids.add(tracker_id)
                del active_tracks[tracker_id]
            else:
                track_info["short_crossing"] = True

    # Filter crossings: only keep crossings for non-discarded tracks, and map to resolved visitor IDs
    valid_crossings = []
    if line_counter:
        valid_crossings = [c for c in track_crossings if c["tracker_id"] not in discarded_tracker_ids]
        entry_count = sum(1 for c in valid_crossings if c["direction"] == "in")
        exit_count = sum(1 for c in valid_crossings if c["direction"] == "out")

    for c in valid_crossings:
        track_info = active_tracks.get(c["tracker_id"])
        # Only log crossings in DB if they are associated with a resolved face identity
        if track_info and track_info["type"] == "visitor" and track_info["id"] is not None:
            completed_crossings.append({
                "session_id": session.id,
                "identity_id": track_info["id"],
                "tracker_id": c["tracker_id"],
                "timestamp": c["timestamp"],
                "direction": c["direction"]
            })

    # Move active tracks to completed occurrences list
    for tracker_id, track in active_tracks.items():
        if track["id"] is None:
            continue
        if track.get("short_crossing", False):
            continue

        entry_time = session.created_at + timedelta(seconds=track["first_seen"])
        exit_time = session.created_at + timedelta(seconds=track["last_seen"])

        if track["type"] == "employee":
            completed_attendance.append({
                "session_id": session.id,
                "employee_id": track["id"],
                "first_seen": track["first_seen"],
                "last_seen": track["last_seen"],
                "occurrence_count": track["occurrences"],
                "entry_time": entry_time,
                "exit_time": exit_time
            })
        else:
            crop_path = None
            best_crop = track.get("best_crop")
            if best_crop is not None and best_crop.size > 0:
                crop_filename = f"{uuid.uuid4()}.jpg"
                user_crops_dir = os.path.join(VISITOR_CROPS_DIR, user_id_str) if user_id_str else VISITOR_CROPS_DIR
                os.makedirs(user_crops_dir, exist_ok=True)
                crop_path = os.path.join(user_crops_dir, crop_filename)
                cv2.imwrite(crop_path, best_crop)

            completed_occurrences.append({
                "session_id": session.id,
                "identity_id": track["id"],
                "tracker_id": tracker_id,
                "first_seen": track["first_seen"],
                "last_seen": track["last_seen"],
                "crop_path": crop_path
            })

            completed_visitor_attendance.append({
                "session_id": session.id,
                "identity_id": track["id"],
                "first_seen_sec": track["first_seen"],
                "last_seen_sec": track["last_seen"],
                "occurrence_increment": track["occurrences"],
                "entry_time": entry_time,
                "exit_time": exit_time
            })

    # Bulk insert occurrences, attendance, and crossings to database
    for occ in completed_occurrences:
        await repo.create_person_occurrence(**occ)
    for att in completed_attendance:
        await repo.create_employee_attendance(**att)
    for vis_att in completed_visitor_attendance:
        await repo.log_visitor_attendance(**vis_att)
    for crs in completed_crossings:
        await repo.create_line_crossing(**crs)

    # Process overall statistics
    occupancies = [o["occupancy"] for o in occupancy_history]
    peak_occupancy = max(occupancies) if occupancies else 0
    average_occupancy = np.mean(occupancies) if occupancies else 0.0
    
    # If face recognition is disabled, use active tracks count as total people count proxy
    total_person_count = len(completed_occurrences) + len(completed_attendance) if is_face_analysis_needed else len(active_tracks)

    # Downsample occupancy_timeline to 1-second intervals
    downsampled_timeline = []
    if occupancy_history:
        from collections import defaultdict
        by_second = defaultdict(list)
        for o in occupancy_history:
            sec_int = int(o["time_sec"])
            by_second[sec_int].append(o["occupancy"])
            
        for sec in sorted(by_second.keys()):
            avg_occ = int(round(np.mean(by_second[sec])))
            downsampled_timeline.append({"time_sec": sec, "occupancy": avg_occ})

    await repo.update_session_results(
        session_id=session.id,
        unique_person_count=len(unique_seen_identities) if is_face_analysis_needed else None,
        total_person_count=total_person_count if (track_occupancy or is_face_analysis_needed) else None,
        first_time_visitor_count=first_time_visitors_count if is_face_analysis_needed else None,
        peak_occupancy=peak_occupancy if track_occupancy else None,
        average_occupancy=round(float(average_occupancy), 2) if track_occupancy else None,
        entry_count=entry_count,
        exit_count=exit_count,
        occupancy_timeline=downsampled_timeline if track_occupancy else None,
        output_video_path=output_path
    )
    await db.commit()
