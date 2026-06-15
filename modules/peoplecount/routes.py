import uuid
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import get_current_user
from modules.users.model import User
from modules.peoplecount.service import PeopleCountService
from modules.peoplecount.schema import (
    PeopleCountMediaResponse,
    PeopleCountMediaDetailResponse,
    PeopleCountResultResponse
)

router = APIRouter(prefix="/peoplecount", tags=["People Count & Video Tracking"])

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
    response_model=StandardResponse[List[PeopleCountMediaResponse]],
    status_code=status.HTTP_201_CREATED
)
async def upload_and_count_media(
    files: List[UploadFile] = File(..., description="The photo(s) or video file(s) to upload and perform people counting on"),
    media_type: str = Form(..., description="Type of media file: 'photo' or 'video'"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads photos/videos, saves them, and indexes people count metrics in the background.
    """
    tenant_id = verify_tenant(current_user)
    
    if media_type not in {"photo", "video"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid media_type. Supported options are 'photo' or 'video'."
        )

    service = PeopleCountService(db)
    media_list = await service.upload_and_process_media(files, media_type, tenant_id)
    
    media_data = [PeopleCountMediaResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Successfully queued {len(media_data)} media file(s) for people counting.",
        status=status.HTTP_201_CREATED,
        data=media_data
    )

@router.get(
    "/media",
    response_model=StandardResponse[List[PeopleCountMediaResponse]],
    status_code=status.HTTP_200_OK
)
async def list_peoplecount_media(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all people count media items scoped to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleCountService(db)
    media_list = await service.get_all_media(tenant_id)
    
    media_data = [PeopleCountMediaResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Retrieved {len(media_data)} media items.",
        status=status.HTTP_200_OK,
        data=media_data
    )

@router.get(
    "/media/{media_id}",
    response_model=StandardResponse[PeopleCountMediaDetailResponse],
    status_code=status.HTTP_200_OK
)
async def get_peoplecount_media_detail(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves detailed metrics and status of a people count media, including track results.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleCountService(db)
    media = await service.get_media_detail(media_id, tenant_id)
    
    media_data = PeopleCountMediaDetailResponse.model_validate(media)
    return StandardResponse(
        message="People count media details retrieved successfully.",
        status=status.HTTP_200_OK,
        data=media_data
    )

@router.get(
    "/media/{media_id}/results",
    response_model=StandardResponse[List[PeopleCountResultResponse]],
    status_code=status.HTTP_200_OK
)
async def get_peoplecount_results(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the track summaries and visibility durations of all people counted.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleCountService(db)
    results = await service.get_media_results(media_id, tenant_id)
    
    results_data = [PeopleCountResultResponse.model_validate(r) for r in results]
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
async def delete_peoplecount_media(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft-deletes a people count media record and physically cleans up its files.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleCountService(db)
    await service.delete_media(media_id, tenant_id)
    
    return StandardResponse(
        message="People count media and associated tracking results deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )
