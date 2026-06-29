import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import get_current_user
from modules.users.model import User
from modules.activity.service import ActivityService
from modules.activity.schema import (
    ActivityMediaResponse,
    ActivityConfigResponse,
    ActivityProcessPayload,
    ActivityProcessStatusResponse,
    ActivityAlertResponse,
    ActivityAlertSummary
)

router = APIRouter(prefix="/activity", tags=["Human Activity & Theft Detection"])


def verify_tenant(user: User) -> uuid.UUID:
    """Helper to verify and return the tenant_id from the authenticated user."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The active user account is not associated with any tenant namespace."
        )
    return user.tenant_id


@router.post(
    "/media",
    response_model=StandardResponse[List[ActivityMediaResponse]],
    status_code=status.HTTP_201_CREATED
)
async def upload_and_process_media(
    files: List[UploadFile] = File(..., description="The photos or video files to process"),
    media_type: str = Form(..., description="Type of media file: 'photo' or 'video'"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads multiple photos or videos specifically for human activity and theft tracking,
    initiating background detection alerts immediately.
    """
    tenant_id = verify_tenant(current_user)
    
    if media_type not in {"photo", "video"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid media_type. Supported options are 'photo' or 'video'."
        )

    service = ActivityService(db)
    media_list = await service.upload_activity_media(files, media_type, tenant_id)
    
    media_data = [ActivityMediaResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Successfully uploaded {len(media_data)} media source(s) and submitted tracking task.",
        status=status.HTTP_201_CREATED,
        data=media_data
    )


@router.get(
    "/media",
    response_model=StandardResponse[List[ActivityMediaResponse]],
    status_code=status.HTTP_200_OK
)
async def list_activity_media(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all non-deleted activity monitoring media uploads for the active tenant.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    media_list = await service.get_all_media_sources(tenant_id)
    
    media_data = [ActivityMediaResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Retrieved {len(media_data)} media sources.",
        status=status.HTTP_200_OK,
        data=media_data
    )


@router.get(
    "/media/{media_id}",
    response_model=StandardResponse[ActivityMediaResponse],
    status_code=status.HTTP_200_OK
)
async def get_activity_media_detail(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the details and processing status of a single activity media file.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    media = await service.repo.get_activity_media_by_id(media_id, tenant_id)
    if not media:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Activity media source not found or unauthorized access."
        )
    return StandardResponse(
        message="Activity media details retrieved successfully.",
        status=status.HTTP_200_OK,
        data=ActivityMediaResponse.model_validate(media)
    )
@router.post(
    "/media/{media_id}/process",
    response_model=StandardResponse[ActivityMediaResponse],
    status_code=status.HTTP_200_OK
)
async def process_activity_media(
    media_id: uuid.UUID,
    payload: ActivityProcessPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Triggers/re-triggers frame-by-frame activity detection models on the selected media file
    using the provided configuration settings.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    media = await service.process_activity_media(media_id, tenant_id, payload)
    return StandardResponse(
        message="Activity detection tracking started successfully.",
        status=status.HTTP_200_OK,
        data=ActivityMediaResponse.model_validate(media)
    )


@router.get(
    "/media/{media_id}/process",
    response_model=StandardResponse[ActivityProcessStatusResponse],
    status_code=status.HTTP_200_OK
)
async def get_process_status(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the current execution status and active configuration details of the media file process.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    status_dict = await service.get_process_status(media_id, tenant_id)
    return StandardResponse(
        message="Activity process status and configuration retrieved successfully.",
        status=status.HTTP_200_OK,
        data=ActivityProcessStatusResponse.model_validate(status_dict)
    )


@router.get(
    "/media/{media_id}/process/history",
    response_model=StandardResponse[List[ActivityAlertResponse]],
    status_code=status.HTTP_200_OK
)
async def get_process_history(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the history of all detected alerts/violations generated during the media analysis process.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    history = await service.get_process_history(media_id, tenant_id)
    
    history_data = [ActivityAlertResponse.model_validate(h) for h in history]
    return StandardResponse(
        message="Activity process history retrieved successfully.",
        status=status.HTTP_200_OK,
        data=history_data
    )


@router.delete(
    "/media/{media_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_activity_media(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft deletes an uploaded activity photo/video and its corresponding configurations and alert records.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    await service.delete_activity_media(media_id, tenant_id)
    
    return StandardResponse(
        message="Activity media and all associated configurations and alerts deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )
@router.get(
    "/report",
    response_model=StandardResponse[List[ActivityAlertResponse]],
    status_code=status.HTTP_200_OK
)
async def get_alerts_report(
    media_id: Optional[uuid.UUID] = None,
    activity_type: Optional[str] = None,
    severity: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves safety or theft alerts for the active tenant. Can filter by media source, alert type, and severity.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    alerts = await service.get_alerts_report(
        tenant_id=tenant_id,
        media_id=media_id,
        activity_type=activity_type,
        severity=severity
    )
    
    alerts_data = [ActivityAlertResponse.model_validate(a) for a in alerts]
    return StandardResponse(
        message=f"Retrieved {len(alerts_data)} activity alert log(s).",
        status=status.HTTP_200_OK,
        data=alerts_data
    )


@router.get(
    "/report/summary",
    response_model=StandardResponse[ActivityAlertSummary],
    status_code=status.HTTP_200_OK
)
async def get_alerts_summary(
    media_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates summary aggregated statistics of all safety/intrusion alerts scoped to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    summary_data = await service.get_alerts_summary(tenant_id=tenant_id, media_id=media_id)
    
    return StandardResponse(
        message="Activity summary report statistics compiled successfully.",
        status=status.HTTP_200_OK,
        data=ActivityAlertSummary.model_validate(summary_data)
    )
