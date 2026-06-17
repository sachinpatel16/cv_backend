import cv2
import logging
from typing import Generator, Tuple

logger = logging.getLogger(__name__)

class VideoFrameExtractor:
    """
    A reusable frame generator for video processing tasks.
    Handles frame rate extraction, stepping by custom time intervals, 
    and optional resizing/downscaling for CPU efficiency.
    """
    def __init__(self, filepath: str, interval_seconds: float = 1.0, max_dimension: int = 640):
        self.filepath = filepath
        self.interval = interval_seconds
        self.max_dimension = max_dimension

    def extract_frames(self) -> Generator[Tuple[cv2.Mat, float, float], None, None]:
        """
        Yields:
            frame: Resized/downscaled BGR frame (numpy.ndarray)
            timestamp_sec: Elapsed time in seconds from the video start
            scale_factor: The multiplier used to resize the frame (small_dim / orig_dim)
        """
        cap = cv2.VideoCapture(self.filepath)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {self.filepath}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        frame_step = max(1, int(fps * self.interval))
        f_idx = 0

        try:
            while True:
                if f_idx % frame_step == 0:
                    ret, frame = cap.read()
                    if not ret or frame is None:
                        break

                    h_orig, w_orig = frame.shape[:2]
                    scale = 1.0
                    
                    if max(h_orig, w_orig) > self.max_dimension:
                        scale = self.max_dimension / max(h_orig, w_orig)
                        frame_resized = cv2.resize(frame, (int(w_orig * scale), int(h_orig * scale)))
                    else:
                        frame_resized = frame

                    timestamp_sec = f_idx / fps
                    yield frame_resized, frame, timestamp_sec, scale

                    # Fast skip of intermediate frames
                    for _ in range(frame_step - 1):
                        ret = cap.grab()
                        if not ret:
                            break
                        f_idx += 1
                else:
                    ret = cap.grab()
                    if not ret:
                        break
                f_idx += 1
        finally:
            cap.release()
