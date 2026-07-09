import os
import shutil
import urllib.request
import logging

logger = logging.getLogger(__name__)

# Base path relative to cv_backend root
_BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
MODELS_DIR = os.path.join(_BASE_DIR, "models")

# Standard YOLO public CDN urls for auto-download if missing
MODEL_URLS = {
    "yolov8n.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n.pt",
    "yolov8n-pose.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolov8n-pose.pt",
    "yolo12n.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo12n.pt",
    "yolo12m.pt": "https://github.com/ultralytics/assets/releases/download/v8.3.0/yolo12m.pt",
    "yolo26m.pt": "https://github.com/ultralytics/assets/releases/download/v8.4.0/yolo26m.pt",
}

def get_model_path(service_name: str, model_filename: str) -> str:
    """
    Returns the absolute path to a model weights file under models/<service_name>/<model_filename>.
    Creates the directory if missing. Auto-downloads standard YOLO weights if they are missing.
    For custom weights, tries to search in fallback directories (like trained-models/) or root,
    and copies them into the correct service folder.
    """
    service_dir = os.path.join(MODELS_DIR, service_name)
    os.makedirs(service_dir, exist_ok=True)
    
    target_path = os.path.join(service_dir, model_filename)
    
    if os.path.exists(target_path):
        return target_path

    # Self-healing / fallback check: search in root or trained-models/
    fallback_sources = [
        os.path.join(_BASE_DIR, model_filename),
        os.path.join(_BASE_DIR, "trained-models", model_filename),
        os.path.join(MODELS_DIR, model_filename),
    ]
    
    for src in fallback_sources:
        if os.path.exists(src):
            logger.info(f"Self-healing: Copying model from fallback source {src} -> {target_path}")
            print(f"Self-healing: Copying model from fallback source {src} -> {target_path}")
            shutil.copy2(src, target_path)
            return target_path

    # Auto-download for standard YOLO assets if URL is defined
    if model_filename in MODEL_URLS:
        url = MODEL_URLS[model_filename]
        logger.info(f"Downloading model {model_filename} from {url} to {target_path}...")
        print(f"Downloading model {model_filename} from {url} to {target_path}...")
        try:
            # Add headers to avoid bot detection block
            opener = urllib.request.build_opener()
            opener.addheaders = [('User-Agent', 'Mozilla/5.0')]
            urllib.request.install_opener(opener)
            
            urllib.request.urlretrieve(url, target_path)
            logger.info(f"Successfully downloaded {model_filename} to {target_path}")
            print(f"Successfully downloaded {model_filename} to {target_path}")
            return target_path
        except Exception as e:
            logger.error(f"Failed to download model {model_filename}: {str(e)}")
            print(f"Failed to download model {model_filename}: {str(e)}")
            # Try to let Ultralytics auto-download it by returning filename if local target creation failed
            return model_filename
            
    # If it is a custom weights file (e.g. cigarette_best.pt) and not found, log error and raise
    error_msg = (
        f"Required model weights file '{model_filename}' is missing for service '{service_name}'. "
        f"Please place it under '{service_dir}/'."
    )
    logger.error(error_msg)
    print(f"ERROR: {error_msg}")
    raise FileNotFoundError(error_msg)
