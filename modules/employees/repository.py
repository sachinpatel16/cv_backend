import uuid
from datetime import datetime
from typing import List, Tuple, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.employees.model import Employee, EmployeeEmbedding
from modules.peopleanalytics.model import EmployeeAttendanceLog, PeopleAnalyticsSession

class EmployeeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_employee(
        self, tenant_id: uuid.UUID, first_name: str, last_name: str, employee_code: str, photo_path: str
    ) -> Employee:
        employee = Employee(
            tenant_id=tenant_id,
            first_name=first_name,
            last_name=last_name,
            employee_code=employee_code,
            photo_path=photo_path,
            is_active=True
        )
        self.db.add(employee)
        await self.db.flush()
        return employee

    async def get_employee_by_id(self, employee_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Employee]:
        stmt = select(Employee).where(
            Employee.id == employee_id,
            Employee.tenant_id == tenant_id,
            Employee.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_employee_by_code(self, employee_code: str, tenant_id: uuid.UUID) -> Optional[Employee]:
        stmt = select(Employee).where(
            Employee.employee_code == employee_code,
            Employee.tenant_id == tenant_id,
            Employee.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_employees(self, tenant_id: uuid.UUID) -> List[Employee]:
        stmt = select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.is_delete == False
        ).order_by(Employee.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_employee(self, employee_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Employee]:
        employee = await self.get_employee_by_id(employee_id, tenant_id)
        if employee:
            employee.is_delete = True
            stmt_emb = update(EmployeeEmbedding).where(
                EmployeeEmbedding.employee_id == employee_id
            ).values(is_delete=True)
            await self.db.execute(stmt_emb)
            await self.db.flush()
        return employee

    async def create_employee_embedding(
        self, employee_id: uuid.UUID, embedding: list[float], bbox: Optional[list[int]] = None
    ) -> EmployeeEmbedding:
        ee = EmployeeEmbedding(
            employee_id=employee_id,
            embedding=embedding,
            bbox=bbox
        )
        self.db.add(ee)
        await self.db.flush()
        return ee

    async def find_similar_employee(
        self, tenant_id: uuid.UUID, target_embedding: list[float], threshold: float
    ) -> Optional[Tuple[Employee, float]]:
        """
        Searches the registered employees database for matching visual features.
        """
        distance_limit = 1.0 - threshold
        similarity_expr = (1.0 - EmployeeEmbedding.embedding.cosine_distance(target_embedding)).label("similarity")

        stmt = (
            select(Employee, similarity_expr)
            .join(EmployeeEmbedding, EmployeeEmbedding.employee_id == Employee.id)
            .where(
                Employee.tenant_id == tenant_id,
                Employee.is_delete == False,
                Employee.is_active == True,
                EmployeeEmbedding.is_delete == False,
                EmployeeEmbedding.embedding.cosine_distance(target_embedding) <= distance_limit
            )
            .order_by(EmployeeEmbedding.embedding.cosine_distance(target_embedding))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.first()
        return (row[0], float(row[1])) if row else None

    async def get_employee_attendance_report(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> List[EmployeeAttendanceLog]:
        stmt = (
            select(EmployeeAttendanceLog)
            .join(PeopleAnalyticsSession, EmployeeAttendanceLog.session_id == PeopleAnalyticsSession.id)
            .options(selectinload(EmployeeAttendanceLog.employee))
            .where(
                EmployeeAttendanceLog.session_id == session_id,
                PeopleAnalyticsSession.tenant_id == tenant_id,
                EmployeeAttendanceLog.is_delete == False,
                PeopleAnalyticsSession.is_delete == False
            )
            .order_by(EmployeeAttendanceLog.first_seen.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_employee_attendance_by_date_range(
        self, tenant_id: uuid.UUID, start_date: object, end_date: object
    ) -> List[EmployeeAttendanceLog]:
        from datetime import datetime, time, timezone
        # Convert date objects to datetime boundaries in UTC
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)

        stmt = (
            select(EmployeeAttendanceLog)
            .join(Employee, EmployeeAttendanceLog.employee_id == Employee.id)
            .options(selectinload(EmployeeAttendanceLog.employee))
            .where(
                Employee.tenant_id == tenant_id,
                EmployeeAttendanceLog.employee_entry_timestamp >= start_dt,
                EmployeeAttendanceLog.employee_entry_timestamp <= end_dt,
                EmployeeAttendanceLog.is_delete == False,
                Employee.is_delete == False
            )
            .order_by(EmployeeAttendanceLog.employee_entry_timestamp.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_session_by_id(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PeopleAnalyticsSession]:
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.id == session_id,
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def log_employee_attendance(
        self,
        tenant_id: uuid.UUID,
        employee_id: uuid.UUID,
        session_id: Optional[uuid.UUID] = None,
        first_seen_sec: float = 0.0,
        last_seen_sec: float = 0.0,
        occurrence_increment: int = 1,
        entry_time: Optional[datetime] = None,
        exit_time: Optional[datetime] = None
    ) -> EmployeeAttendanceLog:
        """
        Registers or updates an employee attendance record for a calendar day (day-wise).
        """
        from datetime import datetime, time, timezone
        if entry_time is None:
            entry_time = datetime.now(timezone.utc)
        if exit_time is None:
            exit_time = entry_time

        # Get calendar day boundaries in UTC
        start_of_day = datetime.combine(entry_time.date(), time.min, tzinfo=timezone.utc)
        end_of_day = datetime.combine(entry_time.date(), time.max, tzinfo=timezone.utc)

        stmt = select(EmployeeAttendanceLog).where(
            EmployeeAttendanceLog.employee_id == employee_id,
            EmployeeAttendanceLog.employee_entry_timestamp >= start_of_day,
            EmployeeAttendanceLog.employee_entry_timestamp <= end_of_day,
            EmployeeAttendanceLog.is_delete == False
        )
        res = await self.db.execute(stmt)
        log = res.scalars().first()

        if log:
            # Update existing log for the day
            log.occurrence_count += occurrence_increment
            if first_seen_sec < log.first_seen:
                log.first_seen = first_seen_sec
            if last_seen_sec > log.last_seen:
                log.last_seen = last_seen_sec

            # Update entry/exit timestamps
            if entry_time < log.employee_entry_timestamp:
                log.employee_entry_timestamp = entry_time
            if exit_time > log.employee_exit_timestamp:
                log.employee_exit_timestamp = exit_time

            if session_id and not log.session_id:
                log.session_id = session_id

            await self.db.flush()
            return log
        else:
            # Create a new log for the day
            log = EmployeeAttendanceLog(
                session_id=session_id,
                employee_id=employee_id,
                first_seen=first_seen_sec,
                last_seen=last_seen_sec,
                occurrence_count=occurrence_increment,
                employee_entry_timestamp=entry_time,
                employee_exit_timestamp=exit_time
            )
            self.db.add(log)
            await self.db.flush()
            return log

    async def create_uploaded_video(
        self, tenant_id: uuid.UUID, original_name: str, saved_path: str, user_id: Optional[uuid.UUID] = None
    ) -> object:
        from modules.peopleanalytics.model import UploadedVideo
        uv = UploadedVideo(
            tenant_id=tenant_id,
            user_id=user_id,
            original_name=original_name,
            saved_path=saved_path
        )
        self.db.add(uv)
        await self.db.flush()
        return uv

    async def get_uploaded_video_by_name(self, tenant_id: uuid.UUID, original_name: str) -> Optional[object]:
        from modules.peopleanalytics.model import UploadedVideo
        stmt = select(UploadedVideo).where(
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.original_name == original_name,
            UploadedVideo.saved_path.like("%employee_attendance_inputs%"),
            UploadedVideo.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_uploaded_video_by_path(self, tenant_id: uuid.UUID, saved_path: str) -> Optional[object]:
        from modules.peopleanalytics.model import UploadedVideo
        stmt = select(UploadedVideo).where(
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.saved_path == saved_path,
            UploadedVideo.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_uploaded_videos(self, tenant_id: uuid.UUID) -> list:
        from modules.peopleanalytics.model import UploadedVideo
        stmt = select(UploadedVideo).where(
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.saved_path.like("%employee_attendance_inputs%"),
            UploadedVideo.is_delete == False
        ).order_by(UploadedVideo.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_uploaded_video_by_id(self, video_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[object]:
        from modules.peopleanalytics.model import UploadedVideo
        stmt = select(UploadedVideo).where(
            UploadedVideo.id == video_id,
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.saved_path.like("%employee_attendance_inputs%"),
            UploadedVideo.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def create_analytics_session(
        self,
        tenant_id: uuid.UUID,
        video_name: str,
        video_path: str,
        line_start: Optional[List[int]] = None,
        line_end: Optional[List[int]] = None,
        similarity_threshold: float = 0.85,
        confidence_threshold: float = 0.3
    ) -> object:
        from modules.peopleanalytics.model import PeopleAnalyticsSession
        session = PeopleAnalyticsSession(
            tenant_id=tenant_id,
            video_name=video_name,
            video_path=video_path,
            line_start=line_start,
            line_end=line_end,
            similarity_threshold=similarity_threshold,
            confidence_threshold=confidence_threshold,
            status="pending"
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_sessions(self, tenant_id: uuid.UUID, user_id: uuid.UUID) -> list:
        from modules.peopleanalytics.model import PeopleAnalyticsSession
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.video_path.like(f"%employee_attendance_inputs/{user_id}/%"),
            PeopleAnalyticsSession.is_delete == False
        ).order_by(PeopleAnalyticsSession.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

