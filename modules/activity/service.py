import os
import uuid
from typing import List, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.activity.repository import ActivityRepository
from modules.activity.model import ActivityMedia, ActivityConfig, ActivityAlert
from modules.activity.schema import ActivityProcessPayload
from shared.utils.image import convert_and_save_image

ACTIVITY_MEDIA_DIR = os.path.join("storage", "activity_media")
os.makedirs(ACTIVITY_MEDIA_DIR, exist_ok=True)


class ActivityService:
    def __init__(self, db: AsyncSession):
        self.repo = ActivityRepository(db)
        self.db = db

    async def upload_activity_media(
        self, files: List[UploadFile], media_type: str, tenant_id: uuid.UUID
    ) -> List[ActivityMedia]:
        """
        Uploads photos or videos for activity tracking, saves them on disk,
        creates DB records, and triggers Celery background tasks.
        """
        results = []
        for file in files:
            # Check for existing filename in tenant namespace (deduplication)
            existing = await self.repo.get_activity_media_by_filename(file.filename, tenant_id)
            if existing:
                if existing.status in {"completed", "processing"}:
                    results.append(existing)
                    continue
                else:
                    # Clear failed or pending records
                    if os.path.exists(existing.filepath):
                        try:
                            os.remove(existing.filepath)
                        except Exception:
                            pass
                    await self.db.delete(existing)
                    await self.db.flush()

            # Save media file
            content = await file.read()
            if media_type == "photo":
                filepath = convert_and_save_image(content, file.filename, ACTIVITY_MEDIA_DIR)
                unique_name = os.path.basename(filepath)
            else:
                file_ext = os.path.splitext(file.filename)[1].lower()
                unique_name = f"{uuid.uuid4()}{file_ext}"
                filepath = os.path.join(ACTIVITY_MEDIA_DIR, unique_name)
                with open(filepath, "wb") as f:
                    f.write(content)

            # Create media record
            media = await self.repo.create_activity_media(
                tenant_id=tenant_id,
                filename=file.filename or unique_name,
                filepath=filepath,
                media_type=media_type
            )
            await self.db.commit()

            # Create default configuration for the uploaded media
            await self.repo.upsert_activity_config(
                media_id=media.id,
                tenant_id=tenant_id,
                polygon_points=None,
                detect_fall=True,
                detect_aggression=True,
                detect_intrusion=True,
                detect_loitering=True,
                loitering_threshold=15.0,
                detect_occupancy=True,
                occupancy_limit=5,
                detect_sleeping=True,
                detect_walking=True,
                selected_activities=None
            )
            await self.db.commit()

            results.append(media)

        return results

    async def get_all_media_sources(self, tenant_id: uuid.UUID) -> List[ActivityMedia]:
        """Retrieve all activity media sources for the active tenant."""
        return await self.repo.get_all_activity_media(tenant_id)

    async def delete_activity_media(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """Deletes activity media source record and removes files from disk."""
        media = await self.repo.get_activity_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activity media source not found or unauthorized access."
            )

        # Delete physical file
        if media.filepath and os.path.exists(media.filepath):
            try:
                os.remove(media.filepath)
            except Exception:
                pass

        await self.repo.delete_activity_media(media_id, tenant_id)
        await self.db.commit()

    async def process_activity_media(
        self, media_id: uuid.UUID, tenant_id: uuid.UUID, payload: ActivityProcessPayload
    ) -> ActivityMedia:
        """
        Update tracking configuration settings and trigger the background Celery process.
        """
        media = await self.repo.get_activity_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activity media source not found or unauthorized access."
            )

        # Upsert the config in database using the payload settings
        await self.repo.upsert_activity_config(
            media_id=media_id,
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
            await self.repo.update_media_status(media_id, "processing")
            await self.db.commit()

            from modules.activity.tasks import process_activity_media_task
            process_activity_media_task.delay(str(media_id), interval=payload.interval)
        except Exception as e:
            await self.repo.update_media_status(media_id, "failed")
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to submit background activity tracking task: {e}"
            )

        media.status = "processing"
        return media

    async def get_process_status(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> dict:
        """
        Retrieves the current execution status and configuration details for a media source.
        """
        media = await self.repo.get_activity_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activity media source not found or unauthorized access."
            )
        
        config = await self.repo.get_activity_config(media_id, tenant_id)
        return {
            "media_id": media.id,
            "status": media.status,
            "output_filepath": media.output_filepath,
            "config": config
        }

    async def get_process_history(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> List[ActivityAlert]:
        """
        Retrieves historical alerts generated for this specific media source.
        """
        media = await self.repo.get_activity_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Activity media source not found or unauthorized access."
            )
        return await self.repo.get_alerts(tenant_id=tenant_id, media_id=media_id)

    async def get_alerts_report(
        self, tenant_id: uuid.UUID, media_id: Optional[uuid.UUID] = None,
        activity_type: Optional[str] = None, severity: Optional[str] = None
    ) -> List[ActivityAlert]:
        """Fetch alert history reports with filters."""
        return await self.repo.get_alerts(
            tenant_id=tenant_id,
            media_id=media_id,
            activity_type=activity_type,
            severity=severity
        )

    async def get_alerts_summary(
        self, tenant_id: uuid.UUID, media_id: Optional[uuid.UUID] = None
    ) -> dict:
        """Fetch statistics summary of alerts."""
        return await self.repo.get_alerts_summary(tenant_id, media_id)
