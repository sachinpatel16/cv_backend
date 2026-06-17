import io
import os
import uuid
from PIL import Image
import pillow_heif

def convert_and_save_image(content: bytes, filename: str, target_dir: str) -> str:
    """
    Saves an image from bytes. If it's a HEIC/HEIF image, converts it to JPG.
    Returns the saved file path.
    """
    file_ext = os.path.splitext(filename)[1].lower()
    unique_name = f"{uuid.uuid4()}{file_ext}"
    
    os.makedirs(target_dir, exist_ok=True)
    
    if file_ext in {".heic", ".heif"}:
        try:
            pillow_heif.register_heif_opener()
            image = Image.open(io.BytesIO(content))
            if image.mode != "RGB":
                image = image.convert("RGB")
            
            unique_name = f"{uuid.uuid4()}.jpg"
            filepath = os.path.join(target_dir, unique_name)
            image.save(filepath, "JPEG", quality=90)
            return filepath
        except Exception as e:
            print(f"HEIC conversion failed, falling back: {str(e)}")
            
    filepath = os.path.join(target_dir, unique_name)
    with open(filepath, "wb") as f:
        f.write(content)
    return filepath
