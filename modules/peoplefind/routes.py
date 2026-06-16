import uuid
from typing import List
from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from database.redis import get_cached, set_cached, delete_cached, clear_cache_by_pattern
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import get_current_user
from modules.users.model import User
from modules.peoplefind.service import PeopleFindService
from modules.peoplefind.schema import (
    MediaSourceResponse,
    SearchSessionResponse,
    SearchResultResponse,
    SearchSessionHistoryResponse
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
    
    # Invalidate media list cache for this tenant
    await delete_cached(f"media_list:{tenant_id}")
    
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
    cache_key = f"media_list:{tenant_id}"
    
    cached = await get_cached(cache_key)
    if cached is not None:
        return StandardResponse(
            message=f"Retrieved {len(cached)} media sources.",
            status=status.HTTP_200_OK,
            data=[MediaSourceResponse.model_validate(m) for m in cached]
        )
    
    service = PeopleFindService(db)
    media_list = await service.get_all_media_sources(tenant_id)
    
    media_data = [MediaSourceResponse.model_validate(m) for m in media_list]
    # Cache the JSON-serializable list
    await set_cached(cache_key, [m.model_dump(mode="json") for m in media_data], expire=3600)
    
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
    session = await service.search_by_selfie(file, threshold, tenant_id, user_id=current_user.id)
    
    # Invalidate session history cache for this tenant
    await clear_cache_by_pattern(f"sessions_history:{tenant_id}:*")
    
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
    interval: float = Form(1.0, ge=0.1, description="Sampling interval in seconds (default: 1.0)"),
    buffalo_model: str = Form("buffalo_l", description="InsightFace model to use (default: 'buffalo_l')"),
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Submits a background task to search inside a specific video file on-demand 
    using the reference selfie. Keyframe annotations and intervals report are generated.
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleFindService(db)
    session = await service.search_in_video_async(
        video_id=video_id,
        file=file,
        threshold=threshold,
        tenant_id=tenant_id,
        user_id=current_user.id,
        interval=interval,
        model_name=buffalo_model
    )
    
    # Invalidate session history cache for this tenant
    await clear_cache_by_pattern(f"sessions_history:{tenant_id}:*")
    
    session_data = SearchSessionResponse.model_validate(session)
    return StandardResponse(
        message="Video search task submitted successfully in the background.",
        status=status.HTTP_202_ACCEPTED,
        data=session_data
    )


@router.get(
    "/sessions/history",
    response_model=StandardResponse[List[SearchSessionHistoryResponse]],
    status_code=status.HTTP_200_OK
)
async def list_search_sessions_history(
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves previous search sessions history scoped by tenant.
    For admin and superadmin roles, it retrieves all sessions in the tenant namespace.
    For operator and viewer roles, it retrieves only their own search sessions history.
    """
    tenant_id = verify_tenant(current_user)
    
    # Check role: admin/superadmin sees all, operator/viewer only sees their own
    user_id_filter = None
    if current_user.role not in {"admin", "superadmin"}:
        user_id_filter = current_user.id
        
    if user_id_filter:
        cache_key = f"sessions_history:{tenant_id}:user:{user_id_filter}"
    else:
        cache_key = f"sessions_history:{tenant_id}:all"
        
    cached = await get_cached(cache_key)
    if cached is not None:
        return StandardResponse(
            message=f"Retrieved {len(cached)} search session(s) in history.",
            status=status.HTTP_200_OK,
            data=[SearchSessionHistoryResponse.model_validate(s) for s in cached]
        )
        
    service = PeopleFindService(db)
    sessions = await service.get_search_history(tenant_id, user_id=user_id_filter)
    
    sessions_data = [SearchSessionHistoryResponse.model_validate(s) for s in sessions]
    # Cache the JSON-serializable list (30 mins duration)
    await set_cached(cache_key, [s.model_dump(mode="json") for s in sessions_data], expire=1800)
    
    return StandardResponse(
        message=f"Retrieved {len(sessions_data)} search session(s) in history.",
        status=status.HTTP_200_OK,
        data=sessions_data
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
    cache_key = f"session_matches:{session_id}"
    
    cached = await get_cached(cache_key)
    if cached is not None:
        return StandardResponse(
            message=f"Retrieved {len(cached)} matches for this search session.",
            status=status.HTTP_200_OK,
            data=[SearchResultResponse.model_validate(r) for r in cached]
        )
    
    service = PeopleFindService(db)
    session = await service.repo.get_search_session_by_id(session_id, tenant_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search session not found or unauthorized access."
        )
        
    results = await service.get_session_details(session_id, tenant_id)
    results_data = [SearchResultResponse.model_validate(r) for r in results]
    
    # Only cache if session has completed or failed, to avoid caching partial/empty results
    if session.status in {"completed", "failed"}:
        await set_cached(cache_key, [r.model_dump(mode="json") for r in results_data], expire=86400) # 24 hours
        
    return StandardResponse(
        message=f"Retrieved {len(results_data)} matches for this search session.",
        status=status.HTTP_200_OK,
        data=results_data
    )


@router.get(
    "/sessions/{session_id}/status",
    response_model=StandardResponse[SearchSessionResponse],
    status_code=status.HTTP_200_OK
)
async def get_search_session_status(
    session_id: uuid.UUID,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches the status and detailed metadata of a search session (including processing status).
    """
    tenant_id = verify_tenant(current_user)
    
    service = PeopleFindService(db)
    session = await service.repo.get_search_session_with_results(session_id, tenant_id)
    if not session:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Search session not found or unauthorized access."
        )
        
    session_data = SearchSessionResponse.model_validate(session)
    return StandardResponse(
        message="Session status retrieved successfully.",
        status=status.HTTP_200_OK,
        data=session_data
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
    
    # Invalidate media list cache for this tenant
    await delete_cached(f"media_list:{tenant_id}")
    
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
    
    # Invalidate media list cache for this tenant
    await delete_cached(f"media_list:{tenant_id}")
    
    return StandardResponse(
        message=f"Successfully deleted {deleted_count} media source(s) and all associated face embeddings.",
        status=status.HTTP_200_OK,
        data=None
    )
