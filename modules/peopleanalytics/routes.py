import uuid
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, status, HTTPException
from fastapi.responses import FileResponse
import os
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import require_admin, require_viewer
from modules.users.model import User
from modules.peopleanalytics.service import PeopleAnalyticsService
from modules.peopleanalytics.schema import (
    PeopleAnalyticsSessionResponse,
    VisitorAnalyticsReport,
    ProcessVideosRequest,
    SessionDetectedPerson,
    VisitorAttendanceResponse
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
# ANALYSIS SESSION MANAGEMENT
# ==========================================

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
    tracking, crossings, and attendance for a list of gallery media items.
    Each video item must supply a valid gallery_media_id from the shared gallery.
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
    Deletes the session and physically wipes its output video file from disk.
    The source gallery media file is NOT deleted — manage raw files via the gallery module.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    await service.delete_session(session_id, tenant_id)
    return StandardResponse(
        message="Analytics session and output video files deleted successfully.",
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


@router.get(
    "/visitors/attendance",
    response_model=StandardResponse[List[VisitorAttendanceResponse]],
    status_code=status.HTTP_200_OK
)
async def get_visitor_attendance_by_date_range(
    start_date: datetime.date,
    end_date: datetime.date,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all visitor attendance logs within a specific date range.
    """
    tenant_id = verify_tenant(current_user)
    service = PeopleAnalyticsService(db)
    logs = await service.get_visitor_attendance_by_date_range(tenant_id, start_date, end_date)
    return StandardResponse(
        message=f"Retrieved {len(logs)} visitor attendance logs between {start_date} and {end_date}.",
        status=status.HTTP_200_OK,
        data=[VisitorAttendanceResponse.model_validate(l) for l in logs]
    )
