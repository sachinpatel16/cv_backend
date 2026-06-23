import torch
import torch.nn as nn
import torchvision.models as models
from torchvision.models import ResNet18_Weights
from torchvision import transforms
import cv2
import numpy as np
from collections import defaultdict

class ReIDFeatureExtractor:
    def __init__(self):
        self.device = torch.device('cuda' if torch.cuda.is_available() else 'cpu')
        
        # Load feature extractor model (ResNet-18)
        resnet = models.resnet18(weights=ResNet18_Weights.DEFAULT)
        self.feature_extractor = nn.Sequential(*list(resnet.children())[:-1])
        self.feature_extractor.to(self.device)
        self.feature_extractor.eval()
        
        # Crop preprocessing transform
        self.transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((224, 224)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            )
        ])

    @torch.no_grad()
    def get_embedding(self, crop: np.ndarray) -> np.ndarray | None:
        """
        Extracts a normalized 512-dimensional visual embedding from a person crop.
        """
        if crop is None or crop.size == 0:
            return None
        try:
            crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            tensor = self.transform(crop_rgb).unsqueeze(0).to(self.device)
            features = self.feature_extractor(tensor)
            features = features.squeeze().cpu().numpy()
            norm = np.linalg.norm(features)
            if norm > 0:
                features = features / norm
            return features
        except Exception as e:
            print(f"Error extracting embedding: {e}")
            return None


class LineCrossingCounter:
    def __init__(self, start_point: list[int] | np.ndarray, end_point: list[int] | np.ndarray, counting_region: int = 15):
        """
        Mathematical line crossing logic based on directional vector geometry.
        """
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
        return -buffer <= projection_length <= self.line_length + buffer
        
    def update(self, object_id: int, center_point: tuple[float, float]) -> str | bool:
        """
        Tracks a coordinate sequence and fires 'in' or 'out' exactly when the object's centroid
        crosses the segment.
        """
        self.object_tracks[object_id].append(center_point)
        
        current_pos = np.array(self.object_tracks[object_id][-1])
        current_distance = self.get_distance_from_line(current_pos)
        current_side = 1 if current_distance >= 0 else -1
        
        if object_id not in self.armed_side:
            if abs(current_distance) > self.counting_region:
                self.armed_side[object_id] = current_side
            else:
                self.armed_side[object_id] = None
                
        if self.armed_side[object_id] is None:
            if abs(current_distance) > self.counting_region:
                self.armed_side[object_id] = current_side
                
        if self.armed_side[object_id] is None:
            return False
            
        if len(self.object_tracks[object_id]) < 2:
            return False
            
        prev_pos = np.array(self.object_tracks[object_id][-2])
        
        if current_side != self.armed_side[object_id]:
            prev_side = self.armed_side[object_id]
            self.armed_side[object_id] = None  # Disarm
            
            if self.is_projection_on_segment(current_pos):
                if self.is_vertical:
                    # Left to Right: IN, Right to Left: OUT
                    if prev_pos[0] <= current_pos[0]:
                        self.in_count += 1
                        return "in"
                    else:
                        self.out_count += 1
                        return "out"
                else:
                    # Top to Bottom: IN, Bottom to Top: OUT
                    if prev_pos[1] <= current_pos[1]:
                        self.in_count += 1
                        return "in"
                    else:
                        self.out_count += 1
                        return "out"
        return False
