import os
import uuid
from typing import List, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from modules.objectcount.repository import ObjectCountRepository
from modules.objectcount.model import ObjectCountMedia, ObjectCountResult
from modules.objectcount.schema import ObjectCountAnalyzeRequest
from shared.utils.image import convert_and_save_image

OBJECTCOUNT_MEDIA_DIR = os.path.join("storage", "objectcount_media")
OBJECTCOUNT_OUTPUTS_DIR = os.path.join("storage", "objectcount_outputs")

os.makedirs(OBJECTCOUNT_MEDIA_DIR, exist_ok=True)
os.makedirs(OBJECTCOUNT_OUTPUTS_DIR, exist_ok=True)

class ObjectCountService:
    def __init__(self, db: AsyncSession):
        self.repo = ObjectCountRepository(db)
        self.db = db

    async def upload_media(
        self,
        files: List[UploadFile],
        media_type: str,
        tenant_id: uuid.UUID
    ) -> List[ObjectCountMedia]:
        """
        Uploads photos or videos for object counting, saves them to disk, 
        and creates a DB record with 'pending' status.
        """
        results = []
        for file in files:
            if file.filename:
                # Smart Deduplication: Check if filename already exists for this tenant
                existing = await self.repo.get_media_by_filename(file.filename, tenant_id)
                if existing:
                    if existing.status in {"completed", "processing"}:
                        raise HTTPException(
                            status_code=status.HTTP_400_BAD_REQUEST,
                            detail=f"A video or photo with the filename '{file.filename}' has already been uploaded."
                        )
                    else:
                        # Failed or pending status, delete old record & physical files and re-process
                        if existing.filepath and os.path.exists(existing.filepath):
                            try:
                                os.remove(existing.filepath)
                            except Exception:
                                pass
                        if existing.processed_filepath and os.path.exists(existing.processed_filepath):
                            try:
                                os.remove(existing.processed_filepath)
                            except Exception:
                                pass
                        await self.db.delete(existing)
                        await self.db.flush()

            # Save media file
            file_ext = os.path.splitext(file.filename)[1].lower() if file.filename else ".mp4"
            unique_name = f"{uuid.uuid4()}{file_ext}"
            filepath = os.path.join(OBJECTCOUNT_MEDIA_DIR, unique_name)
            
            content = await file.read()

            if media_type == 'photo':
                # convert_and_save_image handles HEIC→JPEG automatically
                filepath = convert_and_save_image(content, file.filename or unique_name, OBJECTCOUNT_MEDIA_DIR)
                # Update filename if extension changed (e.g. .heic -> .jpg)
                stored_filename = os.path.splitext(file.filename or unique_name)[0] + os.path.splitext(filepath)[1]
            else:
                # Videos: save as-is
                filepath = os.path.join(OBJECTCOUNT_MEDIA_DIR, unique_name)
                with open(filepath, "wb") as f:
                    f.write(content)
                stored_filename = file.filename or unique_name

            # Create media record in DB
            media = await self.repo.create_media(
                tenant_id=tenant_id,
                filename=stored_filename,
                filepath=filepath,
                media_type=media_type
            )
            await self.db.commit()
            results.append(media)
        return results

    async def trigger_analysis(
        self,
        media_id: uuid.UUID,
        tenant_id: uuid.UUID,
        configs: ObjectCountAnalyzeRequest
    ) -> ObjectCountMedia:
        """
        Clears previous results, updates analysis configuration, transition status to 'processing',
        and schedules a background Celery task.
        """
        media = await self.repo.get_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media record not found or access denied."
            )

        # Clear any old results/outputs from a previous run
        await self.repo.clear_results_by_media_id(media_id)
        
        # Cleanup old processed video file if it exists
        if media.processed_filepath and os.path.exists(media.processed_filepath):
            try:
                os.remove(media.processed_filepath)
            except Exception:
                pass
                
        # Update details
        await self.repo.update_media_results(
            media_id=media_id,
            status="processing",
            total_objects_count=None,
            peak_objects_count=None,
            average_objects_count=None,
            video_duration_seconds=None,
            processed_filepath=None,
            classify_gender=configs.classify_gender,
            classify_vehicle=configs.classify_vehicle,
            classes_to_track=configs.classes_to_track,
            report_summary=None
        )
        # Clear any old progress from Redis
        from database.redis import get_redis_client
        redis_client = get_redis_client()
        if redis_client:
            try:
                await redis_client.delete(f"objectcount:progress:{media_id}")
            except Exception:
                pass
        await self.db.commit()

        # Trigger background tracking Celery task
        try:
            from modules.objectcount.tasks import index_objectcount_task
            index_objectcount_task.delay(
                str(media.id),
                media.filepath,
                media.media_type,
                configs.model_dump()
            )
        except Exception as e:
            await self.repo.update_media_status(media.id, "failed")
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to submit object tracking task: {str(e)}"
            )

        # Eager load updated object
        return await self.repo.get_media_by_id(media_id, tenant_id)

    async def get_all_media(self, tenant_id: uuid.UUID) -> List[ObjectCountMedia]:
        media_list = await self.repo.get_all_media(tenant_id)
        from database.redis import get_redis_client
        redis_client = get_redis_client()
        for media in media_list:
            progress = 0
            if media.status == "completed":
                progress = 100
            elif media.status == "failed":
                progress = 0
            elif media.status == "processing":
                if redis_client:
                    try:
                        val = await redis_client.get(f"objectcount:progress:{media.id}")
                        if val is not None:
                            progress = int(val)
                    except Exception:
                        progress = 0
            media.progress_percentage = progress
        return media_list

    async def get_media_detail(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> ObjectCountMedia:
        media = await self.repo.get_media_with_results(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media record not found or access denied."
            )
        from database.redis import get_redis_client
        redis_client = get_redis_client()
        progress = 0
        if media.status == "completed":
            progress = 100
        elif media.status == "failed":
            progress = 0
        elif media.status == "processing":
            if redis_client:
                try:
                    val = await redis_client.get(f"objectcount:progress:{media_id}")
                    if val is not None:
                        progress = int(val)
                except Exception:
                    progress = 0
        media.progress_percentage = progress
        return media

    async def get_media_results(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> List[ObjectCountResult]:
        # Validate media exists first
        media = await self.repo.get_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media record not found or access denied."
            )
        return await self.repo.get_results_by_media_id(media_id, tenant_id)

    async def delete_media(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        media = await self.repo.get_media_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media record not found or access denied."
            )
        
        # Physical cleanup of raw and processed files
        if media.filepath and os.path.exists(media.filepath):
            try:
                os.remove(media.filepath)
            except Exception:
                pass
        if media.processed_filepath and os.path.exists(media.processed_filepath):
            try:
                os.remove(media.processed_filepath)
            except Exception:
                pass

        await self.repo.delete_media(media_id, tenant_id)
        await self.db.commit()
