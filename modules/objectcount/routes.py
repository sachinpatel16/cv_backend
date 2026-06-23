import uuid
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import get_current_user
from modules.users.model import User
from modules.objectcount.service import ObjectCountService
from modules.objectcount.schema import (
    ObjectCountMediaResponse,
    ObjectCountMediaDetailResponse,
    ObjectCountResultResponse,
    ObjectCountAnalyzeRequest
)

router = APIRouter(prefix="/objectcount", tags=["Generic Object Count & Tracking"])

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
    response_model=StandardResponse[List[ObjectCountMediaResponse]],
    status_code=status.HTTP_201_CREATED
)
async def upload_object_media(
    files: List[UploadFile] = File(..., description="The photo(s) or video file(s) to upload"),
    media_type: str = Form(..., description="Type of media file: 'photo' or 'video'"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads photos/videos and saves them. Media is initially in 'pending' status until analyze is triggered.
    """
    tenant_id = verify_tenant(current_user)
    
    if media_type not in {"photo", "video"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid media_type. Supported options are 'photo' or 'video'."
        )

    service = ObjectCountService(db)
    media_list = await service.upload_media(
        files=files,
        media_type=media_type,
        tenant_id=tenant_id
    )
    
    media_data = [ObjectCountMediaResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Successfully uploaded {len(media_data)} media file(s).",
        status=status.HTTP_201_CREATED,
        data=media_data
    )

@router.post(
    "/media/{media_id}/analyze",
    response_model=StandardResponse[ObjectCountMediaResponse],
    status_code=status.HTTP_200_OK
)
async def analyze_object_media(
    media_id: uuid.UUID,
    configs: ObjectCountAnalyzeRequest,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Triggers object tracking and classification on the previously uploaded media.
    """
    tenant_id = verify_tenant(current_user)
    service = ObjectCountService(db)
    media = await service.trigger_analysis(
        media_id=media_id,
        tenant_id=tenant_id,
        configs=configs
    )
    
    media_data = ObjectCountMediaResponse.model_validate(media)
    return StandardResponse(
        message="Object tracking and classification analysis triggered successfully.",
        status=status.HTTP_200_OK,
        data=media_data
    )

@router.get(
    "/media",
    response_model=StandardResponse[List[ObjectCountMediaResponse]],
    status_code=status.HTTP_200_OK
)
async def list_objectcount_media(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all object count media items scoped to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    
    service = ObjectCountService(db)
    media_list = await service.get_all_media(tenant_id)
    
    media_data = [ObjectCountMediaResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Retrieved {len(media_data)} media items.",
        status=status.HTTP_200_OK,
        data=media_data
    )

@router.get(
    "/media/{media_id}",
    response_model=StandardResponse[ObjectCountMediaDetailResponse],
    status_code=status.HTTP_200_OK
)
async def get_objectcount_media_detail(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves detailed metrics and status of an object count media, including track results.
    """
    tenant_id = verify_tenant(current_user)
    
    service = ObjectCountService(db)
    media = await service.get_media_detail(media_id, tenant_id)
    
    media_data = ObjectCountMediaDetailResponse.model_validate(media)
    return StandardResponse(
        message="Object count media details retrieved successfully.",
        status=status.HTTP_200_OK,
        data=media_data
    )

@router.get(
    "/media/{media_id}/results",
    response_model=StandardResponse[List[ObjectCountResultResponse]],
    status_code=status.HTTP_200_OK
)
async def get_objectcount_results(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the track summaries and visibility durations of all objects counted.
    """
    tenant_id = verify_tenant(current_user)
    
    service = ObjectCountService(db)
    results = await service.get_media_results(media_id, tenant_id)
    
    results_data = [ObjectCountResultResponse.model_validate(r) for r in results]
    return StandardResponse(
        message=f"Retrieved {len(results_data)} track result(s) for this media.",
        status=status.HTTP_200_OK,
        data=results_data
    )

@router.delete(
    "/media/{media_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_objectcount_media(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft-deletes an object count media record and physically cleans up its files.
    """
    tenant_id = verify_tenant(current_user)
    
    service = ObjectCountService(db)
    await service.delete_media(media_id, tenant_id)
    
    return StandardResponse(
        message="Object count media and associated tracking results deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )
