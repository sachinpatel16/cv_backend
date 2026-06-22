import os
import uuid
from typing import List, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from modules.peoplecount.repository import PeopleCountRepository
from modules.peoplecount.model import PeopleCountMedia, PeopleCountResult

PEOPLECOUNT_MEDIA_DIR = os.path.join("storage", "peoplecount_media")
PEOPLECOUNT_OUTPUTS_DIR = os.path.join("storage", "peoplecount_outputs")

os.makedirs(PEOPLECOUNT_MEDIA_DIR, exist_ok=True)
os.makedirs(PEOPLECOUNT_OUTPUTS_DIR, exist_ok=True)

class PeopleCountService:
    def __init__(self, db: AsyncSession):
        self.repo = PeopleCountRepository(db)
        self.db = db

    async def upload_and_process_media(
        self,
        files: List[UploadFile],
        media_type: str,
        tenant_id: uuid.UUID,
        min_track_frames: int = 300,
        track_buffer: int = 150,
        confidence_threshold: float = 0.35
    ) -> List[PeopleCountMedia]:
        """
        Uploads photos or videos for people counting, saves them, and schedules a Celery task.
        """
        results = []
        for file in files:
            # Deduplicate by filename
            existing = await self.repo.get_media_by_filename(file.filename, tenant_id)
            if existing:
                if existing.status in {"completed", "processing"}:
                    results.append(existing)
                    continue
                else:
                    # Cleanup old failed/pending file and DB record
                    if os.path.exists(existing.filepath):
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
            file_ext = os.path.splitext(file.filename)[1].lower()
            unique_name = f"{uuid.uuid4()}{file_ext}"
            filepath = os.path.join(PEOPLECOUNT_MEDIA_DIR, unique_name)
            
            content = await file.read()
            with open(filepath, "wb") as f:
                f.write(content)

            # Create media record in DB
            media = await self.repo.create_media(
                tenant_id=tenant_id,
                filename=file.filename or unique_name,
                filepath=filepath,
                media_type=media_type
            )
            await self.db.commit()

            # Trigger background counting tasks via Celery
            try:
                await self.repo.update_media_status(media.id, "processing")
                await self.db.commit()
                
                from workers.tasks import index_peoplecount_task
                index_peoplecount_task.delay(
                    str(media.id),
                    filepath,
                    media_type,
                    min_track_frames,
                    track_buffer,
                    confidence_threshold
                )
            except Exception as e:
                await self.repo.update_media_status(media.id, "failed")
                await self.db.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to submit people count task for {file.filename}: {str(e)}"
                )

            results.append(media)
        return results

    async def get_all_media(self, tenant_id: uuid.UUID) -> List[PeopleCountMedia]:
        return await self.repo.get_all_media(tenant_id)

    async def get_media_detail(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> PeopleCountMedia:
        media = await self.repo.get_media_with_results(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media record not found or access denied."
            )
        return media

    async def get_media_results(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> List[PeopleCountResult]:
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
        
        # Physical cleanup
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
