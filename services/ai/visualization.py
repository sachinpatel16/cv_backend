import cv2
import numpy as np
from typing import List, Tuple

def format_time(seconds: float) -> str:
    """Formats float seconds into HH:MM:SS format."""
    h = int(seconds // 3600)
    m = int((seconds % 3600) // 60)
    s = int(seconds % 60)
    return f"{h:02d}:{m:02d}:{s:02d}"

def draw_bbox_on_image(
    img: np.ndarray, 
    bbox: List[int], 
    label: str, 
    color: Tuple[int, int, int] = (0, 255, 0), 
    thickness: int = 3
) -> np.ndarray:
    """
    Draws a bounding box and text label background/text on an image.
    
    Args:
        img: Input BGR image (numpy.ndarray).
        bbox: Bounding box coordinates [x1, y1, x2, y2].
        label: Text to display on top of the bounding box.
        color: Box color in BGR format (default is green).
        thickness: Box border thickness.
    """
    vis = img.copy()
    x1, y1, x2, y2 = bbox
    cv2.rectangle(vis, (x1, y1), (x2, y2), color, thickness)
    
    (w, h), _ = cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.7, 2)
    cv2.rectangle(vis, (x1, max(y1 - 30, 0)), (x1 + w, max(y1, 30)), color, -1)
    cv2.putText(vis, label, (x1, max(y1 - 8, 22)),
                cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 0, 0), 2)
    return vis
