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
from services.ai.people_analytics import ReIDFeatureExtractor
from shared.utils.image import convert_and_save_image

EMPLOYEE_PHOTOS_DIR = os.path.join("storage", "employee_photos")
os.makedirs(EMPLOYEE_PHOTOS_DIR, exist_ok=True)

class EmployeeService:
    def __init__(self, db: AsyncSession):
        self.repo = EmployeeRepository(db)
        self.db = db
        self.extractor = ReIDFeatureExtractor()

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
        return employee

    async def _extract_employee_features(self, image_bytes: bytes) -> Tuple[np.ndarray, Optional[list[int]]]:
        nparr = np.frombuffer(image_bytes, np.uint8)
        img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
        if img is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image upload. Could not decode file."
            )

        try:
            model = YOLO("models/yolo12m.pt")
            results = model(img, classes=[0], verbose=False)
            boxes = results[0].boxes
        except Exception:
            boxes = []

        crop = img
        bbox = None

        if len(boxes) > 0:
            largest_box = max(boxes, key=lambda b: (b.xyxy[0][2] - b.xyxy[0][0]) * (b.xyxy[0][3] - b.xyxy[0][1]))
            x1, y1, x2, y2 = map(int, largest_box.xyxy[0])
            crop = img[y1:y2, x1:x2]
            bbox = [x1, y1, x2, y2]

        embedding = self.extractor.get_embedding(crop)
        if embedding is None:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Failed to extract visual ReID embedding from employee photo."
            )

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
