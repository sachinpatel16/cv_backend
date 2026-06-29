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
        file: UploadFile,
        similarity_threshold: float = 0.85,
        confidence_threshold: float = 0.3
    ) -> Tuple[List[EmployeeAttendanceLog], str]:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc)
        
        os.makedirs(os.path.join("storage", "group_photos"), exist_ok=True)
        unique_name = f"{uuid.uuid4()}{os.path.splitext(file.filename or '')[1].lower()}"
        filepath = os.path.join("storage", "group_photos", unique_name)
        
        content = await file.read()
        with open(filepath, "wb") as f:
            f.write(content)

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
                    session_id=None,
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
        output_dir = os.path.join("storage", "group_photos_outputs")
        os.makedirs(output_dir, exist_ok=True)
        output_filename = f"{os.path.splitext(unique_name)[0]}_annotated.jpg"
        output_filepath = os.path.join(output_dir, output_filename)
        cv2.imwrite(output_filepath, img)

        unique_logs = {log.id: log for log in checked_in_logs}.values()
        
        from sqlalchemy.orm import selectinload
        from sqlalchemy import select
        from modules.peopleanalytics.model import EmployeeAttendanceLog as EAL
        
        log_ids = [l.id for l in unique_logs]
        if not log_ids:
            await self.db.commit()
            return [], output_filepath
            
        stmt = select(EAL).options(selectinload(EAL.employee)).where(EAL.id.in_(log_ids))
        res = await self.db.execute(stmt)
        
        await self.db.commit()
        return list(res.scalars().all()), output_filepath

    async def upload_attendance_video_files(
        self,
        tenant_id: uuid.UUID,
        files: List[UploadFile],
        user_id: uuid.UUID
    ) -> List[object]:
        if len(files) > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can upload a maximum of 10 files in a single batch request."
            )

        uploaded_records = []
        inputs_dir = os.path.join("storage", "employee_attendance_inputs", str(user_id))
        os.makedirs(inputs_dir, exist_ok=True)

        for file in files:
            original_name = file.filename or ""
            # Prevent duplicate uploads
            existing_video = await self.repo.get_uploaded_video_by_name(tenant_id, original_name)
            if existing_video:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Video file '{original_name}' has already been uploaded."
                )

            file_ext = os.path.splitext(original_name)[1].lower()
            unique_name = f"{uuid.uuid4()}{file_ext}"
            filepath = os.path.join(inputs_dir, unique_name)

            content = await file.read()
            with open(filepath, "wb") as f:
                f.write(content)

            uv = await self.repo.create_uploaded_video(
                tenant_id=tenant_id,
                original_name=original_name,
                saved_path=filepath,
                user_id=user_id
            )
            uploaded_records.append(uv)

        await self.db.commit()
        return uploaded_records

    async def get_uploaded_videos(self, tenant_id: uuid.UUID) -> List[object]:
        return await self.repo.get_uploaded_videos(tenant_id)

    async def delete_uploaded_video(self, video_id: uuid.UUID, tenant_id: uuid.UUID, current_user: object) -> None:
        video = await self.repo.get_uploaded_video_by_id(video_id, tenant_id)
        if not video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uploaded video not found or unauthorized access."
            )

        is_owner = (video.user_id == current_user.id)
        is_admin = getattr(current_user, "role", None) in ["admin", "superadmin"]

        if not (is_owner or is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this video."
            )

        video.is_delete = True
        
        if video.saved_path and os.path.exists(video.saved_path):
            try:
                os.remove(video.saved_path)
            except Exception:
                pass
        await self.db.commit()

    async def create_and_start_attendance_sessions(
        self,
        tenant_id: uuid.UUID,
        videos: List[object],
        global_similarity_threshold: float = 0.85,
        global_confidence_threshold: float = 0.3,
        user_id: uuid.UUID = None
    ) -> List[object]:
        # Validate all files exist on disk and belong to this tenant's module
        for item in videos:
            filepath = item.video_path
            if not os.path.exists(filepath):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Video file '{filepath}' does not exist on server storage."
                )
            if "employee_attendance_inputs" not in filepath:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Video file '{filepath}' is not a valid Employee Attendance video."
                )
            # Check tenant ownership in DB
            existing_video = await self.repo.get_uploaded_video_by_path(tenant_id, filepath)
            if not existing_video:
                raise HTTPException(
                    status_code=status.HTTP_403_FORBIDDEN,
                    detail=f"Unauthorized access or invalid video file: '{filepath}'"
                )

        sessions = []
        outputs_dir = os.path.join("storage", "employee_attendance_outputs", str(user_id))
        os.makedirs(outputs_dir, exist_ok=True)

        for item in videos:
            filepath = item.video_path
            similarity_threshold = getattr(item, "similarity_threshold", None)
            if similarity_threshold is None:
                similarity_threshold = global_similarity_threshold

            confidence_threshold = getattr(item, "confidence_threshold", None)
            if confidence_threshold is None:
                confidence_threshold = global_confidence_threshold


            video_name = os.path.basename(filepath)
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
        return await self.repo.get_sessions(tenant_id, user_id)

