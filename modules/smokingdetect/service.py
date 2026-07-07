import os
import uuid
import shutil
from typing import List, Optional

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.smokingdetect.repository import SmokingDetectRepository
from modules.smokingdetect.model import SmokingSession, SmokingEvent
from modules.gallery.repository import GalleryRepository

SMOKING_DETECTION_DIR = os.path.join("storage", "smoking_detection")
os.makedirs(SMOKING_DETECTION_DIR, exist_ok=True)

class SmokingDetectService:
    def __init__(self, db: AsyncSession):
        self.repo = SmokingDetectRepository(db)
        self.gallery_repo = GalleryRepository(db)
        self.db = db

    async def trigger_analysis(
        self,
        gallery_media_id: uuid.UUID,
        interval: float,
        tenant_id: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> SmokingSession:
        """
        Creates a SmokingSession row in 'pending' status referencing a gallery media item,
        and dispatches a Celery task for background analysis.
        """
        # Validate that the gallery media file exists and belongs to this tenant
        tenant_uuid = uuid.UUID(tenant_id)
        gallery_media = await self.gallery_repo.get_media_by_id(gallery_media_id, tenant_uuid)
        if not gallery_media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gallery media record not found or access denied."
            )

        # --- Create DB session record ---
        session = await self.repo.create_session(
            db=self.db,
            user_id=user_id,
            tenant_id=tenant_id,
            gallery_media_id=gallery_media_id,
            interval=interval,
        )
        await self.db.commit()

        # --- Dispatch Celery background task ---
        try:
            from modules.smokingdetect.tasks import run_smoking_analysis

            run_smoking_analysis.delay(
                str(session.id),
                gallery_media.filepath,
                interval,
            )
        except Exception as exc:
            # If task dispatch itself fails, mark the session failed so the
            # frontend does not poll forever.
            await self.repo.update_session_status(session.id, "failed")
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to dispatch analysis task: {exc}",
            )

        # Reload to include the (empty) events relationship
        loaded = await self.repo.get_session_with_events(session.id, tenant_id)
        return loaded or session

    async def get_session_status(
        self,
        session_id: uuid.UUID,
        tenant_id: str,
    ) -> SmokingSession:
        """Fetch session with its events for the polling/status endpoint."""
        session = await self.repo.get_session_with_events(session_id, tenant_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Smoking detection session not found or unauthorized access.",
            )
        return session

    async def get_session_events(
        self,
        session_id: uuid.UUID,
        tenant_id: str,
    ) -> List[SmokingEvent]:
        """Verify tenant ownership, then return all events for the session."""
        session = await self.repo.get_session(session_id, tenant_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Smoking detection session not found or unauthorized access.",
            )
        return await self.repo.get_session_events(session_id)

    async def get_sessions_history(
        self,
        tenant_id: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> List[SmokingSession]:
        """
        Return sessions for the tenant. Pass user_id to restrict to
        operator/viewer's own sessions; leave None for admin/superadmin.
        """
        return await self.repo.get_sessions_history(tenant_id, user_id)

    def get_video_path(
        self,
        session: SmokingSession,
    ) -> str:
        """Return the annotated video path or raise 404 if not yet available."""
        if not session.video_out_path or not os.path.exists(session.video_out_path):
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Annotated video is not yet available for this session.",
            )
        return session.video_out_path

    async def delete_session(
        self,
        session_id: uuid.UUID,
        tenant_id: str,
    ) -> None:
        """Deletes smoking detection session record, associated events, and physical files."""
        session = await self.repo.get_session(session_id, tenant_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Smoking detection session not found or unauthorized access.",
            )

        # Remove the session's results directory (contains annotated video and frames)
        session_id_str = str(session_id)
        output_dir = os.path.join(SMOKING_DETECTION_DIR, session_id_str)
        if os.path.exists(output_dir):
            try:
                shutil.rmtree(output_dir)
            except Exception:
                pass

        await self.repo.delete_session(session_id, tenant_id)
        await self.db.commit()
