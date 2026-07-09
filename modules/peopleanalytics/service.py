import os
import uuid
from typing import List, Optional
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.peopleanalytics.repository import PeopleAnalyticsRepository
from modules.peopleanalytics.model import PeopleAnalyticsSession, EmployeeAttendanceLog
from modules.peopleanalytics.schema import VisitorAnalyticsReport, VideoProcessItem, SessionDetectedPerson, FirstTimeVisitorDetail
from modules.users.model import User

ANALYTICS_OUTPUTS_DIR = os.path.join("storage", "people_analytics_outputs")
os.makedirs(ANALYTICS_OUTPUTS_DIR, exist_ok=True)

class PeopleAnalyticsService:
    def __init__(self, db: AsyncSession):
        self.repo = PeopleAnalyticsRepository(db)
        self.db = db

    # ==========================================
    # ANALYTICS SESSIONS — gallery-based
    # ==========================================

    async def create_and_start_sessions(
        self,
        tenant_id: uuid.UUID,
        videos: List[VideoProcessItem],
        global_line_start: Optional[List[int]] = None,
        global_line_end: Optional[List[int]] = None,
        global_similarity_threshold: float = 0.85,
        global_confidence_threshold: float = 0.3,
        user_id: Optional[uuid.UUID] = None
    ) -> List[PeopleAnalyticsSession]:
        # Validate all gallery media IDs and resolve file paths
        from modules.gallery.repository import GalleryRepository
        gallery_repo = GalleryRepository(self.db)

        resolved_items = []
        for item in videos:
            gallery_media_id = uuid.UUID(item.gallery_media_id)
            gallery_media = await gallery_repo.get_media_by_id(gallery_media_id, tenant_id)
            if not gallery_media:
                raise HTTPException(
                    status_code=status.HTTP_404_NOT_FOUND,
                    detail=f"Gallery media '{item.gallery_media_id}' not found or access denied."
                )
            if gallery_media.media_type != "video":
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Gallery media '{item.gallery_media_id}' is not a video file."
                )
            if not os.path.exists(gallery_media.filepath):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Gallery media file does not exist on server storage: '{gallery_media.filepath}'."
                )
            resolved_items.append((item, gallery_media))

        sessions = []

        for item, gallery_media in resolved_items:
            filepath = gallery_media.filepath

            # Determine parameters (local override or global fallback)
            line_start = item.line_start if item.line_start is not None else global_line_start
            line_end = item.line_end if item.line_end is not None else global_line_end
            similarity_threshold = item.similarity_threshold if item.similarity_threshold is not None else global_similarity_threshold
            confidence_threshold = item.confidence_threshold if item.confidence_threshold is not None else global_confidence_threshold

            video_name = gallery_media.filename
            # Register database session
            session = await self.repo.create_analytics_session(
                tenant_id=tenant_id,
                video_name=video_name,
                video_path=filepath,
                line_start=line_start,
                line_end=line_end,
                similarity_threshold=similarity_threshold,
                confidence_threshold=confidence_threshold
            )
            await self.db.commit()
            await self.db.refresh(session)

            # Schedule background tracking/analytics task
            from modules.peopleanalytics.tasks import process_people_analytics_task
            process_people_analytics_task.delay(
                str(session.id),
                filepath,
                line_start,
                line_end,
                similarity_threshold,
                confidence_threshold,
                str(user_id) if user_id else None
            )

            sessions.append(session)

        return sessions

    async def get_session(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> PeopleAnalyticsSession:
        session = await self.repo.get_session_by_id(session_id, tenant_id)
        if not session:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Analytics session not found or unauthorized access."
            )
        
        # Fetch first-time visitors and attach to session
        first_time_occs = await self.repo.get_session_first_time_visitors(session_id)
        from collections import defaultdict
        grouped_visitors = defaultdict(list)
        for occ in first_time_occs:
            grouped_visitors[occ.identity_id].append(occ)

        session.first_time_visitors = [
            FirstTimeVisitorDetail(
                identity_id=identity_id,
                photo_path=next((occ.crop_path for occ in occs if occ.crop_path), None),
                first_seen=min(occ.first_seen for occ in occs),
                last_seen=max(occ.last_seen for occ in occs),
                first_name=occs[0].identity.first_name if (occs and occs[0].identity) else None,
                last_name=occs[0].identity.last_name if (occs and occs[0].identity) else None
            )
            for identity_id, occs in grouped_visitors.items()
        ]
        return session

    async def get_all_sessions(self, tenant_id: uuid.UUID) -> List[PeopleAnalyticsSession]:
        return await self.repo.get_all_sessions(tenant_id)

    async def delete_session(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> None:
        # Soft delete in database
        res = await self.repo.delete_session(session_id, tenant_id)
        if not res:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Session not found or unauthorized access."
            )
        
        video_path, output_video_path, crop_paths = res
        # Remove physical files
        all_paths = [video_path, output_video_path] + crop_paths
        for path in all_paths:
            if path and os.path.exists(path):
                try:
                    os.remove(path)
                except Exception:
                    pass
        await self.db.commit()

    async def get_visitor_dashboard(self, tenant_id: uuid.UUID) -> VisitorAnalyticsReport:
        tot_unq, rep_vis, rate, new_this_month = await self.repo.get_visitor_dashboard_metrics(tenant_id)
        return VisitorAnalyticsReport(
            total_unique_people=tot_unq,
            repeat_visitors_count=rep_vis,
            repeat_visitor_rate=rate,
            new_visitors_this_month=new_this_month
        )

    async def get_session_detected_people(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> List[SessionDetectedPerson]:
        # 1. Verify session exists & authorized
        await self.get_session(session_id, tenant_id)

        # 2. Get all visitor occurrences in this session
        occurrences = await self.repo.get_session_occurrences(session_id)

        # 3. Get all employee attendance logs in this session (reusing the new employee service method)
        from modules.employees.service import EmployeeService
        emp_service = EmployeeService(self.db)
        attendance_logs = await emp_service.get_session_attendance(session_id, tenant_id)

        people = []

        # Add employees
        for log in attendance_logs:
            people.append(SessionDetectedPerson(
                identity_id=log.employee_id,
                type="employee",
                name=f"{log.employee.first_name} {log.employee.last_name}",
                photo_path=log.employee.photo_path,
                first_seen=log.first_seen,
                last_seen=log.last_seen
            ))

        # Add visitors
        for occ in occurrences:
            if occ.identity and (occ.identity.first_name or occ.identity.last_name):
                visitor_name = f"{occ.identity.first_name or ''} {occ.identity.last_name or ''}".strip()
            else:
                visitor_name = f"Visitor #{str(occ.identity_id)[:4]}"
                
            people.append(SessionDetectedPerson(
                identity_id=occ.identity_id,
                type="visitor",
                name=visitor_name,
                photo_path=occ.crop_path,
                first_seen=occ.first_seen,
                last_seen=occ.last_seen
            ))

        return people

    async def get_visitor_attendance_by_date_range(
        self, tenant_id: uuid.UUID, start_date: object, end_date: object
    ):
        return await self.repo.get_visitor_attendance_by_date_range(tenant_id, start_date, end_date)

    async def register_visitor_or_convert_to_employee(
        self, tenant_id: uuid.UUID, data
    ):
        from sqlalchemy import select
        from sqlalchemy.orm import selectinload
        from fastapi import HTTPException
        from modules.peopleanalytics.model import PersonIdentity

        # 1. Fetch PersonIdentity with relationships
        stmt = (
            select(PersonIdentity)
            .options(
                selectinload(PersonIdentity.occurrences),
                selectinload(PersonIdentity.embeddings)
            )
            .where(
                PersonIdentity.id == data.identity_id,
                PersonIdentity.tenant_id == tenant_id,
                PersonIdentity.is_delete == False
            )
        )
        res = await self.db.execute(stmt)
        identity = res.scalars().first()
        if not identity:
            raise HTTPException(
                status_code=404,
                detail="Visitor identity not found."
            )

        if data.registration_type == "visitor":
            # Just update first_name & last_name
            identity.first_name = data.first_name
            identity.last_name = data.last_name
            await self.db.commit()
            return {"message": "Visitor registered successfully.", "type": "visitor"}

        elif data.registration_type == "employee":
            # 1. Verify employee code is unique under this tenant
            from modules.employees.repository import EmployeeRepository
            emp_repo = EmployeeRepository(self.db)
            existing = await emp_repo.get_employee_by_code(data.employee_code, tenant_id)
            if existing:
                raise HTTPException(
                    status_code=400,
                    detail=f"Employee code '{data.employee_code}' is already registered."
                )

            # 2. Get photo path (crop_path from first occurrence)
            crop_path = None
            for occ in identity.occurrences:
                if occ.crop_path:
                    crop_path = occ.crop_path
                    break

            if not crop_path:
                raise HTTPException(
                    status_code=400,
                    detail="No crop photo available for this visitor to register as employee."
                )

            # 3. Copy crop file to employee photos directory
            import shutil
            from modules.employees.service import EMPLOYEE_PHOTOS_DIR
            os.makedirs(EMPLOYEE_PHOTOS_DIR, exist_ok=True)
            
            src_full_path = crop_path
            new_filename = f"{uuid.uuid4()}.jpg"
            dest_full_path = os.path.join(EMPLOYEE_PHOTOS_DIR, new_filename)
            
            try:
                shutil.copy(src_full_path, dest_full_path)
                emp_photo_path = dest_full_path.replace("\\", "/")
            except Exception:
                emp_photo_path = crop_path

            # 4. Get embedding from PersonEmbedding
            if not identity.embeddings:
                raise HTTPException(
                    status_code=400,
                    detail="No ReID embedding found for this visitor identity."
                )
            
            target_embedding = identity.embeddings[0].embedding
            bbox = identity.embeddings[0].bbox

            # 5. Create new Employee
            from modules.employees.model import Employee, EmployeeEmbedding
            from modules.peopleanalytics.model import EmployeeAttendanceLog, VisitorAttendanceLog
            
            employee = Employee(
                id=uuid.uuid4(),
                tenant_id=tenant_id,
                first_name=data.first_name,
                last_name=data.last_name,
                employee_code=data.employee_code,
                photo_path=emp_photo_path
            )
            self.db.add(employee)
            await self.db.flush()

            # Create Employee Embedding
            emp_emb = EmployeeEmbedding(
                employee_id=employee.id,
                embedding=target_embedding,
                bbox=bbox
            )
            self.db.add(emp_emb)

            # 6. Migrate VisitorAttendanceLog records to EmployeeAttendanceLog
            stmt_logs = select(VisitorAttendanceLog).where(
                VisitorAttendanceLog.identity_id == identity.id,
                VisitorAttendanceLog.is_delete == False
            )
            res_logs = await self.db.execute(stmt_logs)
            v_logs = res_logs.scalars().all()
            
            for v_log in v_logs:
                emp_log = EmployeeAttendanceLog(
                    session_id=v_log.session_id,
                    employee_id=employee.id,
                    first_seen=v_log.first_seen,
                    last_seen=v_log.last_seen,
                    occurrence_count=v_log.occurrence_count,
                    employee_entry_timestamp=v_log.visitor_entry_timestamp,
                    employee_exit_timestamp=v_log.visitor_exit_timestamp,
                    created_at=v_log.created_at,
                    update_at=v_log.update_at
                )
                self.db.add(emp_log)
                
            # 7. Delete visitor data (cascades embeddings, occurrences, visitor attendance logs, crossing logs)
            await self.db.delete(identity)
            
            await self.db.commit()
            
            # Invalidate employee embeddings cache for this tenant
            from modules.employees.cache import invalidate_employee_embeddings_cache
            await invalidate_employee_embeddings_cache(tenant_id)
            
            return {
                "message": f"Visitor successfully registered as Employee ({data.employee_code}) and visitor logs converted.",
                "type": "employee"
            }

