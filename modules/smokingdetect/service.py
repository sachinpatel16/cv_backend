import os
import uuid
import shutil
from pathlib import Path
from typing import List, Optional

from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.smokingdetect.repository import SmokingDetectRepository
from modules.smokingdetect.model import SmokingSession, SmokingEvent

# ---------------------------------------------------------------------------
# Storage directories
# ---------------------------------------------------------------------------
SMOKING_UPLOADS_DIR = os.path.join("storage", "smoking_uploads")
SMOKING_DETECTION_DIR = os.path.join("storage", "smoking_detection")

os.makedirs(SMOKING_UPLOADS_DIR, exist_ok=True)
os.makedirs(SMOKING_DETECTION_DIR, exist_ok=True)

# ---------------------------------------------------------------------------
# Singleton SmokingDetector — loaded once at import time so the heavy model
# weights are only read from disk once, not per-request.
# ---------------------------------------------------------------------------
try:
    from services.ai.smoking_detector import SmokingDetector  # type: ignore

    smoking_detector = SmokingDetector(
        person_model_path="trained-models/yolov8n.pt",
        cig_model_path="trained-models/cigarette.pt",
    )
    print("[SmokingDetect] SmokingDetector loaded successfully.")
except Exception as _exc:  # noqa: BLE001
    # Allow the application to start even if the model weights are missing
    # (e.g. in CI/CD or staging without GPU).  Requests will still fail
    # gracefully inside the Celery task.
    smoking_detector = None  # type: ignore
    print(f"[SmokingDetect] WARNING: SmokingDetector could not be loaded: {_exc}")


class SmokingDetectService:
    def __init__(self, db: AsyncSession):
        self.repo = SmokingDetectRepository(db)
        self.db = db

    # ------------------------------------------------------------------
    # Public service methods
    # ------------------------------------------------------------------

    async def submit_video(
        self,
        file: UploadFile,
        interval: float,
        tenant_id: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> SmokingSession:
        """
        Saves the uploaded video to disk, creates a SmokingSession row in
        'pending' status, and dispatches a Celery task for background analysis.
        Returns immediately with the session so the caller can respond 202.
        """
        # --- Save video file ---
        file_ext = os.path.splitext(file.filename or "video.mp4")[1].lower() or ".mp4"
        unique_name = f"{uuid.uuid4()}{file_ext}"
        video_path = os.path.join(SMOKING_UPLOADS_DIR, unique_name)

        content = await file.read()
        with open(video_path, "wb") as f:
            f.write(content)

        # --- Create DB session record ---
        session = await self.repo.create_session(
            db=self.db,
            user_id=user_id,
            tenant_id=tenant_id,
            media_id=None,
            interval=interval,
        )
        await self.db.commit()

        # --- Dispatch Celery background task ---
        try:
            from modules.smokingdetect.tasks import run_smoking_analysis

            run_smoking_analysis.delay(
                str(session.id),
                video_path,
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
        Return sessions for the tenant.  Pass user_id to restrict to
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

