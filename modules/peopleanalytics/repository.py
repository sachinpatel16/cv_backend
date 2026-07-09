import uuid
from typing import List, Tuple, Optional
from datetime import datetime, timedelta
from sqlalchemy import select, update, func, and_
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.peopleanalytics.model import (
    PeopleAnalyticsSession,
    EmployeeAttendanceLog,
    PersonIdentity,
    PersonEmbedding,
    PersonOccurrence,
    LineCrossingLog,
    UploadedVideo,
    VisitorAttendanceLog,
    EmployeeSessionDetection
)
from modules.employees.model import Employee, EmployeeEmbedding

class PeopleAnalyticsRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ==========================================
    # UPLOADED VIDEO OPERATIONS
    # ==========================================

    async def create_uploaded_video(
        self, tenant_id: uuid.UUID, original_name: str, saved_path: str, user_id: Optional[uuid.UUID] = None
    ) -> UploadedVideo:
        uv = UploadedVideo(
            tenant_id=tenant_id,
            user_id=user_id,
            original_name=original_name,
            saved_path=saved_path
        )
        self.db.add(uv)
        await self.db.flush()
        return uv

    async def get_uploaded_video_by_id(self, video_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[UploadedVideo]:
        stmt = select(UploadedVideo).where(
            UploadedVideo.id == video_id,
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.saved_path.like("%people_analytics_inputs%"),
            UploadedVideo.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_uploaded_video_by_name(self, tenant_id: uuid.UUID, original_name: str) -> Optional[UploadedVideo]:
        stmt = select(UploadedVideo).where(
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.original_name == original_name,
            UploadedVideo.saved_path.like("%people_analytics_inputs%"),
            UploadedVideo.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_uploaded_video_by_path(self, tenant_id: uuid.UUID, saved_path: str) -> Optional[UploadedVideo]:
        stmt = select(UploadedVideo).where(
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.saved_path == saved_path,
            UploadedVideo.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def soft_delete_uploaded_video(self, video: UploadedVideo) -> None:
        video.is_delete = True
        await self.db.flush()

    async def get_all_uploaded_videos(self, tenant_id: uuid.UUID) -> List[UploadedVideo]:
        stmt = select(UploadedVideo).where(
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.saved_path.like("%people_analytics_inputs%"),
            UploadedVideo.is_delete == False
        ).order_by(UploadedVideo.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ==========================================
    # VISITOR / IDENTITY OPERATIONS
    # ==========================================

    async def create_person_identity(self, tenant_id: uuid.UUID, class_id: int = 0) -> PersonIdentity:
        identity = PersonIdentity(tenant_id=tenant_id, class_id=class_id)
        self.db.add(identity)
        await self.db.flush()
        return identity

    async def create_person_embedding(
        self, identity_id: uuid.UUID, embedding: list[float], bbox: Optional[list[int]] = None, timestamp: Optional[float] = None
    ) -> PersonEmbedding:
        pe = PersonEmbedding(
            identity_id=identity_id,
            embedding=embedding,
            bbox=bbox,
            timestamp=timestamp
        )
        self.db.add(pe)
        await self.db.flush()
        return pe

    async def create_person_occurrence(
        self, session_id: uuid.UUID, identity_id: uuid.UUID, tracker_id: int, first_seen: float, last_seen: float, crop_path: Optional[str] = None
    ) -> PersonOccurrence:
        occurrence = PersonOccurrence(
            session_id=session_id,
            identity_id=identity_id,
            tracker_id=tracker_id,
            first_seen=first_seen,
            last_seen=last_seen,
            crop_path=crop_path
        )
        self.db.add(occurrence)
        await self.db.flush()
        return occurrence

    async def create_line_crossing(
        self, session_id: uuid.UUID, identity_id: uuid.UUID, tracker_id: int, timestamp: float, direction: str
    ) -> LineCrossingLog:
        log = LineCrossingLog(
            session_id=session_id,
            identity_id=identity_id,
            tracker_id=tracker_id,
            timestamp=timestamp,
            direction=direction
        )
        self.db.add(log)
        await self.db.flush()
        return log

    async def create_employee_attendance(
        self,
        session_id: uuid.UUID,
        employee_id: uuid.UUID,
        first_seen: float,
        last_seen: float,
        occurrence_count: int = 1,
        entry_time: Optional[datetime] = None,
        exit_time: Optional[datetime] = None
    ) -> EmployeeAttendanceLog:
        from datetime import time, timezone
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
            log.occurrence_count += occurrence_count
            if first_seen < log.first_seen:
                log.first_seen = first_seen
            if last_seen > log.last_seen:
                log.last_seen = last_seen

            # Update entry/exit timestamps
            if entry_time < log.employee_entry_timestamp:
                log.employee_entry_timestamp = entry_time
            if exit_time > log.employee_exit_timestamp:
                log.employee_exit_timestamp = exit_time

            if session_id and not log.session_id:
                log.session_id = session_id
        else:
            # Create a new log for the day
            log = EmployeeAttendanceLog(
                session_id=session_id,
                employee_id=employee_id,
                first_seen=first_seen,
                last_seen=last_seen,
                occurrence_count=occurrence_count,
                employee_entry_timestamp=entry_time,
                employee_exit_timestamp=exit_time
            )
            self.db.add(log)

        # Log/Update employee session detection
        if session_id:
            stmt_det = select(EmployeeSessionDetection).where(
                EmployeeSessionDetection.session_id == session_id,
                EmployeeSessionDetection.employee_id == employee_id,
                EmployeeSessionDetection.is_delete == False
            )
            res_det = await self.db.execute(stmt_det)
            det = res_det.scalars().first()
            if det:
                det.occurrence_count += occurrence_count
                if first_seen < det.first_seen:
                    det.first_seen = first_seen
                if last_seen > det.last_seen:
                    det.last_seen = last_seen
            else:
                det = EmployeeSessionDetection(
                    session_id=session_id,
                    employee_id=employee_id,
                    first_seen=first_seen,
                    last_seen=last_seen,
                    occurrence_count=occurrence_count
                )
                self.db.add(det)

        await self.db.flush()
        return log

    async def log_visitor_attendance(
        self,
        session_id: Optional[uuid.UUID],
        identity_id: uuid.UUID,
        first_seen_sec: float = 0.0,
        last_seen_sec: float = 0.0,
        occurrence_increment: int = 1,
        entry_time: Optional[datetime] = None,
        exit_time: Optional[datetime] = None
    ) -> VisitorAttendanceLog:
        """
        Registers or updates a visitor attendance record for a calendar day (day-wise).
        """
        from datetime import time, timezone
        if entry_time is None:
            entry_time = datetime.now(timezone.utc)
        if exit_time is None:
            exit_time = entry_time

        # Get calendar day boundaries in UTC
        start_of_day = datetime.combine(entry_time.date(), time.min, tzinfo=timezone.utc)
        end_of_day = datetime.combine(entry_time.date(), time.max, tzinfo=timezone.utc)

        stmt = select(VisitorAttendanceLog).where(
            VisitorAttendanceLog.identity_id == identity_id,
            VisitorAttendanceLog.visitor_entry_timestamp >= start_of_day,
            VisitorAttendanceLog.visitor_entry_timestamp <= end_of_day,
            VisitorAttendanceLog.is_delete == False
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
            if entry_time < log.visitor_entry_timestamp:
                log.visitor_entry_timestamp = entry_time
            if exit_time > log.visitor_exit_timestamp:
                log.visitor_exit_timestamp = exit_time

            if session_id and not log.session_id:
                log.session_id = session_id

            await self.db.flush()
            return log
        else:
            # Create a new log for the day
            log = VisitorAttendanceLog(
                session_id=session_id,
                identity_id=identity_id,
                first_seen=first_seen_sec,
                last_seen=last_seen_sec,
                occurrence_count=occurrence_increment,
                visitor_entry_timestamp=entry_time,
                visitor_exit_timestamp=exit_time
            )
            self.db.add(log)
            await self.db.flush()
            return log

    async def get_visitor_attendance_by_date_range(
        self, tenant_id: uuid.UUID, start_date: object, end_date: object
    ) -> List[VisitorAttendanceLog]:
        from datetime import datetime, time, timezone
        # Convert date objects to datetime boundaries in UTC
        start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
        end_dt = datetime.combine(end_date, time.max, tzinfo=timezone.utc)

        stmt = (
            select(VisitorAttendanceLog)
            .options(
                selectinload(VisitorAttendanceLog.identity)
                .selectinload(PersonIdentity.occurrences)
            )
            .join(PersonIdentity, VisitorAttendanceLog.identity_id == PersonIdentity.id)
            .where(
                PersonIdentity.tenant_id == tenant_id,
                VisitorAttendanceLog.visitor_entry_timestamp >= start_dt,
                VisitorAttendanceLog.visitor_entry_timestamp <= end_dt,
                VisitorAttendanceLog.is_delete == False,
                PersonIdentity.is_delete == False
            )
            .order_by(VisitorAttendanceLog.visitor_entry_timestamp.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    # ==========================================
    # SIMILARITY VECTOR SEARCH (pgvector)
    # ==========================================

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

    async def find_similar_visitor(
        self, tenant_id: uuid.UUID, target_embedding: list[float], threshold: float, class_id: Optional[int] = 0
    ) -> Optional[Tuple[PersonIdentity, float]]:
        """
        Searches the generic visitor identities for matching visual features, optionally filtered by class_id.
        """
        distance_limit = 1.0 - threshold
        similarity_expr = (1.0 - PersonEmbedding.embedding.cosine_distance(target_embedding)).label("similarity")

        conditions = [
            PersonIdentity.tenant_id == tenant_id,
            PersonIdentity.is_delete == False,
            PersonEmbedding.is_delete == False,
            PersonEmbedding.embedding.cosine_distance(target_embedding) <= distance_limit
        ]
        if class_id is not None:
            conditions.append(PersonIdentity.class_id == class_id)

        stmt = (
            select(PersonIdentity, similarity_expr)
            .join(PersonEmbedding, PersonEmbedding.identity_id == PersonIdentity.id)
            .where(and_(*conditions))
            .order_by(PersonEmbedding.embedding.cosine_distance(target_embedding))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.first()
        return (row[0], float(row[1])) if row else None


    # ==========================================
    # SESSION OPERATIONS
    # ==========================================

    async def create_analytics_session(
        self,
        tenant_id: uuid.UUID,
        video_name: str,
        video_path: str,
        line_start: Optional[list[int]] = None,
        line_end: Optional[list[int]] = None,
        similarity_threshold: float = 0.82,
        confidence_threshold: float = 0.3
    ) -> PeopleAnalyticsSession:
        session = PeopleAnalyticsSession(
            tenant_id=tenant_id,
            video_name=video_name,
            video_path=video_path,
            status="pending",
            session_type="people_analytics",
            line_start=line_start,
            line_end=line_end,
            similarity_threshold=similarity_threshold,
            confidence_threshold=confidence_threshold
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_session_by_id(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PeopleAnalyticsSession]:
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.id == session_id,
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.session_type == "people_analytics",
            PeopleAnalyticsSession.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_sessions(self, tenant_id: uuid.UUID) -> List[PeopleAnalyticsSession]:
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.session_type == "people_analytics",
            PeopleAnalyticsSession.is_delete == False
        ).order_by(PeopleAnalyticsSession.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_session(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Tuple[str, Optional[str], List[str]]]:
        """
        Soft deletes session and returns physical paths to delete.
        """
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.id == session_id,
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.is_delete == False
        )
        res = await self.db.execute(stmt)
        session = res.scalars().first()
        if session:
            # Retrieve visitor crops to delete
            stmt_crops = select(PersonOccurrence.crop_path).where(
                PersonOccurrence.session_id == session_id,
                PersonOccurrence.is_delete == False
            )
            res_crops = await self.db.execute(stmt_crops)
            crop_paths = [p for p in res_crops.scalars().all() if p]

            session.is_delete = True
            
            # Soft delete child logs
            stmt_occ = update(PersonOccurrence).where(PersonOccurrence.session_id == session_id).values(is_delete=True)
            stmt_crs = update(LineCrossingLog).where(LineCrossingLog.session_id == session_id).values(is_delete=True)
            stmt_det = update(EmployeeSessionDetection).where(EmployeeSessionDetection.session_id == session_id).values(is_delete=True)
            await self.db.execute(stmt_occ)
            await self.db.execute(stmt_crs)
            await self.db.execute(stmt_det)
            await self.db.flush()
            return session.video_path, session.output_video_path, crop_paths
        return None

    async def get_session_occurrences(self, session_id: uuid.UUID) -> List[PersonOccurrence]:
        stmt = select(PersonOccurrence).where(
            PersonOccurrence.session_id == session_id,
            PersonOccurrence.is_delete == False
        ).options(
            selectinload(PersonOccurrence.identity)
        ).order_by(PersonOccurrence.first_seen.asc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

    async def get_session_first_time_visitors(self, session_id: uuid.UUID) -> List[PersonOccurrence]:
        """
        Retrieves all PersonOccurrence records in the given session for identities 
        whose very first appearance across all sessions is in this session.
        """
        # 1. Get all occurrences in this session
        stmt = select(PersonOccurrence).where(
            PersonOccurrence.session_id == session_id,
            PersonOccurrence.is_delete == False
        ).options(
            selectinload(PersonOccurrence.identity)
        )
        res = await self.db.execute(stmt)
        occurrences = list(res.scalars().all())
        
        if not occurrences:
            return []
            
        # 2. Extract unique identity IDs
        identity_ids = list(set(occ.identity_id for occ in occurrences))
        
        # 3. Get the current session's creation time to compare
        curr_session_stmt = select(PeopleAnalyticsSession).where(PeopleAnalyticsSession.id == session_id)
        curr_session_res = await self.db.execute(curr_session_stmt)
        curr_session = curr_session_res.scalars().first()
        if not curr_session:
            return []
            
        # 4. Find which of these identities appeared in any session created BEFORE this session
        stmt_older = (
            select(PersonOccurrence.identity_id)
            .join(PeopleAnalyticsSession, PersonOccurrence.session_id == PeopleAnalyticsSession.id)
            .where(
                PersonOccurrence.identity_id.in_(identity_ids),
                PeopleAnalyticsSession.created_at < curr_session.created_at,
                PersonOccurrence.is_delete == False,
                PeopleAnalyticsSession.is_delete == False
            )
        )
        res_older = await self.db.execute(stmt_older)
        older_identity_ids = set(res_older.scalars().all())
        
        # 5. Filter occurrences to only those whose identity has no older appearances
        first_time_occs = [occ for occ in occurrences if occ.identity_id not in older_identity_ids]
        return first_time_occs


    async def update_session_status(self, session_id: uuid.UUID, status: str) -> None:
        stmt = update(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.id == session_id
        ).values(status=status)
        await self.db.execute(stmt)

    async def update_session_results(
        self,
        session_id: uuid.UUID,
        unique_person_count: int,
        total_person_count: int,
        first_time_visitor_count: int,
        peak_occupancy: int,
        average_occupancy: float,
        entry_count: int,
        exit_count: int,
        occupancy_timeline: List[dict],
        output_video_path: Optional[str] = None
    ) -> None:
        stmt = update(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.id == session_id
        ).values(
            status="completed",
            unique_person_count=unique_person_count,
            total_person_count=total_person_count,
            first_time_visitor_count=first_time_visitor_count,
            peak_occupancy=peak_occupancy,
            average_occupancy=average_occupancy,
            entry_count=entry_count,
            exit_count=exit_count,
            occupancy_timeline=occupancy_timeline,
            output_video_path=output_video_path,
            completed_at=datetime.utcnow()
        )
        await self.db.execute(stmt)

    # ==========================================
    # ANALYTICS REPORTS QUERIES
    # ==========================================


    async def get_visitor_dashboard_metrics(self, tenant_id: uuid.UUID) -> Tuple[int, int, float, int]:
        """
        Calculates aggregate statistics for the Visitor Report Dashboard:
        - Total Unique People
        - Repeat Visitors Count
        - Repeat Visitor Rate
        - New Visitors This Month
        """
        # 1. Total Unique Visitor Identities
        stmt_tot = select(func.count(PersonIdentity.id)).where(
            PersonIdentity.tenant_id == tenant_id,
            PersonIdentity.is_delete == False
        )
        res_tot = await self.db.execute(stmt_tot)
        total_unique = res_tot.scalar() or 0

        # 2. Repeat Visitors Count (person identities with >1 distinct tracking occurrences)
        stmt_rep = (
            select(func.count(func.distinct(PersonOccurrence.identity_id)))
            .join(PersonIdentity, PersonOccurrence.identity_id == PersonIdentity.id)
            .where(
                PersonIdentity.tenant_id == tenant_id,
                PersonIdentity.is_delete == False,
                PersonOccurrence.is_delete == False
            )
            .group_by(PersonOccurrence.identity_id)
            .having(func.count(PersonOccurrence.id) > 1)
        )
        res_rep = await self.db.execute(stmt_rep)
        repeat_visitors = len(res_rep.all())

        # 3. Repeat Visitor Rate
        repeat_rate = (repeat_visitors / total_unique * 100.0) if total_unique > 0 else 0.0

        # 4. New Visitors This Month
        thirty_days_ago = datetime.utcnow() - timedelta(days=30)
        stmt_new = select(func.count(PersonIdentity.id)).where(
            PersonIdentity.tenant_id == tenant_id,
            PersonIdentity.is_delete == False,
            PersonIdentity.created_at >= thirty_days_ago
        )
        res_new = await self.db.execute(stmt_new)
        new_this_month = res_new.scalar() or 0

        return total_unique, repeat_visitors, round(repeat_rate, 2), new_this_month
