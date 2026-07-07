import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, status, HTTPException
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
    "/process",
    response_model=StandardResponse[ActivityMediaResponse],
    status_code=status.HTTP_200_OK
)
async def process_activity_media(
    payload: ActivityProcessPayload,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Triggers/re-triggers frame-by-frame activity detection models on a gallery media item by its gallery_media_id.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    media = await service.process_activity_media(payload.gallery_media_id, tenant_id, payload)
    return StandardResponse(
        message="Activity detection tracking started successfully.",
        status=status.HTTP_200_OK,
        data=ActivityMediaResponse.model_validate(media)
    )


@router.get(
    "/process/{gallery_media_id}",
    response_model=StandardResponse[ActivityProcessStatusResponse],
    status_code=status.HTTP_200_OK
)
async def get_process_status(
    gallery_media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the current execution status and active configuration details of the media file process.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    status_dict = await service.get_process_status(gallery_media_id, tenant_id)
    return StandardResponse(
        message="Activity process status and configuration retrieved successfully.",
        status=status.HTTP_200_OK,
        data=ActivityProcessStatusResponse.model_validate(status_dict)
    )


@router.get(
    "/process/{gallery_media_id}/history",
    response_model=StandardResponse[List[ActivityAlertResponse]],
    status_code=status.HTTP_200_OK
)
async def get_process_history(
    gallery_media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the history of all detected alerts/violations generated during the media analysis process.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    history = await service.get_process_history(gallery_media_id, tenant_id)
    
    history_data = [ActivityAlertResponse.model_validate(h) for h in history]
    return StandardResponse(
        message="Activity process history retrieved successfully.",
        status=status.HTTP_200_OK,
        data=history_data
    )


@router.get(
    "/report",
    response_model=StandardResponse[List[ActivityAlertResponse]],
    status_code=status.HTTP_200_OK
)
async def get_alerts_report(
    gallery_media_id: Optional[uuid.UUID] = None,
    activity_type: Optional[str] = None,
    severity: Optional[str] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves safety or theft alerts for the active tenant. Can filter by gallery media source, alert type, and severity.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    alerts = await service.get_alerts_report(
        tenant_id=tenant_id,
        gallery_media_id=gallery_media_id,
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
    gallery_media_id: Optional[uuid.UUID] = None,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Generates summary aggregated statistics of all safety/intrusion alerts scoped to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    service = ActivityService(db)
    summary_data = await service.get_alerts_summary(tenant_id=tenant_id, gallery_media_id=gallery_media_id)
    
    return StandardResponse(
        message="Activity summary report statistics compiled successfully.",
        status=status.HTTP_200_OK,
        data=ActivityAlertSummary.model_validate(summary_data)
    )
