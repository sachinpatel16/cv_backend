import os
import uuid
import cv2
cv2.setNumThreads(0)

import numpy as np
from sqlalchemy import select
from collections import defaultdict
from datetime import datetime, timezone, timedelta

from workers.celery import celery_app
from database.session import SessionLocal
from workers.utils import run_async
from modules.peopleanalytics.model import PeopleAnalyticsSession, PersonIdentity
from modules.employees.model import Employee
from modules.faceanalytics.repository import FaceAnalyticsRepository

FACE_OUTPUTS_DIR = os.path.join("storage", "face_analytics_outputs")
os.makedirs(FACE_OUTPUTS_DIR, exist_ok=True)

VISITOR_CROPS_DIR = os.path.join("storage", "visitor_crops")
os.makedirs(VISITOR_CROPS_DIR, exist_ok=True)


class FaceTracker:
    def __init__(self, max_lost_frames=30, iou_threshold=0.3):
        self.max_lost_frames = max_lost_frames
        self.iou_threshold = iou_threshold
        self.next_id = 1
        self.tracks = {}  # face_id -> track_dict

    def update(self, detected_faces, frame_idx, timestamp_sec):
        """
        detected_faces: list of dicts: {"bbox": [x1, y1, x2, y2], "embedding": np.ndarray, "crop": np.ndarray}
        """
        updated_tracks = {}
        matched_detections = set()

        # 1. Associate detected faces with active tracks based on IoU
        for face_id, track in list(self.tracks.items()):
            best_iou = 0
            best_det_idx = -1
            for det_idx, det in enumerate(detected_faces):
                if det_idx in matched_detections:
                    continue
                iou = self._calculate_iou(track["bbox"], det["bbox"])
                if iou > best_iou:
                    best_iou = iou
                    best_det_idx = det_idx

            if best_iou >= self.iou_threshold:
                det = detected_faces[best_det_idx]
                matched_detections.add(best_det_idx)
                
                track["bbox"] = det["bbox"]
                track["last_seen_frame"] = frame_idx
                track["last_seen_time"] = timestamp_sec
                track["occurrences"] += 1
                track["active_in_current_frame"] = True
                
                area = (det["bbox"][2] - det["bbox"][0]) * (det["bbox"][3] - det["bbox"][1])
                if area > track["best_crop_area"] and det.get("embedding") is not None:
                    track["best_crop_area"] = area
                    track["embedding"] = det["embedding"]
                    track["best_crop"] = det.get("crop")
                
                updated_tracks[face_id] = track
            else:
                # Keep lost tracks if they haven't expired
                if frame_idx - track["last_seen_frame"] <= self.max_lost_frames:
                    track["active_in_current_frame"] = False
                    updated_tracks[face_id] = track

        # 2. Start new tracks for unmatched detections
        for det_idx, det in enumerate(detected_faces):
            if det_idx in matched_detections:
                continue
            
            area = (det["bbox"][2] - det["bbox"][0]) * (det["bbox"][3] - det["bbox"][1])
            new_track = {
                "face_id": self.next_id,
                "bbox": det["bbox"],
                "first_seen_time": timestamp_sec,
                "last_seen_time": timestamp_sec,
                "first_seen_frame": frame_idx,
                "last_seen_frame": frame_idx,
                "occurrences": 1,
                "best_crop_area": area,
                "embedding": det.get("embedding"),
                "best_crop": det.get("crop"),
                "matched": False,
                "matched_type": None,  # "employee" or "visitor"
                "matched_id": None,    # employee_id or visitor_id
                "label": f"Face #{self.next_id}",
                "color": (200, 200, 200),
                "active_in_current_frame": True
            }
            updated_tracks[self.next_id] = new_track
            self.next_id += 1

        self.tracks = updated_tracks
        return self.tracks

    def _calculate_iou(self, bbox1, bbox2):
        x1 = max(bbox1[0], bbox2[0])
        y1 = max(bbox1[1], bbox2[1])
        x2 = min(bbox1[2], bbox2[2])
        y2 = min(bbox1[3], bbox2[3])

        intersection = max(0, x2 - x1) * max(0, y2 - y1)
        area1 = (bbox1[2] - bbox1[0]) * (bbox1[3] - bbox1[1])
        area2 = (bbox2[2] - bbox2[0]) * (bbox2[3] - bbox2[1])
        union = area1 + area2 - intersection
        return intersection / union if union > 0 else 0


@celery_app.task(name="modules.faceanalytics.tasks.process_face_analytics_task")
def process_face_analytics_task(
    session_id_str: str,
    filepath: str,
    line_start: list[int] | None = None,
    line_end: list[int] | None = None,
    similarity_threshold: float = 0.70,
    confidence_threshold: float = 0.3,
    user_id_str: str | None = None
):
    """
    Celery background task for Face-Only Analytics Suite using buffalo_l only.
    """
    session_id = uuid.UUID(session_id_str)

    async def run():
        async with SessionLocal() as db:
            repo = FaceAnalyticsRepository(db)
            
            # Fetch the session
            stmt = select(PeopleAnalyticsSession).where(
                PeopleAnalyticsSession.id == session_id,
                PeopleAnalyticsSession.is_delete == False
            )
            res = await db.execute(stmt)
            session = res.scalars().first()
            if not session:
                return

            session.status = "processing"
            await db.commit()

            try:
                cap = cv2.VideoCapture(filepath)
                if not cap.isOpened():
                    raise ValueError("Could not open video file.")

                orig_width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
                orig_height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
                fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
                total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

                # Initialize video writer
                output_filename = f"{uuid.uuid4()}_annotated.mp4"
                user_outputs_dir = os.path.join(FACE_OUTPUTS_DIR, user_id_str) if user_id_str else FACE_OUTPUTS_DIR
                os.makedirs(user_outputs_dir, exist_ok=True)
                output_path = os.path.join(user_outputs_dir, output_filename)
                fourcc = cv2.VideoWriter_fourcc(*'mp4v')
                output_writer = cv2.VideoWriter(output_path, fourcc, fps, (orig_width, orig_height))

                # Initialize custom tracker
                tracker = FaceTracker(max_lost_frames=int(fps * 3))  # 3 seconds lost threshold
                
                # Tracking states
                active_tracks = {}
                occupancy_history = []
                local_reid_cache = []
                peak_occupancy_so_far = 0

                frame_step = max(1, int(fps / 5))  # Process 5 frames per second to save CPU and stay highly accurate

                from services.ai.face_recognition import face_rec_service

                frame_idx = 0
                while cap.isOpened():
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break

                    timestamp_sec = frame_idx / fps
                    
                    # Detect and track faces on every `frame_step` frames
                    if frame_idx % frame_step == 0:
                        # Convert image to JPEG bytes for FaceRecognitionService
                        _, encoded_img = cv2.imencode(".jpg", frame)
                        img_bytes = encoded_img.tobytes()

                        try:
                            faces = face_rec_service.extract_faces(img_bytes)
                        except Exception:
                            faces = []

                        detected_faces = []
                        for face in faces:
                            fx1, fy1, fx2, fy2 = map(int, face["bbox"])
                            fx1, fy1 = max(0, fx1), max(0, fy1)
                            fx2, fy2 = min(orig_width, fx2), min(orig_height, fy2)
                            crop = frame[fy1:fy2, fx1:fx2]
                            detected_faces.append({
                                "bbox": [fx1, fy1, fx2, fy2],
                                "embedding": np.array(face["embedding"], dtype=np.float32),
                                "crop": crop
                            })

                        # Update tracker
                        active_tracks = tracker.update(detected_faces, frame_idx, timestamp_sec)

                    # Compute current live occupancy (only count tracks active in current frame)
                    current_occupancy = sum(1 for t in active_tracks.values() if t["active_in_current_frame"])
                    occupancy_history.append({"time_sec": round(timestamp_sec, 2), "occupancy": current_occupancy})
                    if current_occupancy > peak_occupancy_so_far:
                        peak_occupancy_so_far = current_occupancy

                    # Draw active tracks on current frame
                    for face_id, track in active_tracks.items():
                        # Only draw if track was recently seen
                        if not track["active_in_current_frame"]:
                            continue

                        # Resolve identity if embedding exists and not already matched
                        if not track["matched"] and track["embedding"] is not None:
                            from services.ai.math_utils import map_similarity_threshold, find_best_match_in_cache
                            mapped_threshold = map_similarity_threshold(similarity_threshold)
                            match_local = find_best_match_in_cache(track["embedding"], local_reid_cache, mapped_threshold)
                            if match_local:
                                local_id, sim = match_local
                                track["matched"] = True
                                track["matched_type"] = "visitor"
                                track["matched_id"] = local_id
                                track["label"] = f"Person #{str(local_id)[:4]}"
                            else:
                                new_local_id = uuid.uuid4()
                                local_reid_cache.append((new_local_id, track["embedding"]))
                                track["matched"] = True
                                track["matched_type"] = "visitor"
                                track["matched_id"] = new_local_id
                                track["label"] = f"Person #{str(new_local_id)[:4]}"

                            # Update track color deterministically based on UUID BGR
                            b = track["matched_id"].bytes
                            r = b[0] % 200 + 55
                            g = b[1] % 200 + 55
                            bg = b[2] % 200 + 55
                            track["color"] = (bg, g, r)

                        # Draw box and label
                        tx1, ty1, tx2, ty2 = track["bbox"]
                        cv2.rectangle(frame, (tx1, ty1), (tx2, ty2), track["color"], 2)
                        cv2.putText(frame, track["label"], (tx1, ty1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, track["color"], 2)

                    # Calculate current unique count dynamically for HUD
                    # A unique person is any track that has accumulated at least 2 processed frames
                    MIN_TRACK_OCCURRENCES = 2
                    valid_track_matched_ids = {t["matched_id"] for t in tracker.tracks.values() if t["occurrences"] >= MIN_TRACK_OCCURRENCES and t["matched_id"] is not None}
                    current_unique_count = len(valid_track_matched_ids)
                    current_total_tracks = sum(1 for t in tracker.tracks.values() if t["occurrences"] >= MIN_TRACK_OCCURRENCES)

                    # Draw HUD
                    hud_w = 320
                    hud_h = 140
                    if orig_width > hud_w + 20 and orig_height > hud_h + 20:
                        sub_img = frame[10:10+hud_h, 10:10+hud_w]
                        rect = np.zeros(sub_img.shape, dtype=np.uint8) + 20
                        blended = cv2.addWeighted(sub_img, 0.4, rect, 0.6, 0)
                        frame[10:10+hud_h, 10:10+hud_w] = blended

                        cv2.putText(frame, "FACE ANALYTICS HUD", (20, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 255), 2)
                        cv2.putText(frame, f"Live Occupancy: {current_occupancy}", (20, 55), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                        cv2.putText(frame, f"Unique People: {current_unique_count}", (20, 75), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                        cv2.putText(frame, f"Total Tracks: {current_total_tracks}", (20, 95), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)
                        cv2.putText(frame, f"Peak Occupancy: {peak_occupancy_so_far}", (20, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (255, 255, 255), 1)

                    output_writer.write(frame)
                    frame_idx += 1

                cap.release()
                output_writer.release()

                # Process final logs and occurrence records
                from datetime import datetime, timezone
                now_ts = datetime.now(timezone.utc)

                # Filter out very short, spurious tracks (e.g. tracks seen in less than 2 processed frames)
                MIN_TRACK_OCCURRENCES = 2
                completed_occurrences = []
                local_db_identities = {}

                for face_id, track in list(tracker.tracks.items()):
                    if track["occurrences"] < MIN_TRACK_OCCURRENCES:
                        del tracker.tracks[face_id]
                        continue

                    # Retrieve or create a database PersonIdentity for this matched_id
                    local_id = track["matched_id"]
                    if local_id is None:
                        local_id = uuid.uuid4()
                        track["matched_id"] = local_id

                    if local_id not in local_db_identities:
                        visitor = await repo.create_person_identity(session.tenant_id)
                        local_db_identities[local_id] = visitor
                    else:
                        visitor = local_db_identities[local_id]

                    # Save crop if available
                    crop_path = None
                    if track["best_crop"] is not None:
                        crop_filename = f"{uuid.uuid4()}.jpg"
                        user_crops_dir = os.path.join(VISITOR_CROPS_DIR, user_id_str) if user_id_str else VISITOR_CROPS_DIR
                        os.makedirs(user_crops_dir, exist_ok=True)
                        crop_path = os.path.join(user_crops_dir, crop_filename)
                        cv2.imwrite(crop_path, track["best_crop"])

                    completed_occurrences.append({
                        "session_id": session.id,
                        "identity_id": visitor.id,
                        "tracker_id": face_id,
                        "first_seen": track["first_seen_time"],
                        "last_seen": track["last_seen_time"],
                        "crop_path": crop_path
                    })

                # Write visitor occurrences to database
                for occ in completed_occurrences:
                    await repo.create_person_occurrence(
                        session_id=session.id,
                        identity_id=occ["identity_id"],
                        tracker_id=occ["tracker_id"],
                        first_seen=occ["first_seen"],
                        last_seen=occ["last_seen"],
                        crop_path=occ["crop_path"]
                    )

                # Calculate stats (without employee matching, count unique people by local resolved identities)
                total_unique_people = len(local_db_identities)
                total_detected = len(completed_occurrences)

                total_occupancy_sum = sum(h["occupancy"] for h in occupancy_history)
                avg_occupancy = round(total_occupancy_sum / len(occupancy_history), 2) if occupancy_history else 0.0

                # Update database session results
                await repo.update_session_results(
                    session_id=session.id,
                    unique_person_count=total_unique_people,
                    total_person_count=total_detected,
                    first_time_visitor_count=None,
                    peak_occupancy=peak_occupancy_so_far,
                    average_occupancy=avg_occupancy,
                    entry_count=None,
                    exit_count=None,
                    occupancy_timeline=occupancy_history,
                    output_video_path=output_path
                )
                session.completed_at = datetime.now(timezone.utc)
                await db.commit()

            except Exception as e:
                import traceback
                traceback.print_exc()
                session.status = "failed"
                await db.commit()

    run_async(run())
