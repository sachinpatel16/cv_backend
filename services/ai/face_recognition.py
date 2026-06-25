import io
import cv2
import numpy as np
from PIL import Image
from pillow_heif import register_heif_opener
from insightface.app import FaceAnalysis

class FaceRecognitionService:
    def __init__(self):
        self.apps = {}

    def _lazy_init(self, model_name: str = "buffalo_l"):
        if model_name not in self.apps:
            # Register HEIF opener to support HEIC format
            register_heif_opener()
            
            try:
                # Initialize detection and recognition pipeline on CPU
                app = FaceAnalysis(
                    name=model_name,
                    providers=["CPUExecutionProvider"]
                )
                # Default det_size=(640, 640) offers the best balance of speed & quality on CPU
                app.prepare(ctx_id=0, det_size=(640, 640))
                self.apps[model_name] = app
            except Exception as e:
                import sys
                print(
                    f"\n[FaceRecognitionService ERROR] Failed to initialize InsightFace FaceAnalysis for model '{model_name}'. "
                    "This usually happens when the pre-trained model files are corrupted "
                    "(e.g., due to an interrupted download) or missing.\n"
                    "HOW TO FIX:\n"
                    "1. If running in Docker, ensure you mount the host's '~/.insightface' folder to "
                    "'/root/.insightface' in docker-compose.yml so the container can reuse your host's models.\n"
                    f"2. If the files are corrupted, delete the model directory at "
                    f"~/.insightface/models/{model_name}/ on the host and restart the container to let it redownload clean files.\n",
                    file=sys.stderr
                )
                raise e

    def extract_faces(self, image_bytes: bytes, model_name: str = "buffalo_l") -> list[dict]:
        """
        Decodes the image from bytes and extracts bounding boxes and embeddings for all detected faces.
        
        Returns:
            list of dicts, each containing:
                "face_idx": int
                "bbox": list[int] [x1, y1, x2, y2]
                "embedding": list[float] (512 dimensions)
        """
        self._lazy_init(model_name)
        app = self.apps[model_name]
        
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
        faces = app.get(img)
        
        results = []
        for i, face in enumerate(faces):
            results.append({
                "face_idx": i,
                "bbox": [int(x) for x in face.bbox],
                "embedding": face.embedding.tolist(),
                "det_score": float(face.det_score) if hasattr(face, "det_score") else 0.0,
                "kps": face.kps.tolist() if getattr(face, "kps", None) is not None else None,
                "gender": int(face.gender) if getattr(face, "gender", None) is not None else None,
                "age": int(face.age) if getattr(face, "age", None) is not None else None
            })
            
        return results

    def load_search_embeddings(self, selfie_path: str | None, fallback_embedding: list[float], model_name: str = "buffalo_l") -> list[np.ndarray]:
        """
        Loads all face embeddings from the reference selfie image file if it exists,
        otherwise falls back to the database-stored embedding.
        """
        import os
        group_embeddings = []
        if selfie_path and os.path.exists(selfie_path):
            try:
                with open(selfie_path, "rb") as sf:
                    selfie_content = sf.read()
                selfie_faces = self.extract_faces(selfie_content, model_name=model_name)
                group_embeddings = [np.array(face["embedding"]) for face in selfie_faces]
            except Exception as e:
                print(f"Failed to extract group faces from {selfie_path}: {e}")

        if not group_embeddings:
            group_embeddings = [np.array(fallback_embedding)]
        return group_embeddings

    def extract_faces_from_video(self, video_path: str, interval: float = 1.0, model_name: str = "buffalo_l"):
        """
        Generator that processes a video frame-by-frame at given interval,
        detecting and yielding all faces found in the video.
        """
        from services.camera_processors.video_service import VideoFrameExtractor
        
        extractor = VideoFrameExtractor(video_path, interval_seconds=interval)
        for frame_small, frame, sec, scale in extractor.extract_frames():
            # Encode frame to bytes for face recognition service
            _, encoded_img = cv2.imencode(".jpg", frame_small)
            frame_bytes = encoded_img.tobytes()

            # Detect faces
            faces = self.extract_faces(frame_bytes, model_name=model_name)
            for face in faces:
                # Restore coordinates back to original full resolution
                orig_bbox = [
                    int(face["bbox"][0] / scale),
                    int(face["bbox"][1] / scale),
                    int(face["bbox"][2] / scale),
                    int(face["bbox"][3] / scale)
                ]
                yield {
                    "bbox": orig_bbox,
                    "embedding": face["embedding"],
                    "timestamp": sec
                }

    def search_face_in_video(
        self,
        video_path: str,
        target_embeddings: list[np.ndarray],
        threshold: float,
        interval: float = 1.0,
        model_name: str = "buffalo_l"
    ):
        """
        Generator that processes a video frame-by-frame at given interval, 
        detecting and matching faces against target reference embeddings.
        Yields dicts with match details.
        """
        from services.camera_processors.video_service import VideoFrameExtractor
        from services.ai.math_utils import find_best_face_match
        
        extractor = VideoFrameExtractor(video_path, interval_seconds=interval)
        for frame_small, frame, sec, scale in extractor.extract_frames():
            h_orig, w_orig = frame.shape[:2]

            # Encode frame to bytes for face recognition service
            _, encoded_img = cv2.imencode(".jpg", frame_small)
            frame_bytes = encoded_img.tobytes()

            # Extract face embeddings
            faces = self.extract_faces(frame_bytes, model_name=model_name)

            if len(faces) > 0:
                best_face, best_sim = find_best_face_match(target_embeddings, faces, threshold)
                if best_face is not None:
                    # Restore coordinates back to original video size
                    x1 = max(0, min(int(best_face["bbox"][0] / scale), w_orig - 1))
                    y1 = max(0, min(int(best_face["bbox"][1] / scale), h_orig - 1))
                    x2 = max(0, min(int(best_face["bbox"][2] / scale), w_orig - 1))
                    y2 = max(0, min(int(best_face["bbox"][3] / scale), h_orig - 1))
                    orig_bbox = [x1, y1, x2, y2]

                    yield {
                        "timestamp": sec,
                        "frame": frame,
                        "bbox": orig_bbox,
                        "similarity": best_sim,
                        "scale": scale
                    }

    def cluster_faces(self, faces: list[dict], threshold: float = 0.45) -> list[dict]:
        """
        Clusters a list of face objects based on their embeddings using DBSCAN.
        
        Args:
            faces: list of dicts, each must contain:
                "id": Any unique identifier
                "embedding": list or np.ndarray (512 dimensions)
                "bbox": list of 4 ints
                "timestamp": float or None
                "face_idx": int
                optional key "metadata": dict (e.g., filename, filepath, media_type, etc.)
            threshold: similarity threshold for grouping faces (default 0.45)
            
        Returns:
            list of dicts, each representing a unique face cluster:
                "cluster_id": int
                "representative": dict (the face dictionary with largest bbox area)
                "total_occurrences": int
                "occurrences": list of face dicts in this cluster (sorted)
        """
        if not faces:
            return []

        from sklearn.cluster import DBSCAN
        import numpy as np

        embeddings = np.array([f["embedding"] for f in faces])
        eps = 1.0 - threshold

        clustering = DBSCAN(eps=eps, min_samples=1, metric="cosine").fit(embeddings)
        labels = clustering.labels_

        cluster_groups = {}
        for idx, label in enumerate(labels):
            if label not in cluster_groups:
                cluster_groups[label] = []
            cluster_groups[label].append(faces[idx])

        unique_faces = []
        for label, group in cluster_groups.items():
            # Pick representative face: largest bbox area
            representative = max(group, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
            
            # Sort occurrences: filename metadata first (if available), then timestamp or face_idx
            def sort_key(f):
                meta = f.get("metadata", {})
                filename = meta.get("filename", "")
                ts = f["timestamp"] if f["timestamp"] is not None else f["face_idx"]
                return (filename, ts)

            sorted_group = sorted(group, key=sort_key)

            unique_faces.append({
                "cluster_id": int(label),
                "representative": representative,
                "total_occurrences": len(group),
                "occurrences": sorted_group
            })

        # Sort the overall unique faces list by total occurrences descending
        unique_faces.sort(key=lambda x: x["total_occurrences"], reverse=True)
        return unique_faces



# Singleton instance for application-wide reuse
face_rec_service = FaceRecognitionService()

