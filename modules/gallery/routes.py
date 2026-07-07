import uuid
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.redis import get_cached, set_cached, delete_cached
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import get_current_user
from modules.users.model import User
from modules.gallery.service import GalleryService
from modules.gallery.schema import GalleryMediaResponse

router = APIRouter(prefix="/gallery", tags=["Gallery & Media Management"])

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
    response_model=StandardResponse[List[GalleryMediaResponse]],
    status_code=status.HTTP_201_CREATED
)
async def upload_gallery_media(
    files: List[UploadFile] = File(..., description="The photos or video files to upload and catalog"),
    media_type: str = Form(..., description="Type of media file: 'photo' or 'video'"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads multiple photos or videos to the centralized gallery, scoped to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    
    if media_type not in {"photo", "video"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid media_type. Supported options are 'photo' or 'video'."
        )

    service = GalleryService(db)
    media_list = await service.upload_media_batch(files, media_type, tenant_id)
    
    # Invalidate media list cache for this tenant
    await delete_cached(f"gallery_media_list:{tenant_id}")
    
    media_data = [GalleryMediaResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Successfully uploaded {len(media_data)} media file(s) to the gallery.",
        status=status.HTTP_201_CREATED,
        data=media_data
    )

@router.get(
    "/media",
    response_model=StandardResponse[List[GalleryMediaResponse]],
    status_code=status.HTTP_200_OK
)
async def list_gallery_media(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all non-deleted gallery photos and videos scoped to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    cache_key = f"gallery_media_list:{tenant_id}"
    
    cached = await get_cached(cache_key)
    if cached is not None:
        return StandardResponse(
            message=f"Retrieved {len(cached)} gallery media sources.",
            status=status.HTTP_200_OK,
            data=[GalleryMediaResponse.model_validate(m) for m in cached]
        )
    
    service = GalleryService(db)
    media_list = await service.get_all_media_sources(tenant_id)
    
    media_data = [GalleryMediaResponse.model_validate(m) for m in media_list]
    await set_cached(cache_key, [m.model_dump(mode="json") for m in media_data], expire=3600)
    
    return StandardResponse(
        message=f"Retrieved {len(media_data)} gallery media sources.",
        status=status.HTTP_200_OK,
        data=media_data
    )

@router.get(
    "/media/{media_id}",
    response_model=StandardResponse[GalleryMediaResponse],
    status_code=status.HTTP_200_OK
)
async def get_gallery_media(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches the metadata of a specific gallery media item.
    """
    tenant_id = verify_tenant(current_user)
    service = GalleryService(db)
    media = await service.get_media_details(media_id, tenant_id)
    
    if not media:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Gallery media source not found or unauthorized access."
        )
        
    return StandardResponse(
        message="Gallery media source retrieved successfully.",
        status=status.HTTP_200_OK,
        data=GalleryMediaResponse.model_validate(media)
    )

@router.delete(
    "/media/{media_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_gallery_media(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Deletes a single media item from the gallery and removes its physical file from storage.
    """
    tenant_id = verify_tenant(current_user)
    
    service = GalleryService(db)
    await service.delete_media_source(media_id, tenant_id)
    
    # Invalidate gallery media list cache
    await delete_cached(f"gallery_media_list:{tenant_id}")
    
    return StandardResponse(
        message="Gallery media source deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )

@router.delete(
    "/media",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_all_gallery_media(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft deletes all uploaded gallery media for the active tenant namespace, and deletes files from disk.
    """
    tenant_id = verify_tenant(current_user)
    
    service = GalleryService(db)
    deleted_count = await service.delete_all_media_sources(tenant_id)
    
    # Invalidate gallery media list cache
    await delete_cached(f"gallery_media_list:{tenant_id}")
    
    return StandardResponse(
        message=f"Successfully deleted {deleted_count} gallery media file(s).",
        status=status.HTTP_200_OK,
        data=None
    )
