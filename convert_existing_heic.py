import os
import sys
import asyncio
from PIL import Image
import pillow_heif
from sqlalchemy import select

# Add current folder to sys.path so we can import from database and modules
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database.session import SessionLocal
from modules.peoplefind.model import MediaSource

pillow_heif.register_heif_opener()

async def convert_existing():
    async with SessionLocal() as session:
        # Fetch all media sources ending in heic/heif or HEIC/HEIF
        result = await session.execute(
            select(MediaSource).where(
                (MediaSource.filepath.ilike("%.heic")) | (MediaSource.filepath.ilike("%.heif"))
            )
        )
        sources = result.scalars().all()
        print(f"Found {len(sources)} HEIC/HEIF media sources to convert.")
        
        for source in sources:
            old_path = source.filepath
            if not os.path.exists(old_path):
                print(f"File not found on disk: {old_path}, skipping conversion.")
                continue
                
            try:
                # Convert file on disk
                image = Image.open(old_path)
                if image.mode != "RGB":
                    image = image.convert("RGB")
                
                # New filepath
                base, _ = os.path.splitext(old_path)
                new_path = f"{base}.jpg"
                
                image.save(new_path, "JPEG", quality=90)
                print(f"Successfully converted: {old_path} -> {new_path}")
                
                # Update model
                source.filepath = new_path
                
                # Update filename extension to .jpg as well so it displays nicely
                if source.filename.lower().endswith(".heic"):
                    source.filename = source.filename[:-5] + ".jpg"
                elif source.filename.lower().endswith(".heif"):
                    source.filename = source.filename[:-5] + ".jpg"
                
                # Remove old file
                os.remove(old_path)
            except Exception as e:
                print(f"Failed to convert {old_path}: {e}")
                
        await session.commit()
        print("Done database updates!")

if __name__ == "__main__":
    asyncio.run(convert_existing())
