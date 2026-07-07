import os
import uuid
import cv2
import numpy as np
from typing import List, Tuple, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from ultralytics import YOLO

from modules.employees.repository import EmployeeRepository
from modules.employees.model import Employee
from modules.peopleanalytics.model import EmployeeAttendanceLog
from shared.utils.image import convert_and_save_image
from services.ai.face_recognition import face_rec_service
from modules.employees.cache import invalidate_employee_embeddings_cache

EMPLOYEE_PHOTOS_DIR = os.path.join("storage", "employee_photos")
os.makedirs(EMPLOYEE_PHOTOS_DIR, exist_ok=True)

class EmployeeService:
    def __init__(self, db: AsyncSession):
        self.repo = EmployeeRepository(db)
        self.db = db

    async def register_employee(
        self, tenant_id: uuid.UUID, first_name: str, last_name: str, employee_code: str, file: UploadFile
    ) -> Employee:
        existing = await self.repo.get_employee_by_code(employee_code, tenant_id)
        if existing:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Employee code '{employee_code}' is already registered in this tenant."
            )

        content = await file.read()
        photo_path = convert_and_save_image(content, file.filename, EMPLOYEE_PHOTOS_DIR)

        embedding, bbox = await self._extract_employee_features(content)

        employee = await self.repo.create_employee(
            tenant_id=tenant_id,
            first_name=first_name,
            last_name=last_name,
            employee_code=employee_code,
            photo_path=photo_path
        )
        await self.repo.create_employee_embedding(
            employee_id=employee.id,
            embedding=embedding.tolist(),
            bbox=bbox
        )
        await self.db.commit()
        await invalidate_employee_embeddings_cache(tenant_id)
        return employee

    async def get_employee(self, employee_id: uuid.UUID, tenant_id: uuid.UUID) -> Employee:
        employee = await self.repo.get_employee_by_id(employee_id, tenant_id)
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found or unauthorized."
            )
        return employee

    async def get_all_employees(self, tenant_id: uuid.UUID) -> List[Employee]:
        return await self.repo.get_all_employees(tenant_id)

    async def delete_employee(self, employee_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        employee = await self.repo.get_employee_by_id(employee_id, tenant_id)
        if not employee:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Employee not found or unauthorized."
            )

        await self.repo.delete_employee(employee_id, tenant_id)
        
        if employee.photo_path and os.path.exists(employee.photo_path):
            try:
                os.remove(employee.photo_path)
            except Exception:
                pass
        await self.db.commit()
        await invalidate_employee_embeddings_cache(tenant_id)

    async def update_employee(
        self, employee_id: uuid.UUID, tenant_id: uuid.UUID,
        first_name: Optional[str] = None, last_name: Optional[str] = None,
        employee_code: Optional[str] = None, file: Optional[UploadFile] = None
    ) -> Employee:
        employee = await self.get_employee(employee_id, tenant_id)
        
        if first_name is not None:
            employee.first_name = first_name
        if last_name is not None:
            employee.last_name = last_name
        if employee_code is not None:
            if employee_code != employee.employee_code:
                existing = await self.repo.get_employee_by_code(employee_code, tenant_id)
                if existing:
                    raise HTTPException(
                        status_code=status.HTTP_400_BAD_REQUEST,
                        detail=f"Employee code '{employee_code}' is already registered."
                    )
                employee.employee_code = employee_code

        if file is not None:
            if employee.photo_path and os.path.exists(employee.photo_path):
                try:
                    os.remove(employee.photo_path)
                except Exception:
                    pass

            content = await file.read()
            photo_path = convert_and_save_image(content, file.filename, EMPLOYEE_PHOTOS_DIR)
            employee.photo_path = photo_path

            embedding, bbox = await self._extract_employee_features(content)

            from sqlalchemy import delete
            from modules.employees.model import EmployeeEmbedding as EEModel
            await self.db.execute(delete(EEModel).where(EEModel.employee_id == employee.id))
            await self.repo.create_employee_embedding(
                employee_id=employee.id,
                embedding=embedding.tolist(),
                bbox=bbox
            )
            
        await self.db.commit()
        await invalidate_employee_embeddings_cache(tenant_id)
        return employee

    async def _extract_employee_features(self, image_bytes: bytes) -> Tuple[np.ndarray, Optional[list[int]]]:
        try:
            faces = face_rec_service.extract_faces(image_bytes)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not extract faces from image: {str(e)}"
            )

        if not faces:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="No face detected in the employee photo. Please upload a clear photo with a visible face."
            )

        largest_face = max(faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
        embedding = np.array(largest_face["embedding"], dtype=np.float32)
        bbox = largest_face["bbox"]

        return embedding, bbox

    async def get_session_attendance(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> List[EmployeeAttendanceLog]:
        # Confirm session exists and authorized
        session = await self.repo.get_session_by_id(session_id, tenant_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analytics session not found or unauthorized access."
            )
        return await self.repo.get_employee_attendance_report(session_id, tenant_id)

    async def get_attendance_by_date_range(
        self, tenant_id: uuid.UUID, start_date: object, end_date: object
    ) -> List[EmployeeAttendanceLog]:
        return await self.repo.get_employee_attendance_by_date_range(tenant_id, start_date, end_date)

    async def process_group_photo_attendance(
        self,
        tenant_id: uuid.UUID,
        user_id: uuid.UUID,
        gallery_media_id: uuid.UUID,
        similarity_threshold: float = 0.85,
        confidence_threshold: float = 0.3
    ) -> Tuple[List[EmployeeAttendanceLog], str, uuid.UUID]:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        from modules.gallery.repository import GalleryRepository
        gallery_repo = GalleryRepository(self.db)
        gallery_media = await gallery_repo.get_media_by_id(gallery_media_id, tenant_id)
        if not gallery_media:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Gallery media not found or unauthorized access."
            )
        if gallery_media.media_type != "photo":
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The selected gallery media is not a photo."
            )
        if not os.path.exists(gallery_media.filepath):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Gallery media file does not exist on storage: '{gallery_media.filepath}'."
            )

        filepath = gallery_media.filepath
        filename = gallery_media.filename
        
        session_id = uuid.uuid4()
        outputs_dir = os.path.join("storage", "employee_attendance_outputs", str(user_id))
        os.makedirs(outputs_dir, exist_ok=True)
        
        with open(filepath, "rb") as f:
            content = f.read()

        from modules.peopleanalytics.model import PeopleAnalyticsSession
        session = PeopleAnalyticsSession(
            id=session_id,
            tenant_id=tenant_id,
            video_name=filename or "group_photo.jpg",
            video_path=filepath,
            similarity_threshold=similarity_threshold,
            confidence_threshold=confidence_threshold,
            session_type="employees",
            status="pending"
        )
        self.db.add(session)
        await self.db.flush()

        # Decode image using Pillow for maximum compatibility (HEIC, PNG, JPEG, WEBP, etc.)
        from PIL import Image
        import io
        import pillow_heif
        
        img = None
        try:
            pillow_heif.register_heif_opener()
            image = Image.open(io.BytesIO(content))
            if image.mode != "RGB":
                image = image.convert("RGB")
            img_rgb = np.array(image)
            # Convert RGB to BGR for OpenCV
            img = cv2.cvtColor(img_rgb, cv2.COLOR_RGB2BGR)
        except Exception as e:
            # Fallback to OpenCV if Pillow decoding fails
            nparr = np.frombuffer(content, np.uint8)
            img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

        if img is None:
            session.status = "failed"
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image upload. Could not decode group photo."
            )

        # Convert image to JPEG bytes for FaceRecognitionService
        _, encoded_img = cv2.imencode(".jpg", img)
        img_bytes = encoded_img.tobytes()
        
        from services.ai.math_utils import map_similarity_threshold, find_best_match_in_cache
        from modules.employees.cache import get_cached_employee_embeddings
        
        # Load employee embeddings from cache (or DB)
        employee_cache = await get_cached_employee_embeddings(self.db, tenant_id)
        
        # Extract all faces
        try:
            faces = face_rec_service.extract_faces(img_bytes)
        except Exception as e:
            session.status = "failed"
            await self.db.commit()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Could not extract faces from photo: {str(e)}"
            )
            
        checked_in_logs = []
        mapped_threshold = map_similarity_threshold(similarity_threshold)
        
        for face in faces:
            embedding = np.array(face["embedding"], dtype=np.float32)
            match = find_best_match_in_cache(embedding, employee_cache, mapped_threshold)
            fx1, fy1, fx2, fy2 = map(int, face["bbox"])
            if match:
                employee, sim = match
                log = await self.repo.log_employee_attendance(
                    tenant_id=tenant_id,
                    employee_id=employee.id,
                    session_id=session.id,
                    first_seen_sec=0.0,
                    last_seen_sec=0.0,
                    occurrence_increment=1,
                    entry_time=now,
                    exit_time=now
                )
                checked_in_logs.append(log)
                # Draw green box for matched employee
                cv2.rectangle(img, (fx1, fy1), (fx2, fy2), (0, 255, 0), 2)
                label = f"{employee.first_name} {employee.last_name}"
                cv2.putText(img, label, (fx1, fy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 2)
            else:
                # Draw red box for unknown person
                cv2.rectangle(img, (fx1, fy1), (fx2, fy2), (0, 0, 255), 2)
                cv2.putText(img, "Unknown", (fx1, fy1 - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 255), 2)

        # Save output annotated image
        output_filename = f"{session.id}_annotated.jpg"
        output_filepath = os.path.join(outputs_dir, output_filename)
        cv2.imwrite(output_filepath, img)

        session.status = "completed"
        session.output_video_path = output_filepath
        session.completed_at = now

        unique_logs = {log.id: log for log in checked_in_logs}.values()

        session.unique_person_count = len(unique_logs)
        session.total_person_count = len(faces)
        session.entry_count = len(unique_logs)
        session.exit_count = 0
        
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from modules.peopleanalytics.model import EmployeeAttendanceLog as EAL
        
        log_ids = [l.id for l in unique_logs]
        if not log_ids:
            await self.db.commit()
            return [], output_filepath, session.id
            
        stmt = select(EAL).options(selectinload(EAL.employee)).where(EAL.id.in_(log_ids))
        res = await self.db.execute(stmt)
        
        await self.db.commit()
        return list(res.scalars().all()), output_filepath, session.id



    async def create_and_start_attendance_sessions(
        self,
        tenant_id: uuid.UUID,
        videos: List[object],
        global_similarity_threshold: float = 0.85,
        global_confidence_threshold: float = 0.3,
        user_id: uuid.UUID = None
    ) -> List[object]:
        from modules.gallery.repository import GalleryRepository
        gallery_repo = GalleryRepository(self.db)

        resolved_items = []
        for item in videos:
            gallery_media_id = item.gallery_media_id
            gallery_media = await gallery_repo.get_media_by_id(gallery_media_id, tenant_id)
            if not gallery_media:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Gallery media '{gallery_media_id}' not found or access denied."
                )
            if gallery_media.media_type != "video":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Gallery media '{gallery_media_id}' is not a video file."
                )
            if not os.path.exists(gallery_media.filepath):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Gallery media file does not exist on storage: '{gallery_media.filepath}'."
                )
            resolved_items.append((item, gallery_media))

        sessions = []
        outputs_dir = os.path.join("storage", "employee_attendance_outputs", str(user_id))
        os.makedirs(outputs_dir, exist_ok=True)

        for item, gallery_media in resolved_items:
            filepath = gallery_media.filepath
            similarity_threshold = getattr(item, "similarity_threshold", None)
            if similarity_threshold is None:
                similarity_threshold = global_similarity_threshold

            confidence_threshold = getattr(item, "confidence_threshold", None)
            if confidence_threshold is None:
                confidence_threshold = global_confidence_threshold

            video_name = gallery_media.filename
            session = await self.repo.create_analytics_session(
                tenant_id=tenant_id,
                video_name=video_name,
                video_path=filepath,
                line_start=None,
                line_end=None,
                similarity_threshold=similarity_threshold,
                confidence_threshold=confidence_threshold
            )
            await self.db.commit()
            await self.db.refresh(session)

            output_filename = f"{session.id}_annotated.mp4"
            output_path = os.path.join(outputs_dir, output_filename)

            from modules.employees.tasks import process_employee_attendance_video_task
            process_employee_attendance_video_task.delay(
                session_id_str=str(session.id),
                filepath=filepath,
                output_path=output_path,
                similarity_threshold=similarity_threshold,
                confidence_threshold=confidence_threshold
            )
            
            sessions.append(session)

        return sessions

    async def get_attendance_session(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> object:
        session = await self.repo.get_session_by_id(session_id, tenant_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or unauthorized access."
            )
        return session

    async def list_attendance_sessions(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> List[object]:
        return await self.repo.get_sessions(tenant_id)

    async def get_uploaded_photos(self, tenant_id: uuid.UUID) -> List[object]:
        return await self.repo.get_uploaded_photos(tenant_id)

    async def delete_uploaded_photo(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        res = await self.repo.delete_photo_session(session_id, tenant_id)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uploaded photo session not found or unauthorized access."
            )
        video_path, output_video_path = res
        # Only delete the annotated output file, keeping the raw gallery media
        if output_video_path and os.path.exists(output_video_path):
            try:
                os.remove(output_video_path)
            except Exception:
                pass
        await self.db.commit()



