import uuid
from typing import List

from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import get_current_user
from modules.users.model import User
from modules.smokingdetect.service import SmokingDetectService
from modules.smokingdetect.schema import (
    SmokingSessionOut,
    SmokingEventOut,
    SmokingSessionHistoryOut,
)

router = APIRouter(prefix="/smokingdetect", tags=["Smoking Detection"])


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _verify_tenant(user: User) -> str:
    """Ensure the authenticated user belongs to a tenant; return tenant_id as str."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The active user account is not associated with any tenant namespace.",
        )
    return str(user.tenant_id)


# ---------------------------------------------------------------------------
# POST /smokingdetect/upload
# ---------------------------------------------------------------------------

@router.post(
    "/upload",
    response_model=StandardResponse[SmokingSessionOut],
    status_code=status.HTTP_202_ACCEPTED,
)
async def upload_video_for_analysis(
    file: UploadFile = File(..., description="Video file to analyse for smoking detection"),
    interval: float = Form(1.0, ge=0.1, description="Frame sampling interval in seconds (default: 1.0)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a video for background smoking detection analysis.

    Saves the video to storage, creates a session record in 'pending' status,
    and dispatches a Celery task.  Returns 202 immediately so the caller can
    poll `/sessions/{id}/status` for progress.
    """
    tenant_id = _verify_tenant(current_user)

    service = SmokingDetectService(db)
    session = await service.submit_video(
        file=file,
        interval=interval,
        tenant_id=tenant_id,
        user_id=current_user.id,
    )

    session_data = SmokingSessionOut.model_validate(session)
    return StandardResponse(
        message="Smoking detection job submitted successfully.",
        status=status.HTTP_202_ACCEPTED,
        data=session_data,
    )


# ---------------------------------------------------------------------------
# GET /smokingdetect/sessions/history
# ---------------------------------------------------------------------------

@router.get(
    "/sessions/history",
    response_model=StandardResponse[List[SmokingSessionHistoryOut]],
    status_code=status.HTTP_200_OK,
)
async def list_sessions_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve all past smoking detection sessions scoped to the caller's tenant.

    - **admin / superadmin**: sees all sessions in the tenant namespace.
    - **operator / viewer**: sees only their own sessions.
    """
    tenant_id = _verify_tenant(current_user)

    # Determine visibility scope based on role
    user_id_filter = None
    if current_user.role not in {"admin", "superadmin"}:
        user_id_filter = current_user.id

    service = SmokingDetectService(db)
    sessions = await service.get_sessions_history(tenant_id, user_id=user_id_filter)

    history_data = []
    for s in sessions:
        history_data.append(
            SmokingSessionHistoryOut(
                id=s.id,
                status=s.status,
                overall_status=s.overall_status,
                interval=s.interval,
                created_at=s.created_at,
                total_events=s.total_events,
                user=(
                    {
                        "id": s.user.id,
                        "email": s.user.email,
                        "role": s.user.role,
                    }
                    if s.user
                    else None
                ),
            )
        )

    return StandardResponse(
        message=f"Retrieved {len(history_data)} smoking detection session(s).",
        status=status.HTTP_200_OK,
        data=history_data,
    )


# ---------------------------------------------------------------------------
# GET /smokingdetect/sessions/{session_id}
# ---------------------------------------------------------------------------

@router.get(
    "/sessions/{session_id}",
    response_model=StandardResponse[List[SmokingEventOut]],
    status_code=status.HTTP_200_OK,
)
async def get_session_events(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Retrieve all detected smoking events for a completed session, ordered by timestamp.
    """
    tenant_id = _verify_tenant(current_user)

    service = SmokingDetectService(db)
    events = await service.get_session_events(session_id, tenant_id)

    events_data = [SmokingEventOut.model_validate(e) for e in events]
    return StandardResponse(
        message=f"Retrieved {len(events_data)} smoking event(s) for this session.",
        status=status.HTTP_200_OK,
        data=events_data,
    )


# ---------------------------------------------------------------------------
# GET /smokingdetect/sessions/{session_id}/status
# ---------------------------------------------------------------------------

@router.get(
    "/sessions/{session_id}/status",
    response_model=StandardResponse[SmokingSessionOut],
    status_code=status.HTTP_200_OK,
)
async def get_session_status(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Poll the processing status of a smoking detection session.

    Returns the full session object including events once the job completes.
    Use this endpoint every few seconds while `status` is `pending` or `processing`.
    """
    tenant_id = _verify_tenant(current_user)

    service = SmokingDetectService(db)
    session = await service.get_session_status(session_id, tenant_id)

    session_data = SmokingSessionOut.model_validate(session)
    return StandardResponse(
        message="Session status retrieved successfully.",
        status=status.HTTP_200_OK,
        data=session_data,
    )


# ---------------------------------------------------------------------------
# GET /smokingdetect/sessions/{session_id}/video
# ---------------------------------------------------------------------------

@router.get(
    "/sessions/{session_id}/video",
    status_code=status.HTTP_200_OK,
)
async def stream_annotated_video(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Stream the annotated output video produced by the smoking detection analysis.

    Returns a `FileResponse` pointing to the MP4 saved under `storage/smoking_detection/{session_id}/footage/`.
    The session must be in `completed` status and the video file must exist on disk.
    """
    tenant_id = _verify_tenant(current_user)

    service = SmokingDetectService(db)
    session = await service.get_session_status(session_id, tenant_id)

    if session.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Session is not yet completed (current status: {session.status}).",
        )

    video_path = service.get_video_path(session)
    return FileResponse(
        path=video_path,
        media_type="video/mp4",
        filename=f"smoking_analysis_{session_id}.mp4",
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK,
)
async def delete_smoking_session(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """
    Soft deletes a smoking detection session and its associated event records,
    and removes the annotated video/frames from disk storage.
    """
    tenant_id = _verify_tenant(current_user)

    service = SmokingDetectService(db)
    await service.delete_session(session_id, tenant_id)

    return StandardResponse(
        message="Smoking session and all associated event records deleted successfully.",
        status=status.HTTP_200_OK,
        data=None,
    )

