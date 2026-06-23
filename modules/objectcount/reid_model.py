import torch
import torch.nn as nn
import cv2
import numpy as np
import logging

from modules.objectcount import osnet

logger = logging.getLogger(__name__)

class ReIDExtractor:
    """
    Extracts deep visual features from cropped detection bounding boxes
    using a pre-trained OSNet model (purpose-built for person re-identification).
    """
    def __init__(self, device="cpu", model_name="osnet_x0_5"):
        self.device = device.lower()
        if self.device == "cuda" and not torch.cuda.is_available():
            logger.warning("CUDA requested for Re-ID but not available. Using CPU.")
            self.device = "cpu"
        elif self.device == "mps" and not (hasattr(torch.backends, "mps") and torch.backends.mps.is_available()):
            logger.warning("MPS requested for Re-ID but not available. Using CPU.")
            self.device = "cpu"

        logger.info(f"Initializing OSNet Re-ID Extractor ({model_name}) on device '{self.device}'...")
        
        try:
            # Dynamically load the requested model size from osnet module
            model_fn = getattr(osnet, model_name, None)
            if model_fn is None:
                logger.warning(f"OSNet model '{model_name}' not found. Defaulting to 'osnet_x0_5'.")
                model_fn = osnet.osnet_x0_5
                model_name = "osnet_x0_5"
                
            self.model = model_fn(pretrained=True)
            self.model.eval()
            self.model.to(self.device)
            # Find the feature dimension dynamically
            self.feature_dim = self.model.feature_dim
            logger.info(f"OSNet model {model_name} loaded and configured successfully ({self.feature_dim}D output).")
        except Exception as e:
            logger.error(f"Failed to load OSNet model '{model_name}' for Re-ID: {e}")
            raise e

        # Preprocessing transforms compatible with standard OSNet Re-ID inputs (256x128)
        from torchvision import transforms
        self.transform = transforms.Compose([
            transforms.ToPILImage(),
            transforms.Resize((256, 128)),
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
            np.ndarray: Matrix of shape (num_crops, feature_dim) representing the normalized embeddings.
        """
        if not crops:
            return np.empty((0, self.feature_dim), dtype=np.float32)

        tensors = []
        for crop in crops:
            # OpenCV BGR -> PyTorch PIL RGB
            crop_rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
            tensors.append(self.transform(crop_rgb))

        # Stack into batch and move to device
        batch = torch.stack(tensors).to(self.device)
        
        # Forward pass through OSNet (outputs feature_dim feature map)
        features = self.model(batch)
        
        # L2 normalize the features along the channel dimension so that 
        # cosine similarity is equivalent to dot product.
        features = nn.functional.normalize(features, p=2, dim=1)
        
        return features.cpu().numpy()
