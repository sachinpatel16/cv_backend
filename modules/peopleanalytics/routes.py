import os
import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, UploadFile, status, HTTPException
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import require_admin, require_viewer
from modules.users.model import User
from modules.peopleanalytics.service import PeopleAnalyticsService
from modules.peopleanalytics.schema import (
    PeopleAnalyticsSessionResponse,
    VisitorAnalyticsReport,
    UploadedVideoResponse,
    ProcessVideosRequest,
    SessionDetectedPerson
)

router = APIRouter(prefix="/peopleanalytics", tags=["CCTV People Analytics & Attendance"])


def verify_tenant(user: User) -> uuid.UUID:
    """Helper to verify and return the tenant_id from the authenticated user."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The active user account is not associated with any tenant namespace."
        )
    return user.tenant_id


# ==========================================
# CCTV MULTIPART UPLOADS & JOB RUNNING
# ==========================================

@router.post(
    "/upload",
    response_model=StandardResponse[List[UploadedVideoResponse]],
    status_code=status.HTTP_202_ACCEPTED
)
async def upload_batch_cctv_footage(
    files: List[UploadFile] = File(..., description="Select up to 10 video files to upload"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads up to 10 CCTV videos in a batch, saves them on disk, and records their metadata.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    details = await service.upload_video_files(
        tenant_id=tenant_id,
        files=files,
        user_id=current_user.id
    )
    return StandardResponse(
        message=f"Successfully uploaded {len(details)} video file(s).",
        status=status.HTTP_202_ACCEPTED,
        data=[UploadedVideoResponse.model_validate(d) for d in details]
    )


@router.get(
    "/uploads",
    response_model=StandardResponse[List[UploadedVideoResponse]],
    status_code=status.HTTP_200_OK
)
async def list_uploaded_videos(
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all video files uploaded by the active tenant.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    videos = await service.get_all_uploaded_videos(tenant_id)
    return StandardResponse(
        message=f"Successfully retrieved {len(videos)} uploaded video(s).",
        status=status.HTTP_200_OK,
        data=[UploadedVideoResponse.model_validate(v) for v in videos]
    )


@router.delete(
    "/uploads/{video_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_uploaded_video(
    video_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes the uploaded video metadata from database and physically removes the file from disk.
    Access is granted to the user who uploaded the video or any tenant admin.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    await service.delete_uploaded_video(video_id, tenant_id, current_user)
    return StandardResponse(
        message="Uploaded video and physical file deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )


@router.post(
    "/process",
    response_model=StandardResponse[List[PeopleAnalyticsSessionResponse]],
    status_code=status.HTTP_202_ACCEPTED
)
async def process_batch_sessions(
    request: ProcessVideosRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Registers database sessions and initiates background Celery tasks to process
    tracking, crossings, and attendance for a list of uploaded CCTV videos.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    sessions = await service.create_and_start_sessions(
        tenant_id=tenant_id,
        videos=request.videos,
        global_line_start=request.line_start,
        global_line_end=request.line_end,
        global_similarity_threshold=request.similarity_threshold,
        global_confidence_threshold=request.confidence_threshold,
        user_id=current_user.id
    )
    return StandardResponse(
        message=f"Successfully registered and started processing for {len(sessions)} session(s).",
        status=status.HTTP_202_ACCEPTED,
        data=[PeopleAnalyticsSessionResponse.model_validate(s) for s in sessions]
    )


@router.get(
    "/sessions",
    response_model=StandardResponse[List[PeopleAnalyticsSessionResponse]],
    status_code=status.HTTP_200_OK
)
async def list_analytics_sessions(
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all video analytics runs scoped to the active tenant.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    sessions = await service.get_all_sessions(tenant_id)
    return StandardResponse(
        message=f"Retrieved {len(sessions)} session(s).",
        status=status.HTTP_200_OK,
        data=[PeopleAnalyticsSessionResponse.model_validate(s) for s in sessions]
    )


@router.get(
    "/sessions/{session_id}",
    response_model=StandardResponse[PeopleAnalyticsSessionResponse],
    status_code=status.HTTP_200_OK
)
async def get_session_details(
    session_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves execution metrics and timeline charts data for a specific session.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    session = await service.get_session(session_id, tenant_id)
    return StandardResponse(
        message="Session details retrieved successfully.",
        status=status.HTTP_200_OK,
        data=PeopleAnalyticsSessionResponse.model_validate(session)
    )


@router.get(
    "/sessions/{session_id}/people",
    response_model=StandardResponse[List[SessionDetectedPerson]],
    status_code=status.HTTP_200_OK
)
async def get_session_detected_people(
    session_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the unique people (both employees and visitor identity crops) detected during analysis of a session.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    people = await service.get_session_detected_people(session_id, tenant_id)
    return StandardResponse(
        message=f"Successfully retrieved {len(people)} detected person(s).",
        status=status.HTTP_200_OK,
        data=people
    )



@router.get(
    "/sessions/{session_id}/video",
    status_code=status.HTTP_200_OK
)
async def stream_annotated_video(
    session_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Streams or downloads the output annotated video file containing boxes, counts, HUD, and crossing lines.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    session = await service.get_session(session_id, tenant_id)
    
    if session.status != "completed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Video cannot be retrieved. Session status is currently '{session.status}'."
        )
    if not session.output_video_path or not os.path.exists(session.output_video_path):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Annotated video file is missing or not generated on disk."
        )

    # Determine media type for response (image vs video)
    file_ext = os.path.splitext(session.output_video_path)[1].lower()
    media_type = "image/jpeg" if file_ext == ".jpg" else "video/mp4"

    return FileResponse(
        path=session.output_video_path,
        media_type=media_type,
        filename=f"{session_id}{file_ext}"
    )


@router.delete(
    "/sessions/{session_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_analytics_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes the session and physically wipes its input and output video files from disk.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    await service.delete_session(session_id, tenant_id)
    return StandardResponse(
        message="Analytics session and physical video files deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )


@router.get(
    "/visitors",
    response_model=StandardResponse[VisitorAnalyticsReport],
    status_code=status.HTTP_200_OK
)
async def get_cross_video_visitor_analytics(
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Aggregates visitor suite analytics across all sessions (total unique visitors, repeat visit rate, new visitors).
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    report = await service.get_visitor_dashboard(tenant_id)
    return StandardResponse(
        message="Cross-video visitor analytics calculated successfully.",
        status=status.HTTP_200_OK,
        data=report
    )
