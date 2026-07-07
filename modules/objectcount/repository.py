import uuid
from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from modules.objectcount.model import ObjectCountMedia, ObjectCountResult
from modules.gallery.model import GalleryMedia

class ObjectCountRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_analysis_session(
        self,
        tenant_id: uuid.UUID,
        gallery_media_id: uuid.UUID,
        classify_gender: bool = False,
        classify_vehicle: bool = False,
        classes_to_track: Optional[List[str]] = None
    ) -> ObjectCountMedia:
        """Create a new analysis session for object counting on a gallery media item."""
        media = ObjectCountMedia(
            tenant_id=tenant_id,
            gallery_media_id=gallery_media_id,
            classify_gender=classify_gender,
            classify_vehicle=classify_vehicle,
            classes_to_track=classes_to_track,
            status="pending"
        )
        self.db.add(media)
        await self.db.flush()
        return media

    async def get_media_by_id(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[ObjectCountMedia]:
        """Fetch media by ID, scoped to a tenant, with gallery_media eagerly loaded."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(ObjectCountMedia)
            .options(selectinload(ObjectCountMedia.gallery_media))
            .where(
                ObjectCountMedia.id == media_id,
                ObjectCountMedia.tenant_id == tenant_id,
                ObjectCountMedia.is_delete == False
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_media_with_results(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[ObjectCountMedia]:
        """Fetch media by ID with tracking results and gallery_media eagerly loaded, scoped to a tenant."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(ObjectCountMedia)
            .options(
                selectinload(ObjectCountMedia.results),
                selectinload(ObjectCountMedia.gallery_media)
            )
            .where(
                ObjectCountMedia.id == media_id,
                ObjectCountMedia.tenant_id == tenant_id,
                ObjectCountMedia.is_delete == False
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_media(self, tenant_id: uuid.UUID) -> List[ObjectCountMedia]:
        """Fetch all non-deleted analysis sessions for a tenant, with gallery_media loaded."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(ObjectCountMedia)
            .options(selectinload(ObjectCountMedia.gallery_media))
            .where(
                ObjectCountMedia.tenant_id == tenant_id,
                ObjectCountMedia.is_delete == False
            )
            .order_by(ObjectCountMedia.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_media(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[ObjectCountMedia]:
        """Soft delete analysis session and associated results."""
        stmt = select(ObjectCountMedia).where(
            ObjectCountMedia.id == media_id,
            ObjectCountMedia.tenant_id == tenant_id,
            ObjectCountMedia.is_delete == False
        )
        result = await self.db.execute(stmt)
        media = result.scalars().first()
        if media:
            media.is_delete = True
            stmt_results = (
                update(ObjectCountResult)
                .where(ObjectCountResult.media_id == media_id)
                .values(is_delete=True)
            )
            await self.db.execute(stmt_results)
            await self.db.flush()
        return media

    async def update_media_status(self, media_id: uuid.UUID, status: str) -> None:
        """Update processing status."""
        stmt = (
            update(ObjectCountMedia)
            .where(ObjectCountMedia.id == media_id)
            .values(status=status)
        )
        await self.db.execute(stmt)

    async def update_media_results(
        self,
        media_id: uuid.UUID,
        status: str,
        total_objects_count: int,
        peak_objects_count: int,
        average_objects_count: float,
        video_duration_seconds: Optional[float] = None,
        processed_filepath: Optional[str] = None,
        report_summary: Optional[dict] = None
    ) -> None:
        """Update metrics and status when analysis is complete, saving processed_filepath to GalleryMedia."""
        stmt = (
            update(ObjectCountMedia)
            .where(ObjectCountMedia.id == media_id)
            .values(
                status=status,
                total_objects_count=total_objects_count,
                peak_objects_count=peak_objects_count,
                average_objects_count=average_objects_count,
                video_duration_seconds=video_duration_seconds,
                report_summary=report_summary
            )
        )
        await self.db.execute(stmt)

        if processed_filepath:
            session_stmt = select(ObjectCountMedia.gallery_media_id).where(ObjectCountMedia.id == media_id)
            res = await self.db.execute(session_stmt)
            gallery_media_id = res.scalar()
            if gallery_media_id:
                gallery_stmt = (
                    update(GalleryMedia)
                    .where(GalleryMedia.id == gallery_media_id)
                    .values(processed_filepath=processed_filepath)
                )
                await self.db.execute(gallery_stmt)

    async def create_result(
        self,
        media_id: uuid.UUID,
        track_id: int,
        class_name: str,
        gender: Optional[str],
        first_frame: int,
        last_frame: int,
        total_frames: int,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None
    ) -> ObjectCountResult:
        """Create a track result entry."""
        result = ObjectCountResult(
            media_id=media_id,
            track_id=track_id,
            class_name=class_name,
            gender=gender,
            first_frame=first_frame,
            last_frame=last_frame,
            total_frames=total_frames,
            start_time=start_time,
            end_time=end_time
        )
        self.db.add(result)
        await self.db.flush()
        return result

    async def clear_results_by_media_id(self, media_id: uuid.UUID) -> None:
        """Delete previous results before starting a new analysis."""
        stmt = delete(ObjectCountResult).where(ObjectCountResult.media_id == media_id)
        await self.db.execute(stmt)

    async def get_results_by_media_id(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> List[ObjectCountResult]:
        """Fetch all results for a media, verifying tenant scoping."""
        stmt = (
            select(ObjectCountResult)
            .join(ObjectCountMedia, ObjectCountResult.media_id == ObjectCountMedia.id)
            .where(
                ObjectCountResult.media_id == media_id,
                ObjectCountMedia.tenant_id == tenant_id,
                ObjectCountResult.is_delete == False,
                ObjectCountMedia.is_delete == False
            )
            .order_by(ObjectCountResult.track_id.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
