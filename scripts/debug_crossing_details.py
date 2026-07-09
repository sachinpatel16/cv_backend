import cv2
import numpy as np
import supervision as sv
from ultralytics import YOLO
from collections import defaultdict

# Implement same LineCrossingCounter class for inspection
class LineCrossingCounterDebug:
    def __init__(self, start_point: list[int] | np.ndarray, end_point: list[int] | np.ndarray, counting_region: int = 15):
        self.start_point = np.array(start_point)
        self.end_point = np.array(end_point)
        self.counting_region = counting_region
        
        self.line_vector = self.end_point - self.start_point
        self.line_length = np.linalg.norm(self.line_vector)
        self.unit_line_vector = self.line_vector / self.line_length
        self.normal_vector = np.array([-self.unit_line_vector[1], self.unit_line_vector[0]])
        
        dx = abs(self.end_point[0] - self.start_point[0])
        dy = abs(self.end_point[1] - self.start_point[1])
        self.is_vertical = dx < dy
        
        self.object_tracks = defaultdict(list)
        self.armed_side = {}  # tracker_id -> side (1 or -1)
        self.in_count = 0
        self.out_count = 0
        
    def get_distance_from_line(self, point: np.ndarray) -> float:
        return np.dot(point - self.start_point, self.normal_vector)
        
    def is_projection_on_segment(self, point: np.ndarray) -> bool:
        point_vector = point - self.start_point
        projection_length = np.dot(point_vector, self.unit_line_vector)
        buffer = 50
        res = -buffer <= projection_length <= self.line_length + buffer
        return res, projection_length

    def update(self, object_id: int, center_point: tuple[float, float]) -> str | bool:
        self.object_tracks[object_id].append(center_point)
        
        current_pos = np.array(self.object_tracks[object_id][-1])
        current_distance = self.get_distance_from_line(current_pos)
        current_side = 1 if current_distance >= 0 else -1
        
        print(f"Track {object_id}: Pos={center_point}, Dist={current_distance:.2f}, Side={current_side}")
        
        if object_id not in self.armed_side:
            if abs(current_distance) > self.counting_region:
                self.armed_side[object_id] = current_side
                print(f"  -> Armed Track {object_id} on side {current_side}")
            else:
                self.armed_side[object_id] = None
                print(f"  -> Track {object_id} too close to line, armed = None")
                
        if self.armed_side[object_id] is None:
            if abs(current_distance) > self.counting_region:
                self.armed_side[object_id] = current_side
                print(f"  -> Armed Track {object_id} on side {current_side}")
                
        if self.armed_side[object_id] is None:
            return False
            
        if len(self.object_tracks[object_id]) < 2:
            return False
            
        prev_pos = np.array(self.object_tracks[object_id][-2])
        
        if current_side != self.armed_side[object_id]:
            prev_side = self.armed_side[object_id]
            self.armed_side[object_id] = None  # Disarm
            print(f"  -> Track {object_id} crossed to opposite side! Disarmed.")
            
            on_seg, proj_len = self.is_projection_on_segment(current_pos)
            print(f"  -> Projection check: on_seg={on_seg}, proj_len={proj_len:.2f} (line_length={self.line_length:.2f})")
            
            if on_seg:
                if self.is_vertical:
                    # Left to Right: IN, Right to Left: OUT
                    if prev_pos[0] <= current_pos[0]:
                        self.in_count += 1
                        print(f"  -> CRITICAL: Track {object_id} crossed IN (vertical check)")
                        return "in"
                    else:
                        self.out_count += 1
                        print(f"  -> CRITICAL: Track {object_id} crossed OUT (vertical check)")
                        return "out"
                else:
                    # Top to Bottom: IN, Bottom to Top: OUT
                    if prev_pos[1] <= current_pos[1]:
                        self.in_count += 1
                        print(f"  -> CRITICAL: Track {object_id} crossed IN (horizontal check)")
                        return "in"
                    else:
                        self.out_count += 1
                        print(f"  -> CRITICAL: Track {object_id} crossed OUT (horizontal check)")
                        return "out"
        return False

def main():
    model = YOLO("yolo26n.pt")
    cap = cv2.VideoCapture("storage/gallery/54d28af3-82e6-4e1f-89fd-d1624bd1264d.mp4")
    if not cap.isOpened():
        print("Could not open video.")
        return
        
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    tracker = sv.ByteTrack(frame_rate=int(fps))
    
    line_start = [370, 466]
    line_end = [986, 577]
    line_counter = LineCrossingCounterDebug(line_start, line_end)
    
    frame_idx = 0
    while cap.isOpened():
        ret, frame = cap.read()
        if not ret:
            break
        frame_idx += 1
        
        results = model(frame, conf=0.3, classes=[0], verbose=False)
        detections = sv.Detections.from_ultralytics(results[0])
        detections = tracker.update_with_detections(detections)
        
        if detections.tracker_id is not None:
            for xyxy, tracker_id in zip(detections.xyxy, detections.tracker_id):
                x1, y1, x2, y2 = map(int, xyxy)
                center_x = (x1 + x2) / 2
                center_y = (y1 + y2) / 2
                
                line_counter.update(tracker_id, (center_x, center_y))

    print(f"Total processed frames: {frame_idx}")
    print(f"Final Count: In={line_counter.in_count}, Out={line_counter.out_count}")

if __name__ == "__main__":
    main()
