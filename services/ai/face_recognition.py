import io
import cv2
import numpy as np
from PIL import Image
from pillow_heif import register_heif_opener
from insightface.app import FaceAnalysis

class FaceRecognitionService:
    def __init__(self):
        self.app = None

    def _lazy_init(self):
        if self.app is None:
            # Register HEIF opener to support HEIC format
            register_heif_opener()
            
            # Initialize detection and recognition pipeline on CPU
            self.app = FaceAnalysis(
                name="buffalo_l",
                providers=["CPUExecutionProvider"]
            )
            # Default det_size=(640, 640) offers the best balance of speed & quality on CPU
            self.app.prepare(ctx_id=0, det_size=(640, 640))

    def extract_faces(self, image_bytes: bytes) -> list[dict]:
        """
        Decodes the image from bytes and extracts bounding boxes and embeddings for all detected faces.
        
        Returns:
            list of dicts, each containing:
                "face_idx": int
                "bbox": list[int] [x1, y1, x2, y2]
                "embedding": list[float] (512 dimensions)
        """
        self._lazy_init()
        
        img = None
        # Try decoding with Pillow (supports HEIC, WebP, JPEG, PNG, etc.)
        try:
            image = Image.open(io.BytesIO(image_bytes))
            if image.mode != "RGB":
                image = image.convert("RGB")
            img_rgb = np.array(image)
            # Convert RGB to BGR for OpenCV / InsightFace
            img = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        except Exception:
            # Fallback to OpenCV if Pillow fails
            nparr = np.frombuffer(image_bytes, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            raise ValueError("Invalid image file format or corrupted image bytes.")

        # Detect faces and extract embeddings
        faces = self.app.get(img)
        
        results = []
        for i, face in enumerate(faces):
            results.append({
                "face_idx": i,
                "bbox": [int(x) for x in face.bbox],
                "embedding": face.embedding.tolist()
            })
            
        return results

# Singleton instance for application-wide reuse
face_rec_service = FaceRecognitionService()
