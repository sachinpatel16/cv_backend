import uuid
from typing import List, Optional, Tuple
from sqlalchemy import select, update
from sqlalchemy.orm import selectinload

from modules.peopleanalytics.repository import PeopleAnalyticsRepository
from modules.peopleanalytics.model import (
    UploadedVideo,
    PeopleAnalyticsSession,
    PersonOccurrence,
    LineCrossingLog,
    EmployeeAttendanceLog,
    PersonIdentity
)

class FaceAnalyticsRepository(PeopleAnalyticsRepository):
    async def get_uploaded_video_by_id(self, video_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[UploadedVideo]:
        stmt = select(UploadedVideo).where(
            UploadedVideo.id == video_id,
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.saved_path.like("%face_analytics_inputs%"),
            UploadedVideo.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_uploaded_video_by_name(self, tenant_id: uuid.UUID, original_name: str) -> Optional[UploadedVideo]:
        stmt = select(UploadedVideo).where(
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.original_name == original_name,
            UploadedVideo.saved_path.like("%face_analytics_inputs%"),
            UploadedVideo.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_uploaded_videos(self, tenant_id: uuid.UUID) -> List[UploadedVideo]:
        stmt = select(UploadedVideo).where(
            UploadedVideo.tenant_id == tenant_id,
            UploadedVideo.saved_path.like("%face_analytics_inputs%"),
            UploadedVideo.is_delete == False
        ).order_by(UploadedVideo.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_session_by_id(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PeopleAnalyticsSession]:
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.id == session_id,
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.video_path.like("%face_analytics_inputs%"),
            PeopleAnalyticsSession.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_sessions(self, tenant_id: uuid.UUID) -> List[PeopleAnalyticsSession]:
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.video_path.like("%face_analytics_inputs%"),
            PeopleAnalyticsSession.is_delete == False
        ).order_by(PeopleAnalyticsSession.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_session(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Tuple[str, Optional[str], List[str]]]:
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.id == session_id,
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.video_path.like("%face_analytics_inputs%"),
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

    async def get_session_first_time_visitors(self, session_id: uuid.UUID) -> List[PersonOccurrence]:
        """
        Retrieves all PersonOccurrence records in the given session for identities 
        whose very first appearance across all sessions is in this session.
        """
        # 1. Get all occurrences in this session
        stmt = select(PersonOccurrence).where(
            PersonOccurrence.session_id == session_id,
            PersonOccurrence.is_delete == False
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

    async def find_similar_visitor(
        self, tenant_id: uuid.UUID, target_embedding: list[float], threshold: float, class_id: Optional[int] = 1
    ) -> Optional[Tuple[PersonIdentity, float]]:
        """
        Overridden to automatically search face-only visitor identities (class_id=1) by default.
        """
        return await super().find_similar_visitor(tenant_id, target_embedding, threshold, class_id=class_id)

