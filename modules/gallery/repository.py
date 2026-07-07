import uuid
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from modules.gallery.model import GalleryMedia

class GalleryRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_gallery_media(
        self, tenant_id: uuid.UUID, filename: str, filepath: str, media_type: str
    ) -> GalleryMedia:
        """Create a new gallery media source entry (photo or video)."""
        media = GalleryMedia(
            tenant_id=tenant_id,
            filename=filename,
            filepath=filepath,
            media_type=media_type,
            status="pending"
        )
        self.db.add(media)
        await self.db.flush()
        return media

    async def get_media_by_id(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[GalleryMedia]:
        """Fetch gallery media by ID, scoped to a specific tenant."""
        stmt = select(GalleryMedia).where(
            GalleryMedia.id == media_id,
            GalleryMedia.tenant_id == tenant_id,
            GalleryMedia.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_media_by_filename(self, filename: str, tenant_id: uuid.UUID) -> Optional[GalleryMedia]:
        """Fetch gallery media by filename and tenant."""
        stmt = select(GalleryMedia).where(
            GalleryMedia.filename == filename,
            GalleryMedia.tenant_id == tenant_id,
            GalleryMedia.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_media(self, tenant_id: uuid.UUID, media_type: Optional[str] = None) -> List[GalleryMedia]:
        """Fetch all active, non-deleted gallery media scoped to a tenant."""
        stmt = (
            select(GalleryMedia)
            .where(
                GalleryMedia.tenant_id == tenant_id,
                GalleryMedia.is_delete == False
            )
        )
        if media_type:
            stmt = stmt.where(GalleryMedia.media_type == media_type)
            
        stmt = stmt.order_by(GalleryMedia.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_media(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[GalleryMedia]:
        """Soft delete a gallery media source, scoped to tenant."""
        stmt = select(GalleryMedia).where(
            GalleryMedia.id == media_id,
            GalleryMedia.tenant_id == tenant_id,
            GalleryMedia.is_delete == False
        )
        result = await self.db.execute(stmt)
        media = result.scalars().first()
        if media:
            media.is_delete = True
            await self.db.flush()
        return media

    async def update_media_status(self, media_id: uuid.UUID, status: str) -> None:
        """Update processing status of a gallery media source."""
        stmt = (
            update(GalleryMedia)
            .where(GalleryMedia.id == media_id)
            .values(status=status)
        )
        await self.db.execute(stmt)

    async def update_processed_filepath(self, media_id: uuid.UUID, processed_filepath: str) -> None:
        """Update processed filepath of a gallery media source."""
        stmt = (
            update(GalleryMedia)
            .where(GalleryMedia.id == media_id)
            .values(processed_filepath=processed_filepath)
        )
        await self.db.execute(stmt)

    async def bulk_delete_media_sources(self, tenant_id: uuid.UUID) -> List[str]:
        """Soft delete all media sources for a tenant and return their filepaths."""
        stmt = select(GalleryMedia).where(
            GalleryMedia.tenant_id == tenant_id,
            GalleryMedia.is_delete == False
        )
        result = await self.db.execute(stmt)
        media_sources = list(result.scalars().all())
        
        filepaths = []
        for media in media_sources:
            media.is_delete = True
            filepaths.append(media.filepath)
            if media.processed_filepath:
                filepaths.append(media.processed_filepath)
                
        await self.db.flush()
        return filepaths
