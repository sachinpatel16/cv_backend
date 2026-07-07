import os
import uuid
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from modules.peoplecount.repository import PeopleCountRepository
from modules.peoplecount.model import PeopleCountMedia, PeopleCountResult

class PeopleCountService:
    def __init__(self, db: AsyncSession):
        self.repo = PeopleCountRepository(db)
        self.db = db

    async def trigger_analysis(
        self,
        gallery_media_id: uuid.UUID,
        tenant_id: uuid.UUID,
        min_track_frames: int = 300,
        track_buffer: int = 150,
        confidence_threshold: float = 0.35
    ) -> PeopleCountMedia:
        """
        Registers a new people counting analysis session on an uploaded gallery media file,
        and schedules the background tracking task.
        """
        # Validate that the gallery media file exists and belongs to this tenant
        from modules.gallery.repository import GalleryRepository
        gallery_repo = GalleryRepository(self.db)
        gallery_media = await gallery_repo.get_media_by_id(gallery_media_id, tenant_id)
        if not gallery_media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gallery media record not found or access denied."
            )

        # Create an analysis session record in DB
        analysis = await self.repo.create_analysis_session(
            tenant_id=tenant_id,
            gallery_media_id=gallery_media_id
        )
        await self.db.commit()

        # Trigger background counting tasks via Celery
        try:
            await self.repo.update_media_status(analysis.id, "processing")
            await self.db.commit()
            
            from workers.tasks import index_peoplecount_task
            index_peoplecount_task.delay(
                str(analysis.id),
                gallery_media.filepath,
                gallery_media.media_type,
                min_track_frames,
                track_buffer,
                confidence_threshold
            )
        except Exception as e:
            await self.repo.update_media_status(analysis.id, "failed")
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to submit people count task: {str(e)}"
            )

        # Return session with eager loaded gallery media
        return await self.repo.get_media_by_id(analysis.id, tenant_id)

    async def get_all_media(self, tenant_id: uuid.UUID) -> List[PeopleCountMedia]:
        return await self.repo.get_all_media(tenant_id)

    async def get_media_detail(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> PeopleCountMedia:
        media = await self.repo.get_media_with_results(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analysis session not found or access denied."
            )
        return media

    async def get_media_results(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> List[PeopleCountResult]:
        # Validate media exists first
        media = await self.repo.get_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analysis session not found or access denied."
            )
        return await self.repo.get_results_by_media_id(media_id, tenant_id)

    async def delete_media(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        media = await self.repo.get_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analysis session not found or access denied."
            )
        
        # Physical cleanup of processed files associated with this session if it updated GalleryMedia
        if media.gallery_media and media.gallery_media.processed_filepath:
            if os.path.exists(media.gallery_media.processed_filepath):
                try:
                    os.remove(media.gallery_media.processed_filepath)
                except Exception:
                    pass
            # Clear processed_filepath on gallery media
            media.gallery_media.processed_filepath = None

        await self.repo.delete_media(media_id, tenant_id)
        await self.db.commit()
