import torch
import torch.nn as nn
import cv2
import numpy as np
import logging

logger = logging.getLogger(__name__)

class ReIDExtractor:
    """
    Extracts deep visual features from cropped detection bounding boxes
    using a pre-trained MobileNetV3-Small model (with its classification head removed).
    """
    def __init__(self, device="cpu"):
        self.device = device.lower()
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA requested for Re-ID but not available. Using CPU.")
            self.device = "cpu"
        elif self.device == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            logger.warning("MPS requested for Re-ID but not available. Using CPU.")
            self.device = "cpu"

        logger.info(f"Initializing Re-ID Extractor on device '{self.device}'...")
        
        try:
            # We use torchvision's pretrained mobilenet_v3_small. 
            # To remain compatible with both older and newer torchvision versions:
            try:
                from torchvision.models import mobilenet_v3_small, MobileNet_V3_Small_Weights
                self.model = mobilenet_v3_small(weights=MobileNet_V3_Small_Weights.DEFAULT)
                logger.info("Loaded MobileNetV3-Small weights using MobileNet_V3_Small_Weights.DEFAULT")
            except ImportError:
                from torchvision.models import mobilenet_v3_small
                self.model = mobilenet_v3_small(pretrained=True)
                logger.info("Loaded MobileNetV3-Small weights using pretrained=True")
                
            # Replace classification head (classifier layer) with nn.Identity
            # so the model outputs the raw 576-dimensional pooling layer features.
            self.model.classifier = nn.Identity()
            self.model.eval()
            self.model.to(self.device)
            logger.info("Re-ID model loaded and configured successfully.")
        except Exception as e:
            logger.error(f"Failed to load MobileNetV3-Small model for Re-ID: {e}")
            raise e

        # Preprocessing transforms compatible with standard PyTorch Re-ID inputs (128x64)
        from torchvision import transforms
        self.transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((128, 64)),
            transforms.ToTensor(),
            transforms.Normalize(
                mean=[0.485, 0.456, 0.406],
                std=[0.229, 0.224, 0.225]
            )
        ])

    @torch.no_grad()
    def extract(self, crops):
        """
        Extracts L2-normalized feature embeddings for a list of cropped BGR images.
        
        Args:
            crops (list of np.ndarray): Cropped BGR images (OpenCV format)
            
        Returns:
            np.ndarray: Matrix of shape (num_crops, 576) representing the normalized embeddings.
        """
        if not crops:
            return np.empty((0, 576), dtype=np.float32)

        tensors = []
        for crop in crops:
            # OpenCV BGR -> PyTorch PIL RGB
            crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            tensors.append(self.transform(crop_rgb))

        # Stack into batch and move to device
        batch = torch.stack(tensors).to(self.device)
        
        # Forward pass
        features = self.model(batch) # Shape: (batch_size, 576)
        
        # L2 normalize the features along the channel dimension so that 
        # cosine similarity is equivalent to dot product.
        features = nn.functional.normalize(features, p=2, dim=1)
        
        return features.cpu().numpy()
