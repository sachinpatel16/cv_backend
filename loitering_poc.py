import os
import time
import argparse
import cv2
import numpy as np
from ultralytics import YOLO

class PersonState:
    IDLE = "IDLE"
    ENTERING = "ENTERING"
    LOITERING = "LOITERING"
    EXITING = "EXITING"

class LoiteringDetectorPoC:
    def __init__(self, model_path="yolo12n.pt", zone_coords=None, dwell_threshold=8.0, 
                 conf_threshold=0.3, velocity_threshold=80.0, grace_period=1.5, imgsz=640):
        """
        Production-grade Proof of Concept Loitering Detector using YOLO12/YOLO11 + BoT-SORT
        with a State Machine, Debouncing, Perspective Correction, and Velocity Filtering.
        """
        print(f"Initializing YOLO model: {model_path}...")
        self.model = YOLO(model_path)
        self.imgsz = imgsz
        
        # Core Parameters
        self.dwell_threshold = dwell_threshold
        self.conf_threshold = conf_threshold
        self.velocity_threshold = velocity_threshold # Max velocity (corrected px/s) to be considered stationary
        self.grace_period = grace_period # Debounce time in seconds
        
        # Zone Polygon
        self.zone_coords = zone_coords
        self.zone_poly = None
        if zone_coords is not None:
            self.zone_poly = np.array(zone_coords, dtype=np.int32)
            
        # State Machine Tracking: 
        # { track_id: {
        #     "state": PersonState,
        #     "first_seen_in_zone": timestamp,
        #     "last_seen_in_zone": timestamp,
        #     "accumulated_dwell": float,
        #     "centroid_history": [(x, y, timestamp)],
        #     "last_velocity": float,
        #     "alert_triggered": bool,
        #     "outside_grace_start": timestamp or None
        # }}
        self.track_states = {}

    def initialize_default_zone(self, width, height):
        """Initializes a default central quadrilateral zone if none is provided."""
        x1, y1 = int(width * 0.25), int(height * 0.25)
        x2, y2 = int(width * 0.75), int(height * 0.25)
        x3, y3 = int(width * 0.75), int(height * 0.75)
        x4, y4 = int(width * 0.25), int(height * 0.75)
        
        self.zone_coords = [[x1, y1], [x2, y2], [x3, y3], [x4, y4]]
        self.zone_poly = np.array(self.zone_coords, dtype=np.int32)
        print(f"No zone coordinates provided. Initialized default central zone: {self.zone_coords}")

    def is_point_in_zone(self, x, y):
        """Checks if a coordinate point is inside the polygon zone using OpenCV's pointPolygonTest."""
        if self.zone_poly is None:
            return False
        dist = cv2.pointPolygonTest(self.zone_poly, (float(x), float(y)), False)
        return dist >= 0

    def calculate_perspective_corrected_velocity(self, history, new_x, new_y, new_t, frame_height):
        """
        Calculates the velocity of the track, applying a linear perspective scaling factor
        based on the y-coordinate to compensate for distance from the camera (Homography approximation).
        """
        if not history:
            return 0.0
            
        # Look back up to 5 entries in history (roughly 0.2 - 0.5 seconds ago) to smooth out noise
        prev_x, prev_y, prev_t = history[-1]
        
        time_delta = new_t - prev_t
        if time_delta <= 0.001:
            return 0.0
            
        # Euclidean distance in pixel space
        pixel_dist = np.sqrt((new_x - prev_x)**2 + (new_y - prev_y)**2)
        
        # Perspective scale factor: objects at the top of the screen (smaller y) are farther
        # and represent larger real-world movements per pixel.
        # Reference line is at the bottom of the frame (y = frame_height)
        y_ref = max(10, (new_y + prev_y) / 2.0)
        scale_factor = frame_height / y_ref
        
        # Calculate corrected velocity (pixels per second)
        corrected_dist = pixel_dist * scale_factor
        velocity = corrected_dist / time_delta
        
        return round(velocity, 2)

    def update_state_machine(self, track_id, is_inside, bottom_center, current_time, frame_height):
        """
        Advances the state machine for a specific track ID, handling debouncing,
        velocity checks, and state transition logging.
        """
        x, y = bottom_center
        
        # Initialize new track state if unseen
        if track_id not in self.track_states:
            self.track_states[track_id] = {
                "state": PersonState.IDLE,
                "first_seen_in_zone": None,
                "last_seen_in_zone": None,
                "accumulated_dwell": 0.0,
                "centroid_history": [],
                "last_velocity": 0.0,
                "alert_triggered": False,
                "outside_grace_start": None,
                "last_update_time": current_time
            }
            
        track = self.track_states[track_id]
        time_delta = current_time - track["last_update_time"]
        track["last_update_time"] = current_time
        
        # 1. Calculate Velocity (Perspective Corrected)
        velocity = self.calculate_perspective_corrected_velocity(track["centroid_history"], x, y, current_time, frame_height)
        track["last_velocity"] = velocity
        
        # Append to history and maintain window size of 10
        track["centroid_history"].append((x, y, current_time))
        if len(track["centroid_history"]) > 10:
            track["centroid_history"].pop(0)

        # 2. State Machine Transitions
        prev_state = track["state"]
        
        if is_inside:
            # Cancel any active outside grace period
            track["outside_grace_start"] = None
            track["last_seen_in_zone"] = current_time
            
            # Check if moving slowly enough to accumulate dwell time (Velocity Filter)
            is_stationary = velocity <= self.velocity_threshold
            
            if track["state"] == PersonState.IDLE:
                # Transition: IDLE -> ENTERING
                track["state"] = PersonState.ENTERING
                track["first_seen_in_zone"] = current_time
                track["accumulated_dwell"] = 0.0
                print(f"[STATE CHANGE] ID {track_id}: IDLE -> ENTERING (Velocity: {velocity} px/s)")
                
            elif track["state"] in (PersonState.ENTERING, PersonState.LOITERING):
                # Accumulate time if they are stationary/lingering
                if is_stationary:
                    if time_delta > 0:
                        track["accumulated_dwell"] += time_delta
                
                # Check for loitering alert threshold
                if track["accumulated_dwell"] >= self.dwell_threshold:
                    if track["state"] != PersonState.LOITERING:
                        track["state"] = PersonState.LOITERING
                        track["alert_triggered"] = True
                        print(f"[STATE CHANGE/ALERT] ID {track_id}: ENTERING -> LOITERING (Dwell: {round(track['accumulated_dwell'], 1)}s, Velocity: {velocity} px/s)")
                        
        else:
            # Currently outside the zone
            if track["state"] in (PersonState.ENTERING, PersonState.LOITERING):
                if track["outside_grace_start"] is None:
                    # Start the debounce/grace period timer
                    track["outside_grace_start"] = current_time
                else:
                    # Check if grace period has expired
                    outside_duration = current_time - track["outside_grace_start"]
                    if outside_duration > self.grace_period:
                        # Transition: ENTERING/LOITERING -> EXITING
                        track["state"] = PersonState.EXITING
                        print(f"[STATE CHANGE] ID {track_id}: {prev_state} -> EXITING (Total Dwell: {round(track['accumulated_dwell'], 1)}s, Outside Duration: {round(outside_duration, 1)}s)")
            
            elif track["state"] == PersonState.EXITING:
                # Transition: EXITING -> IDLE
                track["state"] = PersonState.IDLE
                track["first_seen_in_zone"] = None
                track["accumulated_dwell"] = 0.0
                track["alert_triggered"] = False
                track["outside_grace_start"] = None
                print(f"[STATE CHANGE] ID {track_id}: EXITING -> IDLE (Cleared)")

    def process_video(self, input_path, output_path=None):
        """Processes the input video frame-by-frame and writes the annotated output."""
        cap = cv2.VideoCapture(input_path)
        if not cap.isOpened():
            print(f"Error: Could not open input video file '{input_path}'")
            return
            
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        
        print(f"Video Properties: Resolution={width}x{height}, FPS={fps}, Total Frames={total_frames}")
        
        # Initialize default zone if not defined
        if self.zone_poly is None:
            self.initialize_default_zone(width, height)
            
        # Initialize Video Writer if output path is provided
        writer = None
        if output_path:
            os.makedirs(os.path.dirname(os.path.abspath(output_path)), exist_ok=True)
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            writer = cv2.VideoWriter(output_path, fourcc, fps, (width, height))
            print(f"Writing annotated video to: {output_path}")

        frame_idx = 0
        start_time = time.time()

        while cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame is None:
                break

            current_time = frame_idx / fps
            frame_idx += 1

            # Run YOLO with BoT-SORT enabled (Class 0 = Person)
            results = self.model.track(
                frame, 
                persist=True, 
                tracker="botsort.yaml", 
                conf=self.conf_threshold,
                classes=[0], 
                verbose=False,
                imgsz=self.imgsz
            )

            active_in_frame_ids = set()
            alerts_triggered_count = 0
            people_in_zone_count = 0
            any_alert_active = False

            detections_to_render = []

            if results and results[0].boxes and results[0].boxes.id is not None:
                boxes = results[0].boxes.xyxy.cpu().numpy()
                track_ids = results[0].boxes.id.int().cpu().numpy()
                
                for box, track_id in zip(boxes, track_ids):
                    x1, y1, x2, y2 = map(int, box)
                    
                    # Compute bottom-center point (ground contact)
                    bottom_center_x = (x1 + x2) // 2
                    bottom_center_y = y2
                    
                    is_inside = self.is_point_in_zone(bottom_center_x, bottom_center_y)
                    
                    # Feed the state machine
                    self.update_state_machine(track_id, is_inside, (bottom_center_x, bottom_center_y), current_time, height)
                    
                    track = self.track_states[track_id]
                    active_in_frame_ids.add(track_id)
                    
                    if track["state"] in (PersonState.ENTERING, PersonState.LOITERING):
                        people_in_zone_count += 1
                        if track["state"] == PersonState.LOITERING:
                            any_alert_active = True
                            alerts_triggered_count += 1
                    
                    detections_to_render.append({
                        "bbox": (x1, y1, x2, y2),
                        "track_id": track_id,
                        "state": track["state"],
                        "dwell": track["accumulated_dwell"],
                        "velocity": track["last_velocity"],
                        "bottom_center": (bottom_center_x, bottom_center_y)
                    })

            # Handle tracks not seen in current frame (clean up / exit state machine)
            stale_ids = []
            for track_id, track in self.track_states.items():
                if track_id not in active_in_frame_ids:
                    # If they were in entering/loitering state, force exit check
                    if track["state"] in (PersonState.ENTERING, PersonState.LOITERING):
                        self.update_state_machine(track_id, False, track["centroid_history"][-1][:2], current_time, height)
                    
                    # Clean up completely if exited and not updated for > 2 seconds
                    if current_time - track["last_update_time"] > 3.0:
                        stale_ids.append(track_id)
                        
            for track_id in stale_ids:
                del self.track_states[track_id]

            # Render Zone Polygon
            poly_color = (0, 0, 255) if any_alert_active else (255, 120, 0)
            cv2.polylines(frame, [self.zone_poly], isClosed=True, color=poly_color, thickness=3)
            
            # Fill zone with transparent overlay
            overlay = frame.copy()
            cv2.fillPoly(overlay, [self.zone_poly], poly_color)
            alpha = 0.15
            cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

            # Render Bounding Boxes, States, and Labels
            for det in detections_to_render:
                x1, y1, x2, y2 = det["bbox"]
                tid = det["track_id"]
                state = det["state"]
                dwell = det["dwell"]
                vel = det["velocity"]
                
                # Determine colors and labels based on the state machine
                if state == PersonState.LOITERING:
                    color = (0, 0, 255) # Red for active loitering
                    label = f"ALERT: Loitering #{tid} ({round(dwell, 1)}s)"
                    box_thickness = 3
                elif state == PersonState.ENTERING:
                    is_moving_fast = vel > self.velocity_threshold
                    if is_moving_fast:
                        color = (0, 255, 255) # Yellow for crossing/moving fast (no dwell timer)
                        label = f"Crossing #{tid} ({round(vel, 0)} px/s)"
                    else:
                        color = (0, 165, 255) # Orange for lingering/stationary (counting dwell)
                        label = f"Lingering #{tid} ({round(dwell, 1)}s)"
                    box_thickness = 2
                elif state == PersonState.EXITING:
                    color = (255, 0, 255) # Pink for exiting zone (grace/exit check)
                    label = f"Exiting #{tid}"
                    box_thickness = 2
                else:
                    color = (0, 255, 0) # Green for outside zone (IDLE)
                    label = f"IDLE #{tid}"
                    box_thickness = 2

                # Draw bounding box
                cv2.rectangle(frame, (x1, y1), (x2, y2), color, box_thickness)
                
                # Draw label banner
                (text_w, text_h), baseline = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.42, 1)
                cv2.rectangle(frame, (x1, y1 - text_h - 10), (x1 + text_w + 10, y1), color, -1)
                cv2.putText(frame, label, (x1 + 5, y1 - 5), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
                
                # Draw bottom center point
                cv2.circle(frame, det["bottom_center"], 4, color, -1)

            # Draw HUD (Heads-Up Display) Panel
            hud_w = 330
            hud_h = 125
            if width > hud_w + 20 and height > hud_h + 20:
                sub_img = frame[10:10+hud_h, 10:10+hud_w]
                rect = np.zeros(sub_img.shape, dtype=np.uint8) + 15
                blended = cv2.addWeighted(sub_img, 0.3, rect, 0.7, 0)
                frame[10:10+hud_h, 10:10+hud_w] = blended

                hud_title_color = (0, 0, 255) if any_alert_active else (255, 255, 255)
                cv2.putText(frame, "ADVANCED LOITERING DETECTOR", (20, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.52, hud_title_color, 2, cv2.LINE_AA)
                cv2.putText(frame, f"Active in Zone: {people_in_zone_count}", (20, 50), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(frame, f"Active Alerts: {alerts_triggered_count}", (20, 70), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (0, 0, 255) if alerts_triggered_count > 0 else (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(frame, f"Dwell Threshold: {self.dwell_threshold}s (Grace: {self.grace_period}s)", (20, 90), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.putText(frame, f"Velocity Filter: <{self.velocity_threshold} px/s", (20, 110), cv2.FONT_HERSHEY_SIMPLEX, 0.42, (255, 255, 255), 1, cv2.LINE_AA)

            if writer:
                writer.write(frame)
            
            if frame_idx % 100 == 0:
                elapsed_real = time.time() - start_time
                fps_processing = frame_idx / elapsed_real
                print(f"Processed {frame_idx}/{total_frames} frames (Speed: {round(fps_processing, 1)} FPS)...")

        cap.release()
        if writer:
            writer.release()
            
        total_time = time.time() - start_time
        print(f"\nProcessing Completed successfully!")
        print(f"Total processing time: {round(total_time, 2)} seconds (Average speed: {round(frame_idx / total_time, 1)} FPS)")

if __name__ == "__main__":
    import sys
    parser = argparse.ArgumentParser(description="YOLO12/YOLO11 BoT-SORT Advanced Loitering Detector")
    parser.add_argument("--input", type=str, required=True, help="Path to input raw CCTV video file")
    parser.add_argument("--output", type=str, default="storage/loitering_outputs/poc_annotated.mp4", help="Path to save annotated video file")
    parser.add_argument("--model", type=str, default="yolo12n.pt", help="YOLO model path or name (e.g., yolo12n.pt, yolo12m.pt, yolo11n.pt)")
    parser.add_argument("--imgsz", type=int, default=640, help="YOLO inference image size (e.g., 320, 640)")
    parser.add_argument("--threshold", type=float, default=8.0, help="Dwell time threshold in seconds before alert")
    parser.add_argument("--conf", type=float, default=0.25, help="YOLO confidence detection threshold")
    parser.add_argument("--zone", type=str, default=None, help="Semicolon-separated coordinates: 'x1,y1;x2,y2;x3,y3;x4,y4'")
    parser.add_argument("--velocity", type=float, default=80.0, help="Max velocity in px/s to accumulate loitering time")
    parser.add_argument("--grace", type=float, default=1.5, help="Debounce grace period in seconds")
    
    args = parser.parse_args()
    
    zone = None
    if args.zone:
        try:
            zone = [[int(coord.split(',')[0]), int(coord.split(',')[1])] for coord in args.zone.split(';')]
            print(f"Parsed custom zone coordinates: {zone}")
        except Exception:
            print("Error: --zone format must be semicolon-separated coordinates, e.g., '100,100;500,100;500,500;100,500'")
            sys.exit(1)
    
    detector = LoiteringDetectorPoC(
        model_path=args.model,
        zone_coords=zone,
        dwell_threshold=args.threshold,
        conf_threshold=args.conf,
        velocity_threshold=args.velocity,
        grace_period=args.grace,
        imgsz=args.imgsz
    )
    
    detector.process_video(args.input, args.output)
