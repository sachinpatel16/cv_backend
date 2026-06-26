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
    UploadedVideo
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
        self, session_id: uuid.UUID, employee_id: uuid.UUID, first_seen: float, last_seen: float, occurrence_count: int = 1
    ) -> EmployeeAttendanceLog:
        log = EmployeeAttendanceLog(
            session_id=session_id,
            employee_id=employee_id,
            first_seen=first_seen,
            last_seen=last_seen,
            occurrence_count=occurrence_count
        )
        self.db.add(log)
        await self.db.flush()
        return log

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
            PeopleAnalyticsSession.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_sessions(self, tenant_id: uuid.UUID) -> List[PeopleAnalyticsSession]:
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.tenant_id == tenant_id,
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
            stmt_att = update(EmployeeAttendanceLog).where(EmployeeAttendanceLog.session_id == session_id).values(is_delete=True)
            await self.db.execute(stmt_occ)
            await self.db.execute(stmt_crs)
            await self.db.execute(stmt_att)
            await self.db.flush()
            return session.video_path, session.output_video_path, crop_paths
        return None

    async def get_session_occurrences(self, session_id: uuid.UUID) -> List[PersonOccurrence]:
        stmt = select(PersonOccurrence).where(
            PersonOccurrence.session_id == session_id,
            PersonOccurrence.is_delete == False
        ).order_by(PersonOccurrence.first_seen.asc())
        res = await self.db.execute(stmt)
        return list(res.scalars().all())

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
