import os
import uuid
from typing import List, Optional
from fastapi import UploadFile, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from modules.peopleanalytics.repository import PeopleAnalyticsRepository
from modules.peopleanalytics.model import PeopleAnalyticsSession, EmployeeAttendanceLog, UploadedVideo
from modules.peopleanalytics.schema import VisitorAnalyticsReport, VideoProcessItem, SessionDetectedPerson
from modules.users.model import User

ANALYTICS_INPUTS_DIR = os.path.join("storage", "people_analytics_inputs")
ANALYTICS_OUTPUTS_DIR = os.path.join("storage", "people_analytics_outputs")

# Ensure storage directories exist
os.makedirs(ANALYTICS_INPUTS_DIR, exist_ok=True)
os.makedirs(ANALYTICS_OUTPUTS_DIR, exist_ok=True)

class PeopleAnalyticsService:
    def __init__(self, db: AsyncSession):
        self.repo = PeopleAnalyticsRepository(db)
        self.db = db

    # ==========================================
    # BATCH CCTV ANALYTICS JOBS & UPLOADS
    # ==========================================

    async def upload_video_files(
        self,
        tenant_id: uuid.UUID,
        files: List[UploadFile],
        user_id: Optional[uuid.UUID] = None
    ) -> List[UploadedVideo]:
        if len(files) > 10:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="You can upload a maximum of 10 files in a single batch request."
            )

        uploaded_records = []

        for file in files:
            file_ext = os.path.splitext(file.filename)[1].lower()
            unique_name = f"{uuid.uuid4()}{file_ext}"
            
            user_inputs_dir = os.path.join(ANALYTICS_INPUTS_DIR, str(user_id)) if user_id else ANALYTICS_INPUTS_DIR
            os.makedirs(user_inputs_dir, exist_ok=True)
            filepath = os.path.join(user_inputs_dir, unique_name)

            # Save media file
            content = await file.read()
            with open(filepath, "wb") as f:
                f.write(content)

            original_name = file.filename or unique_name
            # Write to database
            uv = await self.repo.create_uploaded_video(
                tenant_id=tenant_id,
                original_name=original_name,
                saved_path=filepath,
                user_id=user_id
            )
            uploaded_records.append(uv)

        await self.db.commit()
        return uploaded_records

    async def get_all_uploaded_videos(self, tenant_id: uuid.UUID) -> List[UploadedVideo]:
        return await self.repo.get_all_uploaded_videos(tenant_id)

    async def delete_uploaded_video(self, video_id: uuid.UUID, tenant_id: uuid.UUID, current_user: User) -> None:
        video = await self.repo.get_uploaded_video_by_id(video_id, tenant_id)
        if not video:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="Uploaded video not found or unauthorized access."
            )

        # Check ownership: allowed if user is admin/superadmin OR if they are the owner of the video (matching user_id or saved_path subdirectory)
        is_owner = (video.user_id == current_user.id) or (str(current_user.id) in video.saved_path)
        is_admin = current_user.role in ["admin", "superadmin"]

        if not (is_owner or is_admin):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="You do not have permission to delete this video."
            )

        await self.repo.soft_delete_uploaded_video(video)

        if video.saved_path and os.path.exists(video.saved_path):
            try:
                os.remove(video.saved_path)
            except Exception:
                pass
        await self.db.commit()

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
        # Validate all files exist on disk
        for item in videos:
            filepath = item.video_path
            if not os.path.exists(filepath):
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"Video file '{filepath}' does not exist on server storage."
                )

        sessions = []

        for item in videos:
            filepath = item.video_path
            
            # Determine parameters (local override or global fallback)
            line_start = item.line_start if item.line_start is not None else global_line_start
            line_end = item.line_end if item.line_end is not None else global_line_end
            similarity_threshold = item.similarity_threshold if item.similarity_threshold is not None else global_similarity_threshold
            confidence_threshold = item.confidence_threshold if item.confidence_threshold is not None else global_confidence_threshold

            video_name = os.path.basename(filepath)
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
            people.append(SessionDetectedPerson(
                identity_id=occ.identity_id,
                type="visitor",
                name=f"Visitor #{str(occ.identity_id)[:4]}",
                photo_path=occ.crop_path,
                first_seen=occ.first_seen,
                last_seen=occ.last_seen
            ))

        return people
