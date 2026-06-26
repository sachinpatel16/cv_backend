import os
import uuid
import cv2
# Prevent OpenCV multi-threading conflicts with Celery fork
cv2.setNumThreads(0)

import torch
# Prevent PyTorch thread conflicts and CPU spinning in Celery child processes
torch.set_num_threads(1)

import numpy as np
from sqlalchemy import select
from collections import defaultdict
from ultralytics import YOLO
import supervision as sv

from workers.celery import celery_app
from database.session import SessionLocal
from workers.utils import run_async
from modules.peopleanalytics.model import PeopleAnalyticsSession, PersonIdentity
from modules.employees.model import Employee
from modules.peopleanalytics.repository import PeopleAnalyticsRepository
from services.ai.people_analytics import ReIDFeatureExtractor, LineCrossingCounter

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
    user_id_str: str | None = None
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

                # Instantiate visual tools
                extractor = ReIDFeatureExtractor()
                model = YOLO("models/yolo12m.pt")

                if is_image:
                    await _process_image_job(
                        db, repo, session, filepath, model, extractor, similarity_threshold, confidence_threshold, user_id_str
                    )
                else:
                    await _process_video_job(
                        db, repo, session, filepath, model, extractor, line_start, line_end, similarity_threshold, confidence_threshold, user_id_str
                    )

            except Exception as e:
                import traceback
                traceback.print_exc()
                session.status = "failed"
                await db.commit()

    run_async(run())


async def _process_image_job(
    db, repo, session, filepath, model, extractor, similarity_threshold, confidence_threshold, user_id_str=None
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

    # Dictionary to keep unique tracked identities in this image
    seen_identities = set()

    for idx, box in enumerate(boxes):
        x1, y1, x2, y2 = map(int, box.xyxy[0])
        # Validate coordinates
        x1, y1 = max(0, x1), max(0, y1)
        x2, y2 = min(w_orig, x2), min(h_orig, y2)

        crop = img[y1:y2, x1:x2]
        embedding = extractor.get_embedding(crop)
        if embedding is None:
            continue

        # Search visitors (specifically class_id=0 for body ReID)
        match_vis = await repo.find_similar_visitor(session.tenant_id, embedding.tolist(), similarity_threshold, class_id=0)
        if match_vis:
            visitor, sim = match_vis
            crop_path = None
            if crop is not None and crop.size > 0:
                crop_filename = f"{uuid.uuid4()}.jpg"
                user_crops_dir = os.path.join(VISITOR_CROPS_DIR, user_id_str) if user_id_str else VISITOR_CROPS_DIR
                os.makedirs(user_crops_dir, exist_ok=True)
                crop_path = os.path.join(user_crops_dir, crop_filename)
                cv2.imwrite(crop_path, crop)

            await repo.create_person_occurrence(
                session_id=session.id,
                identity_id=visitor.id,
                tracker_id=idx,
                first_seen=0.0,
                last_seen=0.0,
                crop_path=crop_path
            )
            # Keep database updated with new profile details
            await repo.create_person_embedding(identity_id=visitor.id, embedding=embedding.tolist(), bbox=[x1, y1, x2, y2], timestamp=0.0)
            seen_identities.add(f"visitor:{visitor.id}")
            label = f"Visitor #{str(visitor.id)[:4]}"
            color = (0, 180, 255) # Orange for returning visitors
        else:
            # Create a new unique identity
            visitor = await repo.create_person_identity(session.tenant_id)
            await repo.create_person_embedding(identity_id=visitor.id, embedding=embedding.tolist(), bbox=[x1, y1, x2, y2], timestamp=0.0)
            crop_path = None
            if crop is not None and crop.size > 0:
                crop_filename = f"{uuid.uuid4()}.jpg"
                user_crops_dir = os.path.join(VISITOR_CROPS_DIR, user_id_str) if user_id_str else VISITOR_CROPS_DIR
                os.makedirs(user_crops_dir, exist_ok=True)
                crop_path = os.path.join(user_crops_dir, crop_filename)
                cv2.imwrite(crop_path, crop)

            await repo.create_person_occurrence(
                session_id=session.id,
                identity_id=visitor.id,
                tracker_id=idx,
                first_seen=0.0,
                last_seen=0.0,
                crop_path=crop_path
            )
            first_time_visitor_count += 1
            seen_identities.add(f"visitor:{visitor.id}")
            label = "New Visitor"
            color = (0, 0, 255) # Red for new visitors

        # Draw overlays
        cv2.rectangle(img, (x1, y1), (x2, y2), color, 2)
        cv2.putText(img, label, (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)

    unique_person_count = len(seen_identities)

    # Draw HUD on static image
    hud_w, hud_h = 320, 140
    if w_orig > hud_w + 20 and h_orig > hud_h + 20:
        sub_img = img[10:10+hud_h, 10:10+hud_w]
        rect = np.zeros(sub_img.shape, dtype=np.uint8) + 20  # dark background
        blended = cv2.addWeighted(sub_img, 0.4, rect, 0.6, 0)
        img[10:10+hud_h, 10:10+hud_w] = blended

        cv2.putText(img, "PEOPLE ANALYTICS SUMMARY", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
        cv2.putText(img, f"Total Detected: {total_person_count}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(img, f"Unique People: {unique_person_count}", (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
        cv2.putText(img, f"New Visitors: {first_time_visitor_count}", (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

    # Save output annotated image
    output_filename = f"{uuid.uuid4()}_annotated.jpg"
    user_outputs_dir = os.path.join(ANALYTICS_OUTPUTS_DIR, user_id_str) if user_id_str else ANALYTICS_OUTPUTS_DIR
    os.makedirs(user_outputs_dir, exist_ok=True)
    output_path = os.path.join(user_outputs_dir, output_filename)
    cv2.imwrite(output_path, img)

    # Generate flat occupancy timeline for static image (just 1 frame)
    occupancy_timeline = [{"time_sec": 0, "occupancy": total_person_count}]

    # Update DB Session results
    await repo.update_session_results(
        session_id=session.id,
        unique_person_count=unique_person_count,
        total_person_count=total_person_count,
        first_time_visitor_count=first_time_visitor_count,
        peak_occupancy=total_person_count,
        average_occupancy=float(total_person_count),
        entry_count=None,
        exit_count=None,
        occupancy_timeline=occupancy_timeline,
        output_video_path=output_path
    )
    await db.commit()


async def _process_video_job(
    db, repo, session, filepath, model, extractor, line_start, line_end, similarity_threshold, confidence_threshold, user_id_str=None
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
    tracker = sv.ByteTrack()
    line_counter = None
    if line_start and line_end and len(line_start) == 2 and len(line_end) == 2 and line_start != line_end:
        line_counter = LineCrossingCounter(line_start, line_end)

    # Tracking states
    # tracker_id -> {"type": "employee"|"visitor", "id": UUID, "first_seen": float, "last_seen": float, "occurrences": int, "label": str, "color": tuple}
    active_tracks = {}
    
    # Store complete session records for bulk inserts at the end
    completed_occurrences = []  # List of dicts
    completed_attendance = []   # List of dicts
    completed_crossings = []    # List of dicts
    track_crossings = []        # Temp list of all raw crossing events

    occupancy_history = []
    unique_seen_identities = set()
    first_time_visitors_count = 0
    entry_count = None
    exit_count = None
    peak_occupancy_so_far = 0

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
                    active_tracks[tracker_id] = {
                        "type": "visitor",
                        "id": None,
                        "first_seen": timestamp_sec,
                        "last_seen": timestamp_sec,
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
                    track_info["frames_since_start"] += 1

                    crop = frame[y1:y2, x1:x2]
                    if crop is not None and crop.size > 0:
                        area = (x2 - x1) * (y2 - y1)
                        if area > track_info["best_crop_area"]:
                            track_info["best_crop_area"] = area
                            track_info["best_crop"] = crop

                track_info = active_tracks[tracker_id]
                # Match once the track reaches 10 frames of history
                if not track_info["matched"] and track_info["frames_since_start"] >= 10:
                    best_crop = track_info["best_crop"]
                    if best_crop is not None:
                        embedding = extractor.get_embedding(best_crop)
                        if embedding is not None:
                            # Match against generic visitors (specifically class_id=0 for body ReID)
                            match_vis = await repo.find_similar_visitor(session.tenant_id, embedding.tolist(), similarity_threshold, class_id=0)
                            if match_vis:
                                visitor, sim = match_vis
                                track_info.update({
                                    "type": "visitor",
                                    "id": visitor.id,
                                    "label": f"Visitor #{str(visitor.id)[:4]}",
                                    "color": (0, 180, 255),
                                    "matched": True
                                })
                                unique_seen_identities.add(f"visitor:{visitor.id}")
                                # Keep database updated with new profile details
                                await repo.create_person_embedding(identity_id=visitor.id, embedding=embedding.tolist(), bbox=[x1, y1, x2, y2], timestamp=timestamp_sec)
                            else:
                                # Create new anonymous identity
                                visitor = await repo.create_person_identity(session.tenant_id)
                                await repo.create_person_embedding(identity_id=visitor.id, embedding=embedding.tolist(), bbox=[x1, y1, x2, y2], timestamp=timestamp_sec)
                                track_info.update({
                                    "type": "visitor",
                                    "id": visitor.id,
                                    "label": "New Visitor",
                                    "color": (0, 0, 255),
                                    "matched": True
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
                cv2.rectangle(frame, (x1, y1), (x2, y2), track_info["color"], 2)
                cv2.putText(frame, track_info["label"], (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, track_info["color"], 2)

        # Draw HUD on video frame
        hud_w, hud_h = 320, 220
        if orig_width > hud_w + 20 and orig_height > hud_h + 20:
            sub_img = frame[10:10+hud_h, 10:10+hud_w]
            rect = np.zeros(sub_img.shape, dtype=np.uint8) + 20  # dark background
            blended = cv2.addWeighted(sub_img, 0.4, rect, 0.6, 0)
            frame[10:10+hud_h, 10:10+hud_w] = blended

            cv2.putText(frame, "PEOPLE ANALYTICS HUD", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
            cv2.putText(frame, f"Live Occupancy: {current_occupancy}", (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f"Unique People: {len(unique_seen_identities)}", (20, 85), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f"Total Tracks: {len(active_tracks)}", (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f"New Visitors: {first_time_visitors_count}", (20, 135), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            cv2.putText(frame, f"Peak Occupancy: {peak_occupancy_so_far}", (20, 160), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
            if line_start and line_end and len(line_start) == 2 and len(line_end) == 2 and line_start != line_end:
                cv2.putText(frame, f"Entry Count (In): {sum(1 for c in track_crossings if c['direction'] == 'in')}", (20, 185), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)
                cv2.putText(frame, f"Exit Count (Out): {sum(1 for c in track_crossings if c['direction'] == 'out')}", (20, 210), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 1)

        # Draw the line coordinates
        if line_start and line_end and len(line_start) == 2 and len(line_end) == 2 and line_start != line_end:
            cv2.line(frame, tuple(line_start), tuple(line_end), (255, 0, 255), 2)

        output_writer.write(frame)

    cap.release()
    output_writer.release()

    # Transcode output video to browser-compatible H.264 format using FFmpeg
    import subprocess
    h264_output_path = output_path.replace(".mp4", "_h264.mp4")
    try:
        cmd = [
            "ffmpeg",
            "-i", output_path,
            "-vcodec", "libx264",
            "-pix_fmt", "yuv420p",
            "-acodec", "aac",
            "-y",
            h264_output_path
        ]
        subprocess.run(cmd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if os.path.exists(h264_output_path):
            os.replace(h264_output_path, output_path)
    except Exception as e:
        print(f"FFmpeg transcoding failed (falling back to raw mp4v): {e}")

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

    # Resolve unmatched tracks (e.g. tracks that lasted at least 10 frames but failed to match during the loop)
    for tracker_id, track_info in active_tracks.items():
        if not track_info.get("matched", False):
            best_crop = track_info.get("best_crop")
            if best_crop is not None:
                embedding = extractor.get_embedding(best_crop)
                if embedding is not None:
                    # Match against generic visitors
                    match_vis = await repo.find_similar_visitor(session.tenant_id, embedding.tolist(), similarity_threshold)
                    if match_vis:
                        visitor, sim = match_vis
                        track_info.update({
                                "type": "visitor",
                                "id": visitor.id,
                                "label": f"Visitor #{str(visitor.id)[:4]}",
                                "color": (0, 180, 255),
                                "matched": True
                        })
                        if not track_info.get("short_crossing", False):
                            unique_seen_identities.add(f"visitor:{visitor.id}")
                    else:
                        # Create new anonymous identity
                        visitor = await repo.create_person_identity(session.tenant_id)
                        await repo.create_person_embedding(identity_id=visitor.id, embedding=embedding.tolist(), bbox=[0, 0, 0, 0], timestamp=track_info["first_seen"])
                        track_info.update({
                            "type": "visitor",
                            "id": visitor.id,
                            "label": "New Visitor",
                            "color": (0, 0, 255),
                            "matched": True
                        })
                        if not track_info.get("short_crossing", False):
                            unique_seen_identities.add(f"visitor:{visitor.id}")
                            first_time_visitors_count += 1

    # Filter crossings: only keep crossings for non-discarded tracks, and map to resolved visitor IDs
    valid_crossings = []
    if line_counter:
        valid_crossings = [c for c in track_crossings if c["tracker_id"] not in discarded_tracker_ids]
        entry_count = sum(1 for c in valid_crossings if c["direction"] == "in")
        exit_count = sum(1 for c in valid_crossings if c["direction"] == "out")

    for c in valid_crossings:
        track_info = active_tracks[c["tracker_id"]]
        if track_info["type"] == "visitor" and track_info["id"] is not None:
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
        if track["type"] == "employee":
            completed_attendance.append({
                "session_id": session.id,
                "employee_id": track["id"],
                "first_seen": track["first_seen"],
                "last_seen": track["last_seen"],
                "occurrence_count": track["occurrences"]
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

    # Bulk insert occurrences, attendance, and crossings to database
    for occ in completed_occurrences:
        await repo.create_person_occurrence(**occ)
    for att in completed_attendance:
        await repo.create_employee_attendance(**att)
    for crs in completed_crossings:
        await repo.create_line_crossing(**crs)

    # Process overall statistics
    occupancies = [o["occupancy"] for o in occupancy_history]
    peak_occupancy = max(occupancies) if occupancies else 0
    average_occupancy = np.mean(occupancies) if occupancies else 0.0
    total_person_count = len(completed_occurrences) + len(completed_attendance)

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
        unique_person_count=len(unique_seen_identities),
        total_person_count=total_person_count,
        first_time_visitor_count=first_time_visitors_count,
        peak_occupancy=peak_occupancy,
        average_occupancy=round(float(average_occupancy), 2),
        entry_count=entry_count,
        exit_count=exit_count,
        occupancy_timeline=downsampled_timeline,
        output_video_path=output_path
    )
    await db.commit()
