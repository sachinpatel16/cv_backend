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
    PersonIdentity,
    EmployeeSessionDetection
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
            stmt_det = update(EmployeeSessionDetection).where(EmployeeSessionDetection.session_id == session_id).values(is_delete=True)
            await self.db.execute(stmt_occ)
            await self.db.execute(stmt_crs)
            await self.db.execute(stmt_att)
            await self.db.execute(stmt_det)
            await self.db.flush()
            return session.video_path, session.output_video_path, crop_paths
        return None



    async def find_similar_visitor(
        self, tenant_id: uuid.UUID, target_embedding: list[float], threshold: float, class_id: Optional[int] = 1
    ) -> Optional[Tuple[PersonIdentity, float]]:
        """
        Overridden to automatically search face-only visitor identities (class_id=1) by default.
        """
        return await super().find_similar_visitor(tenant_id, target_embedding, threshold, class_id=class_id)

