import os
import uuid
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.activity.repository import ActivityRepository
from modules.activity.model import ActivityConfig, ActivityAlert
from modules.activity.schema import ActivityProcessPayload
from modules.gallery.repository import GalleryRepository

class ActivityService:
    def __init__(self, db: AsyncSession):
        self.repo = ActivityRepository(db)
        self.gallery_repo = GalleryRepository(db)
        self.db = db

    async def process_activity_media(
        self, gallery_media_id: uuid.UUID, tenant_id: uuid.UUID, payload: ActivityProcessPayload
    ):
        """
        Update tracking configuration settings and trigger the background Celery process on a gallery media item.
        """
        media = await self.gallery_repo.get_media_by_id(gallery_media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gallery media source not found or unauthorized access."
            )

        # Upsert the config in database using the payload settings
        await self.repo.upsert_activity_config(
            gallery_media_id=gallery_media_id,
            tenant_id=tenant_id,
            polygon_points=payload.polygon_points,
            detect_fall=payload.detect_fall,
            detect_aggression=payload.detect_aggression,
            detect_intrusion=payload.detect_intrusion,
            detect_loitering=payload.detect_loitering,
            loitering_threshold=payload.loitering_threshold,
            detect_occupancy=payload.detect_occupancy,
            occupancy_limit=payload.occupancy_limit,
            detect_sleeping=payload.detect_sleeping,
            detect_walking=payload.detect_walking,
            selected_activities=payload.selected_activities
        )
        await self.db.commit()

        try:
            await self.gallery_repo.update_media_status(gallery_media_id, "processing")
            await self.db.commit()

            from modules.activity.tasks import process_activity_media_task
            process_activity_media_task.delay(str(gallery_media_id), interval=payload.interval)
        except Exception as e:
            await self.gallery_repo.update_media_status(gallery_media_id, "failed")
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to submit background activity tracking task: {e}"
            )

        # Reload and return
        return await self.gallery_repo.get_media_by_id(gallery_media_id, tenant_id)

    async def get_process_status(self, gallery_media_id: uuid.UUID, tenant_id: uuid.UUID) -> dict:
        """
        Retrieves the current execution status and configuration details for a gallery media item.
        """
        media = await self.gallery_repo.get_media_by_id(gallery_media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gallery media source not found or unauthorized access."
            )
        
        config = await self.repo.get_activity_config(gallery_media_id, tenant_id)
        return {
            "gallery_media_id": media.id,
            "status": media.status,
            "processed_filepath": media.processed_filepath,
            "config": config
        }

    async def get_process_history(self, gallery_media_id: uuid.UUID, tenant_id: uuid.UUID) -> List[ActivityAlert]:
        """
        Retrieves historical alerts generated for this specific gallery media item.
        """
        media = await self.gallery_repo.get_media_by_id(gallery_media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gallery media source not found or unauthorized access."
            )
        return await self.repo.get_alerts(tenant_id=tenant_id, gallery_media_id=gallery_media_id)

    async def get_alerts_report(
        self, tenant_id: uuid.UUID, gallery_media_id: Optional[uuid.UUID] = None,
        activity_type: Optional[str] = None, severity: Optional[str] = None
    ) -> List[ActivityAlert]:
        """Fetch alert history reports with filters."""
        return await self.repo.get_alerts(
            tenant_id=tenant_id,
            gallery_media_id=gallery_media_id,
            activity_type=activity_type,
            severity=severity
        )

    async def get_alerts_summary(
        self, tenant_id: uuid.UUID, gallery_media_id: Optional[uuid.UUID] = None
    ) -> dict:
        """Fetch statistics summary of alerts."""
        return await self.repo.get_alerts_summary(tenant_id, gallery_media_id)
