import os
import uuid
import cv2
from typing import List, Tuple, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.peoplefind.repository import PeopleFindRepository
from modules.peoplefind.model import MediaSource, FaceSearchSession, FaceSearchResult
from services.ai.face_recognition import face_rec_service

MEDIA_SOURCES_DIR = os.path.join("storage", "media_sources")
SELFIES_DIR = os.path.join("storage", "selfies")

# Ensure storage directories exist
os.makedirs(MEDIA_SOURCES_DIR, exist_ok=True)
os.makedirs(SELFIES_DIR, exist_ok=True)

class PeopleFindService:
    def __init__(self, db: AsyncSession):
        self.repo = PeopleFindRepository(db)
        self.db = db

    async def upload_and_index_media(
        self, files: List[UploadFile], media_type: str, tenant_id: uuid.UUID
    ) -> List[MediaSource]:
        """
        Uploads multiple admin photos or videos, saves them, and indexes detected faces into the DB.
        """
        results = []
        for file in files:
            # Smart Deduplication: Check if filename already exists for this tenant
            existing = await self.repo.get_media_source_by_filename(file.filename, tenant_id)
            if existing:
                if existing.status in {"completed", "processing"}:
                    # Already successfully indexed/indexing, skip processing and keep this record
                    results.append(existing)
                    continue
                else:
                    # Failed or pending status, delete old record & file and re-process
                    if os.path.exists(existing.filepath):
                        try:
                            os.remove(existing.filepath)
                        except Exception:
                            pass
                    await self.db.delete(existing)
                    await self.db.flush()

            # Save media file locally
            file_ext = os.path.splitext(file.filename)[1].lower()
            unique_name = f"{uuid.uuid4()}{file_ext}"
            
            content = await file.read()
            
            # Convert HEIC/HEIF photos to JPG for standard browser rendering
            if media_type == "photo" and file_ext in {".heic", ".heif"}:
                try:
                    import io
                    from PIL import Image
                    import pillow_heif
                    pillow_heif.register_heif_opener()
                    
                    image = Image.open(io.BytesIO(content))
                    if image.mode != "RGB":
                        image = image.convert("RGB")
                    
                    file_ext = ".jpg"
                    unique_name = f"{uuid.uuid4()}{file_ext}"
                    filepath = os.path.join(MEDIA_SOURCES_DIR, unique_name)
                    image.save(filepath, "JPEG", quality=90)
                except Exception as e:
                    print(f"HEIC conversion failed, falling back to original: {str(e)}")
                    filepath = os.path.join(MEDIA_SOURCES_DIR, unique_name)
                    with open(filepath, "wb") as f:
                        f.write(content)
            else:
                filepath = os.path.join(MEDIA_SOURCES_DIR, unique_name)
                with open(filepath, "wb") as f:
                    f.write(content)

            # Create database record
            media = await self.repo.create_media_source(
                tenant_id=tenant_id,
                filename=file.filename or unique_name,
                filepath=filepath,
                media_type=media_type
            )
            await self.db.commit()

            # Perform indexing based on media type
            try:
                if media_type == "photo":
                    # Set status to processing and trigger Celery background task
                    await self.repo.update_media_source_status(media.id, "processing")
                    await self.db.commit()
                    
                    from workers.tasks import index_photo_task
                    index_photo_task.delay(str(media.id), filepath)
                
                elif media_type == "video":
                    # Trigger background video indexing Celery task
                    await self.repo.update_media_source_status(media.id, "processing")
                    await self.db.commit()
                    
                    from workers.tasks import index_video_task
                    index_video_task.delay(str(media.id), filepath)
                    
            except Exception as e:
                await self.repo.update_media_source_status(media.id, "failed")
                await self.db.commit()
                raise HTTPException(
                    status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                    detail=f"Failed to process and index media file {file.filename}: {str(e)}"
                )

            results.append(media)

        return results

    async def search_in_video_async(
        self, video_id: uuid.UUID, file: UploadFile, threshold: float, tenant_id: uuid.UUID
    ) -> FaceSearchSession:
        """
        Registers a selfie and launches a Celery task to search occurrences of that face 
        inside a specific video on-demand.
        """
        # Validate that the video exists and belongs to the active tenant
        media = await self.repo.get_media_source_by_id(video_id, tenant_id)
        if not media or media.media_type != "video":
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Target video not found or unauthorized access."
            )

        # Save reference selfie image
        file_ext = os.path.splitext(file.filename)[1].lower()
        unique_name = f"{uuid.uuid4()}{file_ext}"
        
        content = await file.read()
        
        # Convert HEIC/HEIF selfies to JPG for standard compatibility
        if file_ext in {".heic", ".heif"}:
            try:
                import io
                from PIL import Image
                import pillow_heif
                pillow_heif.register_heif_opener()
                
                image = Image.open(io.BytesIO(content))
                if image.mode != "RGB":
                    image = image.convert("RGB")
                
                file_ext = ".jpg"
                unique_name = f"{uuid.uuid4()}{file_ext}"
                selfie_path = os.path.join(SELFIES_DIR, unique_name)
                image.save(selfie_path, "JPEG", quality=90)
            except Exception as e:
                print(f"HEIC selfie conversion failed, falling back: {str(e)}")
                selfie_path = os.path.join(SELFIES_DIR, unique_name)
                with open(selfie_path, "wb") as f:
                    f.write(content)
        else:
            selfie_path = os.path.join(SELFIES_DIR, unique_name)
            with open(selfie_path, "wb") as f:
                f.write(content)

        # Extract selfie face embedding
        try:
            faces = face_rec_service.extract_faces(content)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse selfie image: {str(e)}"
            )

        if not faces:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No faces detected in the selfie. Please provide a clear profile photo."
            )

        ref_face = max(faces, key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))
        ref_embedding = ref_face["embedding"]

        # Create Search Session in pending status
        session = await self.repo.create_search_session(
            tenant_id=tenant_id,
            selfie_path=selfie_path,
            selfie_embedding=ref_embedding,
            threshold=threshold
        )
        await self.db.commit()

        # Trigger on-demand video search Celery task
        from workers.tasks import process_video_search_task
        process_video_search_task.delay(
            str(video_id),
            str(session.id),
            threshold,
            interval=1.0
        )

        loaded_session = await self.repo.get_search_session_with_results(session.id, tenant_id)
        return loaded_session or session

    async def _index_photo_sync(self, media_id: uuid.UUID, filepath: str) -> None:
        """
        Helper method that processes a photo, extracts faces, 
        and indexes faces into the database. Called asynchronously by Celery.
        """
        if not os.path.exists(filepath):
            await self.repo.update_media_source_status(media_id, "failed")
            await self.db.commit()
            return

        try:
            with open(filepath, "rb") as f:
                content = f.read()

            faces = face_rec_service.extract_faces(content)
            for face in faces:
                await self.repo.create_face_embedding(
                    media_source_id=media_id,
                    face_idx=face["face_idx"],
                    bbox=face["bbox"],
                    embedding=face["embedding"],
                    timestamp=None
                )
            await self.repo.update_media_source_status(media_id, "completed")
            await self.db.commit()
        except Exception as e:
            await self.repo.update_media_source_status(media_id, "failed")
            await self.db.commit()
            raise e

    async def _index_video_sync(self, media_id: uuid.UUID, filepath: str, interval: float = 1.0) -> None:
        """
        Helper method that processes a video, extracts frames at intervals, 
        and indexes faces into the database with timestamps.
        """
        cap = cv2.VideoCapture(filepath)
        if not cap.isOpened():
            raise ValueError(f"Could not open video file: {filepath}")

        fps = cap.get(cv2.CAP_PROP_FPS)
        if fps <= 0:
            fps = 30.0

        frame_step = max(1, int(fps * interval))
        f_idx = 0
        face_count = 0

        while True:
            if f_idx % frame_step == 0:
                ret, frame = cap.read()
                if not ret or frame is None:
                    break

                # Downscale for CPU optimization (matches reference step3_video.py logic)
                h, w = frame.shape[:2]
                max_dim = 640
                if max(h, w) > max_dim:
                    scale = max_dim / max(h, w)
                    frame = cv2.resize(frame, (int(w * scale), int(h * scale)))
                else:
                    scale = 1.0

                # Encode frame to bytes for face recognition service
                _, encoded_img = cv2.imencode(".jpg", frame)
                frame_bytes = encoded_img.tobytes()

                # Detect faces
                faces = face_rec_service.extract_faces(frame_bytes)
                sec = f_idx / fps

                for face in faces:
                    # Restore coordinates back to original full resolution
                    orig_bbox = [
                        int(face["bbox"][0] / scale),
                        int(face["bbox"][1] / scale),
                        int(face["bbox"][2] / scale),
                        int(face["bbox"][3] / scale)
                    ]
                    
                    await self.repo.create_face_embedding(
                        media_source_id=media_id,
                        face_idx=face_count,
                        bbox=orig_bbox,
                        embedding=face["embedding"],
                        timestamp=sec
                    )
                    face_count += 1
                
                # Skip frames sequentially by calling cap.grab()
                for _ in range(frame_step - 1):
                    ret = cap.grab()
                    if not ret:
                        break
                    f_idx += 1
            else:
                ret = cap.grab()
                if not ret:
                    break
            
            f_idx += 1

        cap.release()
        await self.repo.update_media_source_status(media_id, "completed")
        await self.db.commit()

    async def search_by_selfie(
        self, file: UploadFile, threshold: float, tenant_id: uuid.UUID
    ) -> FaceSearchSession:
        """
        Registers reference selfie, extracts the main face vector, performs similarity search 
        across indexed tenant faces, and generates search results.
        """
        # Save reference selfie image
        file_ext = os.path.splitext(file.filename)[1].lower()
        unique_name = f"{uuid.uuid4()}{file_ext}"
        
        content = await file.read()
        
        # Convert HEIC/HEIF selfies to JPG for standard compatibility
        if file_ext in {".heic", ".heif"}:
            try:
                import io
                from PIL import Image
                import pillow_heif
                pillow_heif.register_heif_opener()
                
                image = Image.open(io.BytesIO(content))
                if image.mode != "RGB":
                    image = image.convert("RGB")
                
                file_ext = ".jpg"
                unique_name = f"{uuid.uuid4()}{file_ext}"
                selfie_path = os.path.join(SELFIES_DIR, unique_name)
                image.save(selfie_path, "JPEG", quality=90)
            except Exception as e:
                print(f"HEIC selfie conversion failed, falling back: {str(e)}")
                selfie_path = os.path.join(SELFIES_DIR, unique_name)
                with open(selfie_path, "wb") as f:
                    f.write(content)
        else:
            selfie_path = os.path.join(SELFIES_DIR, unique_name)
            with open(selfie_path, "wb") as f:
                f.write(content)

        # Extract selfie faces
        try:
            faces = face_rec_service.extract_faces(content)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not parse selfie image: {str(e)}"
            )

        if not faces:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No faces detected in the selfie. Please provide a clear profile photo."
            )

        # Pick the largest face in selfie
        ref_face = max(faces, key=lambda x: (x["bbox"][2] - x["bbox"][0]) * (x["bbox"][3] - x["bbox"][1]))
        ref_embedding = ref_face["embedding"]

        # Create Search Session
        session = await self.repo.create_search_session(
            tenant_id=tenant_id,
            selfie_path=selfie_path,
            selfie_embedding=ref_embedding,
            threshold=threshold
        )
        await self.db.commit()

        # Find matching faces in DB (scoped to the same tenant_id) for all faces detected in the photo
        try:
            media_best = {}  # media_source_id -> (similarity, face_embedding)
            
            for face in faces:
                target_emb = face["embedding"]
                matches = await self.repo.find_similar_faces(
                    tenant_id=tenant_id,
                    target_embedding=target_emb,
                    threshold=threshold
                )

                # De-duplicate matches per photo (only keep highest similarity match per source media item)
                for face_emb, sim in matches:
                    media_id = face_emb.media_source_id
                    if media_id not in media_best or sim > media_best[media_id][0]:
                        media_best[media_id] = (sim, face_emb)

            # Save confirmed matches in FaceSearchResult table
            for media_id, (sim, face_emb) in media_best.items():
                await self.repo.create_search_result(
                    session_id=session.id,
                    media_source_id=media_id,
                    similarity=sim,
                    bbox=face_emb.bbox,
                    timestamp=face_emb.timestamp
                )

            await self.repo.update_search_session_status(session.id, "completed")
            await self.db.commit()

        except Exception as e:
            await self.repo.update_search_session_status(session.id, "failed")
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Search matching process failed: {str(e)}"
            )

        # Retrieve the session with loaded results and media sources
        loaded_session = await self.repo.get_search_session_with_results(session.id, tenant_id)
        return loaded_session or session


    async def get_session_details(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> List[FaceSearchResult]:
        """Retrieve results and matching details of a session, sorted by similarity."""
        return await self.repo.get_session_results(session_id, tenant_id)



    async def delete_media_source(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        """
        Soft deletes a media source from DB and deletes the file from disk.
        """
        media = await self.repo.get_media_source_by_id(media_id, tenant_id)
        if not media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Media source not found or unauthorized access."
            )

        # Delete physical file from disk
        if media.filepath and os.path.exists(media.filepath):
            try:
                os.remove(media.filepath)
            except Exception:
                pass

        # Perform database soft delete
        await self.repo.delete_media_source(media_id, tenant_id)
        await self.db.commit()

    async def get_all_media_sources(self, tenant_id: uuid.UUID) -> List[MediaSource]:
        """
        Retrieves all non-deleted media sources for the active tenant.
        """
        return await self.repo.get_all_media_sources(tenant_id)

    async def delete_all_media_sources(self, tenant_id: uuid.UUID) -> int:
        """
        Soft deletes all media sources for a tenant from the DB and deletes their physical files from disk.
        """
        filepaths = await self.repo.bulk_delete_media_sources(tenant_id)
        
        # Delete files from disk
        deleted_count = 0
        for filepath in filepaths:
            if filepath and os.path.exists(filepath):
                try:
                    os.remove(filepath)
                    deleted_count += 1
                except Exception:
                    pass
                    
        await self.db.commit()
        return len(filepaths)

    @classmethod
    async def migrate_existing_heic(cls):
        """
        Background migration method to convert all existing HEIC files to JPG format.
        """
        from database.session import SessionLocal
        from PIL import Image
        import pillow_heif
        from sqlalchemy import select
        
        try:
            pillow_heif.register_heif_opener()
            async with SessionLocal() as session:
                result = await session.execute(
                    select(MediaSource).where(
                        (MediaSource.filepath.ilike("%.heic")) | (MediaSource.filepath.ilike("%.heif"))
                    )
                )
                sources = result.scalars().all()
                if not sources:
                    return
                
                print(f"[HEIC Migration] Found {len(sources)} HEIC/HEIF media sources to convert.")
                for source in sources:
                    old_path = source.filepath
                    if not os.path.exists(old_path):
                        print(f"[HEIC Migration] File not found on disk: {old_path}")
                        continue
                    try:
                        image = Image.open(old_path)
                        if image.mode != "RGB":
                            image = image.convert("RGB")
                        
                        base, _ = os.path.splitext(old_path)
                        new_path = f"{base}.jpg"
                        
                        image.save(new_path, "JPEG", quality=90)
                        source.filepath = new_path
                        
                        if source.filename.lower().endswith(".heic"):
                            source.filename = source.filename[:-5] + ".jpg"
                        elif source.filename.lower().endswith(".heif"):
                            source.filename = source.filename[:-5] + ".jpg"
                        
                        os.remove(old_path)
                        print(f"[HEIC Migration] Converted: {old_path} -> {new_path}")
                    except Exception as err:
                        print(f"[HEIC Migration] Failed to convert {old_path}: {err}")
                await session.commit()
                print("[HEIC Migration] Completed migration successfully.")
        except Exception as e:
            print(f"[HEIC Migration] Error during background migration: {str(e)}")

