import os
import uuid
import cv2


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
from modules.peoplecount.tracker import KalmanFilter
cv2.setNumThreads(0)
FACE_OUTPUTS_DIR = os.path.join("storage", "face_analytics_outputs")
os.makedirs(FACE_OUTPUTS_DIR, exist_ok=True)

VISITOR_CROPS_DIR = os.path.join("storage", "visitor_crops")
os.makedirs(VISITOR_CROPS_DIR, exist_ok=True)


def is_face_occluded(frame, kps, threshold=15.0):
    """
    Checks if the nose or mouth keypoints are occluded by comparing their chrominance (Cr, Cb)
    to the reference skin tone of the forehead (midpoint between the eyes, shifted slightly up).
    Returns True if an occlusion (non-skin object covering the features) is detected.
    """
    if not kps or len(kps) < 5:
        return False
        
    h, w = frame.shape[:2]
    
    def get_patch_chroma(cx, cy, patch_size=5):
        half = patch_size // 2
        x1 = max(0, int(cx - half))
        x2 = min(w - 1, int(cx + half))
        y1 = max(0, int(cy - half))
        y2 = min(h - 1, int(cy + half))
        
        patch_bgr = frame[y1:y2+1, x1:x2+1]
        if patch_bgr.size == 0:
            return None
            
        patch_ycrcb = cv2.cvtColor(patch_bgr, cv2.COLOR_BGR2YCrCb)
        mean_ycrcb = cv2.mean(patch_ycrcb)
        return mean_ycrcb[1], mean_ycrcb[2] # Cr, Cb

    # Keypoint indices: 0/1: Eyes, 2: Nose, 3/4: Mouth corners
    le_x, le_y = kps[0]
    re_x, re_y = kps[1]
    
    # Forehead reference point: shifted up from eye midpoint by 25% of inter-pupillary distance
    eye_dist = np.sqrt((re_x - le_x)**2 + (re_y - le_y)**2)
    fh_x = (le_x + re_x) / 2.0
    fh_y = (le_y + re_y) / 2.0 - (eye_dist * 0.25)
    
    fh_y = max(0, min(h - 1, fh_y))
    fh_x = max(0, min(w - 1, fh_x))
    
    fh_chroma = get_patch_chroma(fh_x, fh_y)
    if not fh_chroma:
        return False
    fh_cr, fh_cb = fh_chroma
    
    # Fallback to standard skin tone if forehead is not skin-colored (e.g., hat/hair/extreme light)
    if not (133 <= fh_cr <= 173 and 77 <= fh_cb <= 127):
        fh_cr, fh_cb = 153.0, 102.0
        
    # Check nose tip (2) and mouth corners (3, 4)
    for idx in [2, 3, 4]:
        tx, ty = kps[idx]
        t_chroma = get_patch_chroma(tx, ty)
        if not t_chroma:
            continue
        t_cr, t_cb = t_chroma
        
        # If Cr or Cb difference exceeds the threshold, check if it's still within universal skin bounds
        if abs(fh_cr - t_cr) > threshold or abs(fh_cb - t_cb) > threshold:
            # Safety Net: If the patch is still within the broad, universal human skin bounds,
            # we accept it to prevent false rejections due to skin conditions, burns, or redness.
            is_universal_skin = (133 <= t_cr <= 173) and (77 <= t_cb <= 127)
            if not is_universal_skin:
                return True
            
    return False


class FaceTracker:
    def __init__(self, max_lost_frames=30, iou_threshold=0.3, max_spatial_lost_frames=90):
        self.max_lost_frames = max_lost_frames
        self.iou_threshold = iou_threshold
        self.next_id = 1
        self.tracks = {}  # face_id -> track_dict
        self.kf = KalmanFilter()
        self.max_spatial_lost_frames = max_spatial_lost_frames

    def update(self, detected_faces, frame_idx, timestamp_sec):
        """
        detected_faces: list of dicts: {"bbox": [x1, y1, x2, y2], "embedding": np.ndarray, "crop": np.ndarray}
        """
        updated_tracks = {}
        matched_detections = set()

        # Predict Kalman states for all active/existing tracks
        for face_id, track in list(self.tracks.items()):
            track["mean"], track["covariance"] = self.kf.predict(track["mean"], track["covariance"])
            # Convert predicted state tlwh back to [x1, y1, x2, y2]
            p_tlwh = track["mean"][:4]
            track["predicted_bbox"] = [
                p_tlwh[0],
                p_tlwh[1],
                p_tlwh[0] + p_tlwh[2],
                p_tlwh[1] + p_tlwh[3]
            ]

        # 1. Associate detected faces with active tracks based on IoU with predicted bbox
        for face_id, track in list(self.tracks.items()):
            best_iou = 0
            best_det_idx = -1
            
            # Skip spatial matching if the track has been lost for too long, to prevent ID swapping
            if frame_idx - track["last_seen_frame"] <= self.max_spatial_lost_frames:
                for det_idx, det in enumerate(detected_faces):
                    if det_idx in matched_detections:
                        continue
                    iou = self._calculate_iou(track["predicted_bbox"], det["bbox"])
                    if iou > best_iou:
                        best_iou = iou
                        best_det_idx = det_idx

            if best_iou >= self.iou_threshold:
                det = detected_faces[best_det_idx]
                matched_detections.add(best_det_idx)
                
                # Convert new detection bbox to tlwh for Kalman update
                det_tlwh = [
                    det["bbox"][0],
                    det["bbox"][1],
                    det["bbox"][2] - det["bbox"][0],
                    det["bbox"][3] - det["bbox"][1]
                ]
                # Update Kalman filter state
                track["mean"], track["covariance"] = self.kf.update(
                    track["mean"], track["covariance"], det_tlwh
                )
                # Compute updated bbox from state
                u_tlwh = track["mean"][:4]
                track["bbox"] = [
                    u_tlwh[0],
                    u_tlwh[1],
                    u_tlwh[0] + u_tlwh[2],
                    u_tlwh[1] + u_tlwh[3]
                ]
                
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
                    # Update bbox to predicted_bbox so it drifts smoothly while lost
                    track["bbox"] = track["predicted_bbox"]
                    updated_tracks[face_id] = track

        # 2. Start new tracks for unmatched detections
        for det_idx, det in enumerate(detected_faces):
            if det_idx in matched_detections:
                continue
            
            # Initialize Kalman Filter state for the new track
            det_tlwh = [
                det["bbox"][0],
                det["bbox"][1],
                det["bbox"][2] - det["bbox"][0],
                det["bbox"][3] - det["bbox"][1]
            ]
            mean, covariance = self.kf.initiate(det_tlwh)
            
            area = (det["bbox"][2] - det["bbox"][0]) * (det["bbox"][3] - det["bbox"][1])
            new_track = {
                "face_id": self.next_id,
                "bbox": det["bbox"],
                "mean": mean,
                "covariance": covariance,
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
                tracker = FaceTracker(max_lost_frames=999999, max_spatial_lost_frames=int(fps * 3))  # Keep lost tracks in memory, but limit spatial matching to 3s
                
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
                            
                            # 1. Size filter
                            if (fx2 - fx1) < 45 or (fy2 - fy1) < 45:
                                continue

                            # 2. Confidence filter
                            if face.get("det_score", 0.0) < 0.70:
                                continue

                            # 3. Keypoints containment filter (ensures full face is in the box)
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
                    else:
                        # On intermediate frames, smoothly predict and advance bounding boxes of active tracks using Kalman Filter
                        for face_id, track in list(tracker.tracks.items()):
                            if track["active_in_current_frame"]:
                                track["mean"], track["covariance"] = tracker.kf.predict(track["mean"], track["covariance"])
                                p_tlwh = track["mean"][:4]
                                track["bbox"] = [
                                    p_tlwh[0],
                                    p_tlwh[1],
                                    p_tlwh[0] + p_tlwh[2],
                                    p_tlwh[1] + p_tlwh[3]
                                ]
                        active_tracks = tracker.tracks

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

                        # Resolve identity if track has at least 5 occurrences, embedding exists, and not already matched
                        if not track["matched"] and track["occurrences"] >= 5 and track["embedding"] is not None:
                            from services.ai.math_utils import map_similarity_threshold
                            mapped_threshold = map_similarity_threshold(similarity_threshold)
                            match_vis = await repo.find_similar_visitor(
                                session.tenant_id,
                                track["embedding"].tolist(),
                                mapped_threshold,
                                class_id=1
                            )
                            if match_vis:
                                visitor, sim = match_vis
                                track["matched"] = True
                                track["matched_type"] = "visitor"
                                track["matched_id"] = visitor.id
                                track["label"] = f"Visitor #{str(visitor.id)[:4]}"
                                
                                # Update track color deterministically based on UUID BGR
                                b = track["matched_id"].bytes
                                r = b[0] % 200 + 55
                                g = b[1] % 200 + 55
                                bg = b[2] % 200 + 55
                                track["color"] = (bg, g, r)

                                await repo.create_person_embedding(
                                    identity_id=visitor.id,
                                    embedding=track["embedding"].tolist(),
                                    bbox=track["bbox"],
                                    timestamp=timestamp_sec
                                )
                            else:
                                visitor = await repo.create_person_identity(session.tenant_id, class_id=1)
                                track["matched"] = True
                                track["matched_type"] = "visitor"
                                track["matched_id"] = visitor.id
                                track["label"] = "New Visitor"
                                track["color"] = (0, 0, 255) # Red for new visitors

                                await repo.create_person_embedding(
                                    identity_id=visitor.id,
                                    embedding=track["embedding"].tolist(),
                                    bbox=track["bbox"],
                                    timestamp=timestamp_sec
                                )

                        # Draw box and label
                        tx1, ty1, tx2, ty2 = map(int, track["bbox"])
                        cv2.rectangle(frame, (tx1, ty1), (tx2, ty2), track["color"], 2)
                        cv2.putText(frame, track["label"], (tx1, ty1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, track["color"], 2)

                    # Calculate current unique count dynamically for HUD
                    # A unique person is any track that has accumulated at least 2 processed frames
                    MIN_TRACK_OCCURRENCES = 2
                    valid_track_matched_ids = set()
                    for face_id, t in tracker.tracks.items():
                        if t["occurrences"] >= MIN_TRACK_OCCURRENCES:
                            if t["matched_id"] is not None:
                                valid_track_matched_ids.add(t["matched_id"])
                            else:
                                valid_track_matched_ids.add(f"temp_{face_id}")
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

                # 1. Filter out very short, spurious tracks (e.g. tracks seen in less than 2 processed frames)
                MIN_TRACK_OCCURRENCES = 2
                valid_tracks = {}
                for face_id, track in list(tracker.tracks.items()):
                    if track["occurrences"] >= MIN_TRACK_OCCURRENCES:
                        valid_tracks[face_id] = track

                # 2. Resolve database PersonIdentity IDs for all valid tracks
                for face_id, track in valid_tracks.items():
                    visitor_id = track["matched_id"]
                    if visitor_id is None:
                        if track["embedding"] is not None:
                            from services.ai.math_utils import map_similarity_threshold
                            mapped_threshold = map_similarity_threshold(similarity_threshold)
                            match_vis = await repo.find_similar_visitor(
                                session.tenant_id,
                                track["embedding"].tolist(),
                                mapped_threshold,
                                class_id=1
                            )
                            if match_vis:
                                visitor, sim = match_vis
                                visitor_id = visitor.id
                                track["matched_id"] = visitor_id
                                track["label"] = f"Visitor #{str(visitor.id)[:4]}"
                            else:
                                visitor = await repo.create_person_identity(session.tenant_id, class_id=1)
                                visitor_id = visitor.id
                                track["matched_id"] = visitor_id
                                track["label"] = "New Visitor"
                                await repo.create_person_embedding(
                                    identity_id=visitor.id,
                                    embedding=track["embedding"].tolist(),
                                    bbox=track["bbox"],
                                    timestamp=track["first_seen_time"]
                                )
                        else:
                            visitor = await repo.create_person_identity(session.tenant_id, class_id=1)
                            visitor_id = visitor.id
                            track["matched_id"] = visitor_id
                            track["label"] = "New Visitor"

                # 3. Group tracks by resolved visitor_id to save only the single best crop per unique visitor
                from collections import defaultdict
                tracks_by_visitor = defaultdict(list)
                for face_id, track in valid_tracks.items():
                    visitor_id = track["matched_id"]
                    if visitor_id is not None:
                        tracks_by_visitor[visitor_id].append(track)

                visitor_crop_paths = {}
                for visitor_id, v_tracks in tracks_by_visitor.items():
                    # Pick the track with the largest crop area
                    best_track = max(v_tracks, key=lambda t: t.get("best_crop_area", 0))
                    crop_path = None
                    if best_track["best_crop"] is not None:
                        crop_filename = f"{uuid.uuid4()}.jpg"
                        user_crops_dir = os.path.join(VISITOR_CROPS_DIR, user_id_str) if user_id_str else VISITOR_CROPS_DIR
                        os.makedirs(user_crops_dir, exist_ok=True)
                        crop_path = os.path.join(user_crops_dir, crop_filename)
                        cv2.imwrite(crop_path, best_track["best_crop"])
                    visitor_crop_paths[visitor_id] = crop_path

                # 4. Prepare and write completed occurrences
                completed_occurrences = []
                for face_id, track in valid_tracks.items():
                    visitor_id = track["matched_id"]
                    crop_path = visitor_crop_paths.get(visitor_id) if visitor_id else None
                    completed_occurrences.append({
                        "session_id": session.id,
                        "identity_id": visitor_id,
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

                # Calculate stats (without employee matching, count unique people by database visitor IDs)
                unique_visitors = {occ["identity_id"] for occ in completed_occurrences}
                total_unique_people = len(unique_visitors)
                total_detected = len(completed_occurrences)

                # Calculate new visitor counts
                new_visitor_ids = {t["matched_id"] for t in valid_tracks.values() if t.get("label") == "New Visitor" and t["matched_id"] is not None}
                first_time_visitor_count = len(new_visitor_ids)

                total_occupancy_sum = sum(h["occupancy"] for h in occupancy_history)
                avg_occupancy = round(total_occupancy_sum / len(occupancy_history), 2) if occupancy_history else 0.0

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

                # Update database session results
                await repo.update_session_results(
                    session_id=session.id,
                    unique_person_count=total_unique_people,
                    total_person_count=total_detected,
                    first_time_visitor_count=first_time_visitor_count,
                    peak_occupancy=peak_occupancy_so_far,
                    average_occupancy=avg_occupancy,
                    entry_count=None,
                    exit_count=None,
                    occupancy_timeline=downsampled_timeline,
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
