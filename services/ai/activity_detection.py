import os
import sys
import numpy as np
import cv2
from typing import Generator, List, Optional, Tuple, Dict
from ultralytics import YOLO
from services.camera_processors.video_service import VideoFrameExtractor

class LoiteringTracker:
    def __init__(self):
        # track_id -> entry_timestamp
        self.entry_times: Dict[int, float] = {}

    def track_person(self, track_id: int, is_inside_roi: bool, timestamp: float) -> Tuple[bool, float]:
        """
        Tracks a person's time inside ROI.
        Returns (is_present_in_roi, time_spent).
        """
        if not is_inside_roi:
            self.entry_times.pop(track_id, None)
            return False, 0.0

        if track_id not in self.entry_times:
            self.entry_times[track_id] = timestamp
            return True, 0.0

        time_spent = timestamp - self.entry_times[track_id]
        return True, time_spent

    def reset_track(self, track_id: int):
        self.entry_times.pop(track_id, None)


class OccupancyTracker:
    def calculate_occupancy(self, person_centers: List[Tuple[int, int]], polygon_np: Optional[np.ndarray]) -> int:
        """
        Calculates how many person centers are inside the polygon ROI.
        If polygon_np is None, calculates headcount in the entire frame.
        """
        if polygon_np is None:
            return len(person_centers)

        count = 0
        for pt in person_centers:
            result = cv2.pointPolygonTest(polygon_np, (float(pt[0]), float(pt[1])), False)
            if result >= 0:
                count += 1
        return count


class ActivityDetectionService:
    def __init__(self):
        self.model = None

    def _lazy_init(self):
        if self.model is None:
            # Loads yolov8n-pose.pt (will auto-download if missing)
            self.model = YOLO("yolov8n-pose.pt")

    def inside_polygon(self, point: Tuple[int, int], polygon: np.ndarray) -> bool:
        """Checks if a point (x, y) is inside the polygon."""
        result = cv2.pointPolygonTest(polygon, (float(point[0]), float(point[1])), False)
        return result >= 0  # 1 = inside, 0 = on edge, -1 = outside

    def process_video(
        self,
        video_path: str,
        polygon_points: Optional[List[List[int]]] = None,
        detect_fall: bool = True,
        detect_aggression: bool = True,
        detect_intrusion: bool = True,
        detect_loitering: bool = True,
        loitering_threshold: float = 15.0,
        detect_occupancy: bool = True,
        occupancy_limit: int = 5,
        detect_sleeping: bool = True,
        detect_walking: bool = True,
        interval: float = 1.0,
    ) -> Generator[dict, None, None]:
        """
        Processes a video frame-by-frame using VideoFrameExtractor, applying ROI, pose, loitering, and occupancy heuristics.
        Yields detected alerts.
        """
        self._lazy_init()
        
        # Track trackers
        loitering_tracker = LoiteringTracker()
        occupancy_tracker = OccupancyTracker()
        
        # Track history dictionary for cooldowns and temporal calculations
        person_history = {}
        last_occupancy_alert = -10.0
        
        # Parse polygon points once
        polygon_np = None
        if polygon_points and len(polygon_points) >= 3:
            polygon_np = np.array(polygon_points, dtype=np.int32)

        extractor = VideoFrameExtractor(video_path, interval_seconds=interval)
        for frame_small, frame, sec, scale in extractor.extract_frames():
            h_orig, w_orig = frame.shape[:2]
            
            # Run YOLO track with persist=True to track IDs
            results = self.model.track(frame_small, persist=True, verbose=False)
            
            if not results or len(results) == 0 or results[0].boxes is None:
                continue

            boxes = results[0].boxes
            keypoints_obj = results[0].keypoints
            
            if boxes.id is None:
                continue

            track_ids = boxes.id.cpu().numpy().astype(int)
            current_detections = []
            
            # Prune loitering tracker for disappeared IDs to free memory
            disappeared_ids = set(loitering_tracker.entry_times.keys()) - set(track_ids)
            for d_id in disappeared_ids:
                loitering_tracker.reset_track(d_id)

            for idx, track_id in enumerate(track_ids):
                # Get bounding box in frame_small coordinates and restore to full size
                box_small = boxes.xyxy[idx].cpu().numpy()
                xmin = int(box_small[0] / scale)
                ymin = int(box_small[1] / scale)
                xmax = int(box_small[2] / scale)
                ymax = int(box_small[3] / scale)
                
                # Check bounds
                xmin, xmax = max(0, min(xmin, w_orig - 1)), max(0, min(xmax, w_orig - 1))
                ymin, ymax = max(0, min(ymin, h_orig - 1)), max(0, min(ymax, h_orig - 1))
                
                box_height = ymax - ymin
                box_width = xmax - xmin
                aspect_ratio = box_height / (box_width + 1e-6)

                # Keypoints in small frame coords, scale back to original resolution
                xy_small = keypoints_obj.xy[idx].cpu().numpy()  # [17, 2]
                conf = keypoints_obj.conf[idx].cpu().numpy()  # [17]
                
                xy = xy_small / scale

                # Fall / Slip detection
                has_shoulders = conf[5] > 0.5 and conf[6] > 0.5
                has_hips = conf[11] > 0.5 and conf[12] > 0.5
                
                body_angle = 0.0
                is_horizontal = False
                
                if has_shoulders and has_hips:
                    shoulder_x = (xy[5][0] + xy[6][0]) / 2.0
                    shoulder_y = (xy[5][1] + xy[6][1]) / 2.0
                    hip_x = (xy[11][0] + xy[12][0]) / 2.0
                    hip_y = (xy[11][1] + xy[12][1]) / 2.0
                    
                    dx = hip_x - shoulder_x
                    dy = hip_y - shoulder_y
                    body_angle = np.degrees(np.arctan2(abs(dx), abs(dy) + 1e-6))
                    if body_angle > 55.0:
                        is_horizontal = True
                        
                if not (has_shoulders and has_hips) and aspect_ratio < 0.75:
                    is_horizontal = True

                # Init history
                if track_id not in person_history:
                    person_history[track_id] = {
                        "hip_y": [],
                        "rel_wrist_l": [],
                        "rel_wrist_r": [],
                        "rel_elbow_l": [],
                        "rel_elbow_r": [],
                        "last_fall_alert": -10.0,
                        "last_intrusion_alert": -10.0,
                        "last_aggression_alert": -10.0,
                        "last_loitering_alert": -10.0,
                        "last_sleeping_alert": -10.0,
                        "last_walking_alert": -10.0,
                    }
                
                history = person_history[track_id]
                
                # Hips Y tracking
                current_hip_y = (xy[11][1] + xy[12][1]) / 2.0 if has_hips else (ymin + ymax) / 2.0
                history["hip_y"].append(current_hip_y)
                if len(history["hip_y"]) > 10:
                    history["hip_y"].pop(0)

                # Wrist & elbow velocity tracking (normalized)
                if conf[9] > 0.5 and conf[5] > 0.5:
                    history["rel_wrist_l"].append(xy[9] - xy[5])
                if len(history["rel_wrist_l"]) > 10:
                    history["rel_wrist_l"].pop(0)

                if conf[10] > 0.5 and conf[6] > 0.5:
                    history["rel_wrist_r"].append(xy[10] - xy[6])
                if len(history["rel_wrist_r"]) > 10:
                    history["rel_wrist_r"].pop(0)

                if conf[7] > 0.5 and conf[5] > 0.5:
                    history["rel_elbow_l"].append(xy[7] - xy[5])
                if len(history["rel_elbow_l"]) > 10:
                    history["rel_elbow_l"].pop(0)

                if conf[8] > 0.5 and conf[6] > 0.5:
                    history["rel_elbow_r"].append(xy[8] - xy[6])
                if len(history["rel_elbow_r"]) > 10:
                    history["rel_elbow_r"].pop(0)

                # Slip calculation
                is_slipping = False
                if len(history["hip_y"]) >= 3:
                    y_delta = history["hip_y"][-1] - history["hip_y"][-3]
                    norm_delta = y_delta / (box_height + 1e-6)
                    if norm_delta > 0.25 and is_horizontal:
                        is_slipping = True

                # Determine if alert needed
                center_x = int((xmin + xmax) / 2)
                center_y = int((ymin + ymax) / 2)

                # Check ROI intrusion
                is_intruded = False
                if polygon_np is not None:
                    is_intruded = self.inside_polygon((center_x, center_y), polygon_np)

                # Save detection state for current frame
                current_detections.append({
                    "track_id": track_id,
                    "bbox": [xmin, ymin, xmax, ymax],
                    "center": (center_x, center_y),
                    "is_horizontal": is_horizontal,
                    "is_slipping": is_slipping,
                    "is_intruded": is_intruded,
                    "xy": xy,
                    "conf": conf,
                    "aspect_ratio": aspect_ratio,
                    "body_angle": body_angle
                })

            # Check individual safety, intrusion, and loitering alerts
            for det in current_detections:
                t_id = det["track_id"]
                hist = person_history[t_id]
                
                # Fall/Slip alert
                if detect_fall:
                    if det["is_slipping"] or det["is_horizontal"]:
                        if sec - hist["last_fall_alert"] >= 5.0:  # 5-second cooldown
                            hist["last_fall_alert"] = sec
                            alert_type = "slipping" if det["is_slipping"] else "falling"
                            yield {
                                "track_id": t_id,
                                "activity_type": alert_type,
                                "timestamp": sec,
                                "bbox": det["bbox"],
                                "severity": "critical",
                                "frame": frame
                            }

                # Intrusion alert
                if detect_intrusion and det["is_intruded"]:
                    if sec - hist["last_intrusion_alert"] >= 5.0:
                        hist["last_intrusion_alert"] = sec
                        yield {
                            "track_id": t_id,
                            "activity_type": "roi_intrusion",
                            "timestamp": sec,
                            "bbox": det["bbox"],
                            "severity": "warning",
                            "frame": frame
                        }

                # Loitering alert
                if detect_loitering:
                    # Person needs to be inside the ROI boundary to accumulate loitering duration
                    in_roi, time_spent = loitering_tracker.track_person(t_id, det["is_intruded"], sec)
                    if in_roi and time_spent >= loitering_threshold:
                        if sec - hist["last_loitering_alert"] >= 5.0:
                            hist["last_loitering_alert"] = sec
                            yield {
                                "track_id": t_id,
                                "activity_type": "loitering",
                                "timestamp": sec,
                                "bbox": det["bbox"],
                                "severity": "warning",
                                "frame": frame
                            }

                # Sleeping alert
                if detect_sleeping and det["is_horizontal"]:
                    if sec - hist["last_sleeping_alert"] >= 10.0:
                        hist["last_sleeping_alert"] = sec
                        yield {
                            "track_id": t_id,
                            "activity_type": "sleeping",
                            "timestamp": sec,
                            "bbox": det["bbox"],
                            "severity": "info",
                            "frame": frame
                        }

                # Walking alert
                if detect_walking and det["aspect_ratio"] > 1.2 and not det["is_horizontal"]:
                    if sec - hist["last_walking_alert"] >= 10.0:
                        hist["last_walking_alert"] = sec
                        yield {
                            "track_id": t_id,
                            "activity_type": "walking",
                            "timestamp": sec,
                            "bbox": det["bbox"],
                            "severity": "info",
                            "frame": frame
                        }

            # Aggression detection (pairs check)
            if detect_aggression and len(current_detections) >= 2:
                for i in range(len(current_detections)):
                    for j in range(i + 1, len(current_detections)):
                        d1 = current_detections[i]
                        d2 = current_detections[j]
                        
                        b1 = d1["bbox"]
                        b2 = d2["bbox"]
                        
                        c1 = d1["center"]
                        c2 = d2["center"]
                        dist = np.sqrt((c1[0] - c2[0])**2 + (c1[1] - c2[1])**2)
                        
                        overlap = not (b1[2] < b2[0] or b2[2] < b1[0] or b1[3] < b2[1] or b2[3] < b1[1])
                        avg_size = ((b1[2] - b1[0] + b1[3] - b1[1]) + (b2[2] - b2[0] + b2[3] - b2[1])) / 4.0
                        
                        if dist < (avg_size * 2.2) or overlap:
                            h1 = person_history[d1["track_id"]]
                            h2 = person_history[d2["track_id"]]
                            
                            agg1 = False
                            agg2 = False
                            for key in ["rel_wrist_l", "rel_wrist_r", "rel_elbow_l", "rel_elbow_r"]:
                                if len(h1[key]) >= 3:
                                    spd = np.linalg.norm(h1[key][-1] - h1[key][-3])
                                    if (spd / avg_size) > 0.20:
                                        agg1 = True
                                if len(h2[key]) >= 3:
                                    spd = np.linalg.norm(h2[key][-1] - h2[key][-3])
                                    if (spd / avg_size) > 0.20:
                                        agg2 = True
                                        
                            if agg1 or agg2:
                                # Trigger aggression alert with 5s cooldown for both
                                if (sec - h1["last_aggression_alert"] >= 5.0) and (sec - h2["last_aggression_alert"] >= 5.0):
                                    h1["last_aggression_alert"] = sec
                                    h2["last_aggression_alert"] = sec
                                    yield {
                                        "track_id": d1["track_id"],
                                        "activity_type": "aggression",
                                        "timestamp": sec,
                                        "bbox": d1["bbox"],
                                        "severity": "critical",
                                        "frame": frame
                                    }

            # Occupancy Limit Alert (Run at the end of the frame)
            if detect_occupancy:
                person_centers = [det["center"] for det in current_detections]
                headcount = occupancy_tracker.calculate_occupancy(person_centers, polygon_np)
                if headcount > occupancy_limit:
                    if sec - last_occupancy_alert >= 5.0:
                        last_occupancy_alert = sec
                        yield {
                            "track_id": None,
                            "activity_type": "occupancy_overlimit",
                            "timestamp": sec,
                            "bbox": None,
                            "severity": "warning",
                            "frame": frame
                        }


activity_detection_service = ActivityDetectionService()
