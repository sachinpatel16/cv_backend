import os
import sys
import numpy as np
import cv2
import math
from typing import Generator, List, Optional, Tuple, Dict
from ultralytics import YOLO
from services.camera_processors.video_service import VideoFrameExtractor

FALL_WINDOW_SIZE = int(os.getenv("FALL_WINDOW_SIZE", 30))
FALL_V_THRESH = float(os.getenv("FALL_V_THRESH", 60.0))
FALL_AR_THRESH = float(os.getenv("FALL_AR_THRESH", 0.35))
FALL_DY_THRESH = float(os.getenv("FALL_DY_THRESH", 20.0))

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
        # TF AVA Model attributes
        self.tf_graph = None
        self.tf_sess = None
        self.tf_labels = []
        self.tf_input_tensor = None
        self.tf_output_tensors = {}

    def _lazy_init(self):
        if self.model is None:
            # Loads yolov8n-pose.pt using self-healing loader
            from shared.utils.model_loader import get_model_path
            weights_path = get_model_path("activity", "yolov8n-pose.pt")
            self.model = YOLO(weights_path)

    def _lazy_init_tf(self):
        if self.tf_sess is None:
            # Self-healing copy: Ensure model and labels exist
            dest_dir = os.path.join("models", "activity")
            os.makedirs(dest_dir, exist_ok=True)
            
            graph_path = os.path.join(dest_dir, "frozen_inference_graph.pb")
            labels_path = os.path.join(dest_dir, "labels.txt")
            
            src_dir = os.path.join("..", "human-activity-detection")
            src_graph = os.path.join(src_dir, "frozen_inference_graph.pb")
            src_labels = os.path.join(src_dir, "labels.txt")
            
            import shutil
            if not os.path.exists(graph_path) and os.path.exists(src_graph):
                print(f"Self-healing copy: copying {src_graph} -> {graph_path}")
                shutil.copy2(src_graph, graph_path)
            if not os.path.exists(labels_path) and os.path.exists(src_labels):
                print(f"Self-healing copy: copying {src_labels} -> {labels_path}")
                shutil.copy2(src_labels, labels_path)
                
            if not os.path.exists(graph_path) or not os.path.exists(labels_path):
                raise FileNotFoundError(
                    f"Model assets not found at {graph_path} or {labels_path} and source directory is missing."
                )
                
            # Read labels
            with open(labels_path, 'r') as f:
                self.tf_labels = [line.strip() for line in f.readlines()]
                
            import tensorflow.compat.v1 as tf
            tf.disable_v2_behavior()
            
            self.tf_graph = tf.Graph()
            with self.tf_graph.as_default():
                graph_def = tf.GraphDef()
                with tf.gfile.GFile(graph_path, 'rb') as f:
                    serialized_graph = f.read()
                    graph_def.ParseFromString(serialized_graph)
                    tf.import_graph_def(graph_def, name='')
                    
                self.tf_sess = tf.Session(graph=self.tf_graph)
                
                ops = self.tf_graph.get_operations()
                all_tensor_names = {output.name for op in ops for output in op.outputs}
                
                for key in ['num_detections', 'detection_boxes', 'detection_scores', 'detection_classes']:
                    tensor_name = key + ':0'
                    if tensor_name in all_tensor_names:
                        self.tf_output_tensors[key] = self.tf_graph.get_tensor_by_name(tensor_name)
                        
                self.tf_input_tensor = self.tf_graph.get_tensor_by_name('image_tensor:0')

    def process_video_tf(
        self,
        video_path: str,
        output_video_path: Optional[str] = None,
        polygon_points: Optional[List[List[int]]] = None,
        selected_activities: Optional[List[str]] = None,
        detect_fall: bool = True,
        detect_sleeping: bool = True,
        detect_walking: bool = True,
        interval: float = 0.1,
        threshold: float = 0.5
    ) -> Generator[dict, None, None]:
        self._lazy_init_tf()
        
        # Determine target activities
        target_labels = None
        if selected_activities and len(selected_activities) > 0:
            target_labels = {lbl.lower().strip() for lbl in selected_activities}
        else:
            # Build target list from legacy flags
            target_labels = set()
            if detect_fall:
                target_labels.add("fall down")
                target_labels.add("get up")
            if detect_sleeping:
                target_labels.add("lie/sleep")
            if detect_walking:
                target_labels.add("walk")
                target_labels.add("run/jog")
                target_labels.add("stand")
                target_labels.add("crouch/kneel")
                target_labels.add("bend/bow (at the waist)")
                
            # If no target set, use all classes except default exclusions
            if not target_labels:
                exclusions = {1, 3, 17, 37, 43, 45, 46, 47, 59, 65, 74, 77, 78, 79, 80}
                target_labels = {
                    self.tf_labels[idx].lower().strip()
                    for idx in range(len(self.tf_labels))
                    if (idx + 1) not in exclusions and self.tf_labels[idx] != "N/A"
                }

        # Parse polygon ROI points once
        polygon_np = None
        if polygon_points and len(polygon_points) >= 3:
            polygon_np = np.array(polygon_points, dtype=np.int32)

        # Set up VideoWriter if needed
        cap = cv2.VideoCapture(video_path)
        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()

        writer = None
        if output_video_path:
            os.makedirs(os.path.dirname(output_video_path), exist_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            # Adjust output video FPS based on frame extraction interval
            output_fps = max(1, int(1.0 / interval)) if interval > 0 else int(fps)
            writer = cv2.VideoWriter(output_video_path, fourcc, output_fps, (width, height))

        colors = np.random.uniform(0, 255, size=(len(self.tf_labels) + 1, 3))
        
        extractor = VideoFrameExtractor(video_path, interval_seconds=interval)
        try:
            for frame_small, frame, sec, scale in extractor.extract_frames():
                h_orig, w_orig = frame.shape[:2]
                
                # Expand dims for batching
                frame_exp = np.expand_dims(frame_small, axis=0)
                
                # Run TF inference
                output_dict = self.tf_sess.run(
                    self.tf_output_tensors,
                    feed_dict={self.tf_input_tensor: frame_exp}
                )
                
                num_detections = int(output_dict['num_detections'][0])
                detection_classes = output_dict['detection_classes'][0].astype(np.uint8)
                detection_boxes = output_dict['detection_boxes'][0]
                detection_scores = output_dict['detection_scores'][0]
                
                frame_annotated = frame.copy()
                
                # Draw ROI polygon boundary on the output frame if config exists
                if polygon_np is not None:
                    cv2.polylines(frame_annotated, [polygon_np], isClosed=True, color=(0, 255, 0), thickness=2)
                
                for i in range(num_detections):
                    score = float(detection_scores[i])
                    if score < threshold:
                        continue
                        
                    class_idx = int(detection_classes[i]) - 1
                    if class_idx < 0 or class_idx >= len(self.tf_labels):
                        continue
                        
                    label = self.tf_labels[class_idx]
                    label_clean = label.lower().strip()
                    
                    if label == "N/A" or label_clean not in target_labels:
                        continue
                        
                    bbox_norm = detection_boxes[i]
                    ymin = int(bbox_norm[0] * h_orig)
                    xmin = int(bbox_norm[1] * w_orig)
                    ymax = int(bbox_norm[2] * h_orig)
                    xmax = int(bbox_norm[3] * w_orig)
                    
                    # ROI intrusion filtering
                    center_x = (xmin + xmax) // 2
                    center_y = (ymin + ymax) // 2
                    if polygon_np is not None:
                        is_inside = cv2.pointPolygonTest(polygon_np, (float(center_x), float(center_y)), False) >= 0
                        if not is_inside:
                            continue
                            
                    # Determine severity based on label
                    severity = "info"
                    if label_clean in ["fall down", "fight/hit (a person)", "push (another person)", "grab (a person)"]:
                        severity = "critical"
                    elif label_clean in ["run/jog", "crouch/kneel", "get up", "jump/leap"]:
                        severity = "warning"
                        
                    # Annotate frame
                    color = colors[class_idx + 1]
                    cv2.rectangle(frame_annotated, (xmin, ymin), (xmax, ymax), color, 2)
                    text = f"{label} ({score:.2f})"
                    cv2.putText(frame_annotated, text, (xmin, max(ymin - 10, 20)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
                                
                    yield {
                        "track_id": None,
                        "activity_type": label,
                        "timestamp": sec,
                        "bbox": [xmin, ymin, xmax, ymax],
                        "severity": severity,
                        "frame": frame
                    }
                    
                if writer is not None:
                    writer.write(frame_annotated)
        finally:
            if writer is not None:
                writer.release()


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
        interval: float = 0.1,
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
                        "horizontal_history": [],
                        "horizontal_start_time": None,
                        "centers": [],
                        "com_history": [],
                        "ar_history": [],
                        "last_fall_alert": -10.0,
                        "last_intrusion_alert": -10.0,
                        "last_aggression_alert": -10.0,
                        "last_loitering_alert": -10.0,
                        "last_sleeping_alert": -10.0,
                        "last_walking_alert": -10.0,
                        "fall_pose_window": [],
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

                # Track horizontal history & sleeping state duration
                history["horizontal_history"].append(is_horizontal)
                if len(history["horizontal_history"]) > 15:
                    history["horizontal_history"].pop(0)

                if is_horizontal:
                    if history["horizontal_start_time"] is None:
                        history["horizontal_start_time"] = sec
                else:
                    history["horizontal_start_time"] = None

                # Fall / Slip detection (using logic from Human-Fall-Detection-master)
                is_falling = False
                is_slipping = False
                
                # Check if pose has required keypoints for tracking center of mass
                # Required: left eye (1), right eye (2), left shoulder (5), right shoulder (6)
                required_joints = [1, 2, 5, 6]
                is_complete = all(conf[idx] > 0.2 for idx in required_joints) and np.sum(conf > 0.2) >= 10
                
                if is_complete:
                    scale_to_960 = 960.0 / w_orig
                    xy_960 = xy * scale_to_960
                    history["fall_pose_window"].append((xy_960, conf, sec))
                    if len(history["fall_pose_window"]) > FALL_WINDOW_SIZE:
                        history["fall_pose_window"].pop(0)
                
                if len(history["fall_pose_window"]) >= FALL_WINDOW_SIZE:
                    p1_xy, p1_conf, p1_sec = history["fall_pose_window"][0]
                    p2_xy, p2_conf, p2_sec = history["fall_pose_window"][-1]
                    
                    # Compute Center of Mass (COM)
                    c1 = np.mean([p1_xy[1], p1_xy[2], p1_xy[5], p1_xy[6]], axis=0)
                    c2 = np.mean([p2_xy[1], p2_xy[2], p2_xy[5], p2_xy[6]], axis=0)
                    
                    dx = c2[0] - c1[0]
                    dy = c2[1] - c1[1]
                    dist = np.sqrt(dx**2 + dy**2)
                    
                    # Duration in seconds
                    t_duration = p2_sec - p1_sec
                    if t_duration <= 0:
                        t_duration = 0.1
                    velocity = min(dist / t_duration, 300.0)
                    
                    # Aspect Ratio function
                    def _get_aspect_ratio(kpts_xy, kpts_conf):
                        visible = kpts_xy[kpts_conf > 0.2]
                        if len(visible) == 0:
                            return 0.0
                        x_coords = visible[:, 0]
                        y_coords = visible[:, 1]
                        w_box = np.max(x_coords) - np.min(x_coords)
                        h_box = np.max(y_coords) - np.min(y_coords)
                        return w_box / h_box if h_box > 0 else 0.0
                    
                    ar_start = _get_aspect_ratio(p1_xy, p1_conf)
                    ar_end = _get_aspect_ratio(p2_xy, p2_conf)
                    ar_delta = ar_end - ar_start
                    
                    # Check SpeedDrop (velocity threshold and vertical drop threshold)
                    if velocity > FALL_V_THRESH and dy > FALL_DY_THRESH and ar_end > 0.1:
                        is_falling = True
                        
                    # Check DownFlat (vertical drop threshold and aspect ratio threshold)
                    if dy > FALL_DY_THRESH and ar_delta > FALL_AR_THRESH:
                        is_slipping = True

                # Determine if alert needed
                center_x = int((xmin + xmax) / 2)
                center_y = int((ymin + ymax) / 2)

                # Track center history
                history["centers"].append((center_x, center_y, sec))
                while history["centers"] and sec - history["centers"][0][2] > 2.0:
                    history["centers"].pop(0)

                # Velocity-based movement detection
                is_moving = False
                if len(history["centers"]) >= 2:
                    oldest_center = history["centers"][0]
                    for c in history["centers"]:
                        if sec - c[2] >= 0.5:
                            oldest_center = c
                            break
                    dt = sec - oldest_center[2]
                    if dt >= 0.3:
                        dist = np.sqrt((center_x - oldest_center[0])**2 + (center_y - oldest_center[1])**2)
                        velocity = dist / (box_height + 1e-6) / dt
                        if velocity > 0.08:
                            is_moving = True

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
                    "is_falling": is_falling,
                    "is_slipping": is_slipping,
                    "is_moving": is_moving,
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
                    if det["is_slipping"] or det["is_falling"]:
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
                    horizontal_duration = sec - hist["horizontal_start_time"] if hist["horizontal_start_time"] is not None else 0.0
                    if horizontal_duration >= 5.0:
                        if sec - hist["last_sleeping_alert"] >= 10.0 and sec - hist["last_fall_alert"] >= 15.0:
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
                if detect_walking and det["aspect_ratio"] > 1.2 and not det["is_horizontal"] and det["is_moving"]:
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
