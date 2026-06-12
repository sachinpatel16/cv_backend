import uuid
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import get_current_user
from modules.users.model import User
from modules.peoplefind.service import PeopleFindService
from modules.peoplefind.schema import (
    MediaSourceResponse,
    SearchSessionResponse,
    SearchResultResponse
)

router = APIRouter(prefix="/peoplefind", tags=["People Search & Face Recognition"])

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
    response_model=StandardResponse[List[MediaSourceResponse]],
    status_code=status.HTTP_201_CREATED
)
async def upload_and_index_event_media(
    files: List[UploadFile] = File(..., description="The event photo(s) or video file(s) to upload and index"),
    media_type: str = Form(..., description="Type of media file: 'photo' or 'video'"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads multiple photos or videos to database catalog and performs sequential 
    face extraction and embedding indexing scoped to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    
    if media_type not in {"photo", "video"}:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid media_type. Supported options are 'photo' or 'video'."
        )

    service = PeopleFindService(db)
    media_list = await service.upload_and_index_media(files, media_type, tenant_id)
    
    # Map to schema response
    media_data = [MediaSourceResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Successfully processed {len(media_data)} media file(s).",
        status=status.HTTP_201_CREATED,
        data=media_data
    )

@router.get(
    "/media",
    response_model=StandardResponse[List[MediaSourceResponse]],
    status_code=status.HTTP_200_OK
)
async def list_event_media(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves all non-deleted event photos and videos scoped to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleFindService(db)
    media_list = await service.get_all_media_sources(tenant_id)
    
    media_data = [MediaSourceResponse.model_validate(m) for m in media_list]
    return StandardResponse(
        message=f"Retrieved {len(media_data)} media sources.",
        status=status.HTTP_200_OK,
        data=media_data
    )

@router.post(
    "/search",
    response_model=StandardResponse[SearchSessionResponse],
    status_code=status.HTTP_200_OK
)
async def search_by_reference_selfie(
    file: UploadFile = File(..., description="Your reference selfie/profile photo"),
    threshold: float = Form(0.45, ge=0.0, le=1.0, description="Similarity matching threshold (default: 0.45)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Uploads a profile picture/selfie, extracts the main face vector, 
    and checks all indexed images and video keyframes belonging to your tenant.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleFindService(db)
    session = await service.search_by_selfie(file, threshold, tenant_id)
    
    session_data = SearchSessionResponse.model_validate(session)
    return StandardResponse(
        message="Selfie search completed successfully.",
        status=status.HTTP_200_OK,
        data=session_data
    )

@router.post(
    "/search-video",
    response_model=StandardResponse[SearchSessionResponse],
    status_code=status.HTTP_202_ACCEPTED
)
async def search_video_on_demand(
    video_id: uuid.UUID = Form(..., description="The ID of the video to search in"),
    file: UploadFile = File(..., description="Your reference selfie/profile photo"),
    threshold: float = Form(0.45, ge=0.0, le=1.0, description="Similarity matching threshold (default: 0.45)"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submits a background task to search inside a specific video file on-demand 
    using the reference selfie. Keyframe annotations and intervals report are generated.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleFindService(db)
    session = await service.search_in_video_async(video_id, file, threshold, tenant_id)
    
    session_data = SearchSessionResponse.model_validate(session)
    return StandardResponse(
        message="Video search task submitted successfully in the background.",
        status=status.HTTP_202_ACCEPTED,
        data=session_data
    )


@router.get(
    "/sessions/{session_id}",
    response_model=StandardResponse[List[SearchResultResponse]],
    status_code=status.HTTP_200_OK
)
async def get_search_session_matches(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches all matching photos and video frames found during a search session, 
    ordered from highest similarity down to the threshold limit.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleFindService(db)
    results = await service.get_session_details(session_id, tenant_id)
    
    results_data = [SearchResultResponse.model_validate(r) for r in results]
    return StandardResponse(
        message=f"Retrieved {len(results_data)} matches for this search session.",
        status=status.HTTP_200_OK,
        data=results_data
    )



@router.delete(
    "/media/{media_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_event_media(
    media_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft deletes an uploaded photo or video and its face embeddings from the catalog, 
    and removes the file from disk storage.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleFindService(db)
    await service.delete_media_source(media_id, tenant_id)
    
    return StandardResponse(
        message="Media source and associated face embeddings deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )

@router.delete(
    "/media",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_all_event_media(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft deletes all uploaded photos and videos (and their face embeddings) scoped to your tenant namespace,
    and removes the physical files from disk.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleFindService(db)
    deleted_count = await service.delete_all_media_sources(tenant_id)
    
    return StandardResponse(
        message=f"Successfully deleted {deleted_count} media source(s) and all associated face embeddings.",
        status=status.HTTP_200_OK,
        data=None
    )
