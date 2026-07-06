import onnxruntime as ort
import numpy as np
import cv2
import os
from pathlib import Path
import logging

logger = logging.getLogger(__name__)

class InsightFaceGenderClassifier:
    """
    Gender classification using InsightFace genderage.onnx.
    """
    
    def __init__(self, model_path="storage/models/insightface/genderage.onnx"):
        available_providers = ort.get_available_providers()
        providers = []
        if "CUDAExecutionProvider" in available_providers:
            providers.append("CUDAExecutionProvider")
        providers.append("CPUExecutionProvider")
        
        logger.info(f"Initializing InsightFace gender classifier on device/providers: {providers}")
        
        # Check standard and fallback paths
        weights_file = Path(model_path)
        if not weights_file.exists():
            # Try fallback to project-relative models dir
            fallback_path = Path("models/insightface/genderage.onnx")
            if fallback_path.exists():
                weights_file = fallback_path
            else:
                raise FileNotFoundError(f"InsightFace model weights not found at: {weights_file.absolute()} or {fallback_path.absolute()}")
        
        self.input_mean = 0.0
        self.input_std = 1.0
        
        try:
            self.session = ort.InferenceSession(str(weights_file), providers=providers)
            self.input_name = self.session.get_inputs()[0].name
            self.output_names = [out.name for out in self.session.get_outputs()]
            logger.info("InsightFace gender ONNX session loaded successfully.")
        except Exception as e:
            logger.error(f"Error loading InsightFace ONNX session: {e}")
            raise e
            
        self.gender_classes = ["Female", "Male"]

    def predict(self, face_image):
        """
        Predicts gender for a cropped face/head image.
        
        Args:
            face_image: NumPy array in BGR format (cv2 image).
            
        Returns:
            dict: {
                "gender": "Male" or "Female",
                "confidence": confidence_score (float, 0.0 to 1.0)
            }
        """
        try:
            if face_image is None or face_image.size == 0:
                return {"gender": "Male", "confidence": 0.5}
                
            aimg = cv2.resize(face_image, (96, 96))
            # Preprocess crop (resize to 96x96 and swap channels BGR -> RGB)
            rgb = cv2.cvtColor(aimg, cv2.COLOR_BGR2RGB)
            normalized = (rgb.astype(np.float32) - self.input_mean) / self.input_std
            blob = np.transpose(normalized, (2, 0, 1))
            blob = np.expand_dims(blob, axis=0) # Add batch dim (1, 3, 96, 96)
            
            pred = self.session.run(self.output_names, {self.input_name: blob})[0][0]
            
            g0, g1 = pred[0], pred[1]
            
            gender_logits = np.array([g0, g1])
            exp_logits = np.exp(gender_logits - np.max(gender_logits))
            gender_probs = exp_logits / np.sum(exp_logits)
            
            pred_idx = np.argmax(gender_probs)
            confidence = float(gender_probs[pred_idx])
            gender = self.gender_classes[pred_idx]
            
            return {
                "gender": gender,
                "confidence": confidence
            }
        except Exception as e:
            logger.error(f"Failed to predict gender for face: {e}")
            return {
                "gender": "Male",  # Fallback
                "confidence": 0.50
            }
