import os
import uuid
from typing import List, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.gallery.repository import GalleryRepository
from modules.gallery.model import GalleryMedia
from shared.utils.image import convert_and_save_image

GALLERY_DIR = os.path.join("storage", "gallery")
os.makedirs(GALLERY_DIR, exist_ok=True)

class GalleryService:
    def __init__(self, db: AsyncSession):
        self.repo = GalleryRepository(db)
        self.db = db

    async def upload_media_batch(
        self, files: List[UploadFile], media_type: str, tenant_id: uuid.UUID
    ) -> List[GalleryMedia]:
        """
        Uploads multiple event photos or videos, saves them under storage/gallery/, and indexes them.
        """
        results = []
        for file in files:
            # Deduplication check
            existing = await self.repo.get_media_by_filename(file.filename, tenant_id)
            if existing:
                if existing.status in {"completed", "processing"}:
                    results.append(existing)
                    continue
                else:
                    # Clean up old failed record and file
                    if os.path.exists(existing.filepath):
                        try:
                            os.remove(existing.filepath)
                        except Exception:
                            pass
                    await self.db.delete(existing)
                    await self.db.flush()

            if media_type == "photo":
                content = await file.read()
                filepath = convert_and_save_image(content, file.filename, GALLERY_DIR)
                unique_name = os.path.basename(filepath)
            else:
                file_ext = os.path.splitext(file.filename)[1].lower()
                unique_name = f"{uuid.uuid4()}{file_ext}"
                filepath = os.path.join(GALLERY_DIR, unique_name)
                with open(filepath, "wb") as f:
                    while True:
                        chunk = await file.read(1024 * 1024)  # 1MB chunk size
                        if not chunk:
                            break
                        f.write(chunk)

            # Create database record in "completed" or "pending" status initially.
            # In general, we mark it as "completed" upload, or "pending" if it awaits processing.
            # For raw gallery media, upload itself is completed immediately.
            media = await self.repo.create_gallery_media(
                tenant_id=tenant_id,
                filename=file.filename or unique_name,
                filepath=filepath,
                media_type=media_type
            )
            media.status = "completed"
            await self.db.flush()
            results.append(media)

        await self.db.commit()
        return results

    async def get_media_details(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[GalleryMedia]:
        """Retrieve gallery media metadata."""
        return await self.repo.get_media_by_id(media_id, tenant_id)

    async def get_all_media_sources(self, tenant_id: uuid.UUID, media_type: Optional[str] = None) -> List[GalleryMedia]:
        """Retrieve all active gallery media sources for the tenant."""
        return await self.repo.get_all_media(tenant_id, media_type)

    async def delete_media_source(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Soft deletes gallery media and physically deletes its file from disk."""
        media = await self.repo.get_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gallery media source not found or unauthorized access."
            )

        # Delete physical raw file from disk
        if media.filepath and os.path.exists(media.filepath):
            try:
                os.remove(media.filepath)
            except Exception:
                pass
        
        # Delete physical processed file from disk
        if media.processed_filepath and os.path.exists(media.processed_filepath):
            try:
                os.remove(media.processed_filepath)
            except Exception:
                pass

        await self.repo.delete_media(media_id, tenant_id)
        await self.db.commit()

    async def delete_all_media_sources(self, tenant_id: uuid.UUID) -> int:
        """Soft deletes all gallery media sources for a tenant and deletes physical files."""
        filepaths = await self.repo.bulk_delete_media_sources(tenant_id)
        
        deleted_count = 0
        for filepath in filepaths:
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    deleted_count += 1
                except Exception:
                    pass
                    
        await self.db.commit()
        return deleted_count

    @classmethod
    async def migrate_existing_heic(cls):
        """Background task to convert any HEIC file uploaded to JPG."""
        from database.session import SessionLocal
        from PIL import Image
        import pillow_heif
        from sqlalchemy import select
        
        try:
            pillow_heif.register_heif_opener()
            async with SessionLocal() as session:
                result = await session.execute(
                    select(GalleryMedia).where(
                        (GalleryMedia.filepath.ilike("%.heic")) | (GalleryMedia.filepath.ilike("%.heif"))
                    )
                )
                sources = result.scalars().all()
                if not sources:
                    return
                
                print(f"[HEIC Gallery Migration] Found {len(sources)} HEIC/HEIF gallery sources to convert.")
                for source in sources:
                    old_path = source.filepath
                    if not os.path.exists(old_path):
                        continue
                    try:
                        image = Image.open(old_path)
                        if image.mode != "RGB":
                            image = image.convert("RGB")
                        
                        base, _ = os.path.splitext(old_path)
                        new_path = f"{base}.jpg"
                        
                        image.save(new_path, "JPEG", quality=90)
                        source.filepath = new_path
                        
                        if source.filename.lower().endswith(".heic"):
                            source.filename = source.filename[:-5] + ".jpg"
                        elif source.filename.lower().endswith(".heif"):
                            source.filename = source.filename[:-5] + ".jpg"
                        
                        os.remove(old_path)
                        print(f"[HEIC Gallery Migration] Converted: {old_path} -> {new_path}")
                    except Exception as err:
                        print(f"[HEIC Gallery Migration] Failed to convert {old_path}: {err}")
                await session.commit()
        except Exception as e:
            print(f"[HEIC Gallery Migration] Error: {str(e)}")
