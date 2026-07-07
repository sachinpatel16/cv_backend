import uuid
import os
import datetime
from typing import List, Optional
from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import require_admin, require_viewer
from modules.users.model import User
from modules.employees.service import EmployeeService
from modules.employees.schema import EmployeeResponse, EmployeeAttendanceResponse, EmployeeProcessVideosRequest, GroupPhotoAttendanceResponse, UploadedPhotoResponse, EmployeePhotoProcessRequest
from modules.peopleanalytics.schema import UploadedVideoResponse, PeopleAnalyticsSessionResponse


router = APIRouter(prefix="/employees", tags=["Employee Registry"])


def verify_tenant(user: User) -> uuid.UUID:
    """Helper to verify and return the tenant_id from the authenticated user."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The active user account is not associated with any tenant namespace."
        )
    return user.tenant_id


@router.post(
    "",
    response_model=StandardResponse[EmployeeResponse],
    status_code=status.HTTP_201_CREATED
)
async def register_new_employee(
    first_name: str = Form(..., description="Employee first name"),
    last_name: str = Form(..., description="Employee last name"),
    employee_code: str = Form(..., description="Unique employee identifier code"),
    file: UploadFile = File(..., description="Registration picture of the employee"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Registers a new employee, uploads their picture, extracts visual ReID embeddings, and stores them.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    employee = await service.register_employee(
        tenant_id=tenant_id,
        first_name=first_name,
        last_name=last_name,
        employee_code=employee_code,
        file=file
    )
    return StandardResponse(
        message="Employee registered successfully.",
        status=status.HTTP_201_CREATED,
        data=EmployeeResponse.model_validate(employee)
    )


@router.get(
    "",
    response_model=StandardResponse[List[EmployeeResponse]],
    status_code=status.HTTP_200_OK
)
async def list_employees(
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists all active registered employees in the tenant namespace.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    employees = await service.get_all_employees(tenant_id)
    return StandardResponse(
        message=f"Successfully retrieved {len(employees)} employee(s).",
        status=status.HTTP_200_OK,
        data=[EmployeeResponse.model_validate(e) for e in employees]
    )


@router.get(
    "/attendance",
    response_model=StandardResponse[List[EmployeeAttendanceResponse]],
    status_code=status.HTTP_200_OK
)
async def get_attendance_by_date_range(
    start_date: datetime.date,
    end_date: datetime.date,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all employee attendance logs within a specific date range.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    logs = await service.get_attendance_by_date_range(tenant_id, start_date, end_date)
    return StandardResponse(
        message=f"Retrieved {len(logs)} attendance logs between {start_date} and {end_date}.",
        status=status.HTTP_200_OK,
        data=[EmployeeAttendanceResponse.model_validate(l) for l in logs]
    )


@router.get(
    "/{employee_id}",
    response_model=StandardResponse[EmployeeResponse],
    status_code=status.HTTP_200_OK
)
async def get_employee_details(
    employee_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches the profile details of a single employee.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    employee = await service.get_employee(employee_id, tenant_id)
    return StandardResponse(
        message="Employee details retrieved.",
        status=status.HTTP_200_OK,
        data=EmployeeResponse.model_validate(employee)
    )


@router.put(
    "/{employee_id}",
    response_model=StandardResponse[EmployeeResponse],
    status_code=status.HTTP_200_OK
)
async def update_employee_profile(
    employee_id: uuid.UUID,
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    employee_code: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates employee profile details. Re-extracts visual embeddings if a new photo file is provided.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    employee = await service.update_employee(
        employee_id=employee_id,
        tenant_id=tenant_id,
        first_name=first_name,
        last_name=last_name,
        employee_code=employee_code,
        file=file
    )
    return StandardResponse(
        message="Employee profile updated successfully.",
        status=status.HTTP_200_OK,
        data=EmployeeResponse.model_validate(employee)
    )


@router.delete(
    "/{employee_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_employee(
    employee_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft deletes an employee and removes their profile image from storage.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    await service.delete_employee(employee_id, tenant_id)
    return StandardResponse(
        message="Employee profile deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )


@router.get(
    "/sessions/{session_id}/attendance",
    response_model=StandardResponse[List[EmployeeAttendanceResponse]],
    status_code=status.HTTP_200_OK
)
async def get_session_employee_attendance(
    session_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the Employee Attendance check-in report computed during the video analysis.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    logs = await service.get_session_attendance(session_id, tenant_id)
    return StandardResponse(
        message=f"Retrieved {len(logs)} attendance logs.",
        status=status.HTTP_200_OK,
        data=[EmployeeAttendanceResponse.model_validate(l) for l in logs]
    )


@router.post(
    "/attendance/photo/process",
    response_model=StandardResponse[GroupPhotoAttendanceResponse],
    status_code=status.HTTP_200_OK
)
async def mark_group_photo_attendance(
    request: EmployeePhotoProcessRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Detects employees in an uploaded group photo and logs check-in records day-wise.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    logs, annotated_image_path, session_id = await service.process_group_photo_attendance(
        tenant_id=tenant_id,
        user_id=current_user.id,
        gallery_media_id=request.gallery_media_id,
        similarity_threshold=request.similarity_threshold or 0.85,
        confidence_threshold=request.confidence_threshold or 0.3
    )
    
    attendance_logs = [EmployeeAttendanceResponse.model_validate(l) for l in logs]
        
    return StandardResponse(
        message=f"Attendance marked for {len(logs)} employee(s).",
        status=status.HTTP_200_OK,
        data=GroupPhotoAttendanceResponse(
            session_id=session_id,
            annotated_image_path=annotated_image_path,
            attendance_logs=attendance_logs
        )
    )


@router.get(
    "/attendance/photo/uploads",
    response_model=StandardResponse[List[UploadedPhotoResponse]],
    status_code=status.HTTP_200_OK
)
async def list_attendance_photo_uploads(
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all group photo files uploaded by the active tenant for employee photo attendance.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    photos = await service.get_uploaded_photos(tenant_id)
    return StandardResponse(
        message=f"Successfully retrieved {len(photos)} uploaded photo(s).",
        status=status.HTTP_200_OK,
        data=[UploadedPhotoResponse.model_validate(p) for p in photos]
    )


@router.delete(
    "/attendance/photo/sessions/{session_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_attendance_photo_session(
    session_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes the group photo attendance session run record.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    await service.delete_uploaded_photo(session_id, tenant_id)
    return StandardResponse(
        message="Attendance session run deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )


@router.post(
    "/attendance/video/process",
    response_model=StandardResponse[List[PeopleAnalyticsSessionResponse]],
    status_code=status.HTTP_202_ACCEPTED
)
async def process_attendance_videos(
    request: EmployeeProcessVideosRequest,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Spawns Celery tracking runs for standalone employee video attendance logs.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    sessions = await service.create_and_start_attendance_sessions(
        tenant_id=tenant_id,
        videos=request.videos,
        global_similarity_threshold=0.85,
        global_confidence_threshold=0.3,
        user_id=current_user.id
    )
    return StandardResponse(
        message=f"Successfully registered and started processing for {len(sessions)} session(s).",
        status=status.HTTP_202_ACCEPTED,
        data=[PeopleAnalyticsSessionResponse.model_validate(s) for s in sessions]
    )



@router.get(
    "/attendance/video/sessions",
    response_model=StandardResponse[List[PeopleAnalyticsSessionResponse]],
    status_code=status.HTTP_200_OK
)
async def list_attendance_sessions(
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all video attendance session runs created by the user.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    sessions = await service.list_attendance_sessions(tenant_id, current_user.id)
    return StandardResponse(
        message=f"Retrieved {len(sessions)} session(s).",
        status=status.HTTP_200_OK,
        data=[PeopleAnalyticsSessionResponse.model_validate(s) for s in sessions]
    )


@router.get(
    "/attendance/video/sessions/{session_id}",
    response_model=StandardResponse[PeopleAnalyticsSessionResponse],
    status_code=status.HTTP_200_OK
)
async def get_attendance_session_details(
    session_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Queries execution metrics and state for a video attendance session.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    session = await service.get_attendance_session(session_id, tenant_id)
    return StandardResponse(
        message="Session details retrieved successfully.",
        status=status.HTTP_200_OK,
        data=PeopleAnalyticsSessionResponse.model_validate(session)
    )


@router.get(
    "/attendance/video/sessions/{session_id}/video",
    status_code=status.HTTP_200_OK
)
async def stream_attendance_annotated_video(
    session_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Streams or downloads the annotated output MP4 containing employee track boundaries.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    session = await service.get_attendance_session(session_id, tenant_id)
    
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

    from fastapi.responses import FileResponse
    file_ext = os.path.splitext(session.output_video_path)[1].lower()
    media_type = "image/jpeg" if file_ext == ".jpg" else "video/mp4"

    return FileResponse(
        path=session.output_video_path,
        media_type=media_type,
        filename=f"{session_id}{file_ext}"
    )

