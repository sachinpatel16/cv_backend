import uuid
from typing import List, Optional
from sqlalchemy import select, update, delete
from sqlalchemy.ext.asyncio import AsyncSession
from modules.peoplecount.model import PeopleCountMedia, PeopleCountResult
from modules.gallery.model import GalleryMedia

class PeopleCountRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_analysis_session(
        self, tenant_id: uuid.UUID, gallery_media_id: uuid.UUID
    ) -> PeopleCountMedia:
        """Create a new people counting analysis session on a gallery media item."""
        media = PeopleCountMedia(
            tenant_id=tenant_id,
            gallery_media_id=gallery_media_id,
            status="pending"
        )
        self.db.add(media)
        await self.db.flush()
        return media

    async def get_media_by_id(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PeopleCountMedia]:
        """Fetch analysis session by ID, scoped to a tenant, loading gallery_media."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(PeopleCountMedia)
            .options(selectinload(PeopleCountMedia.gallery_media))
            .where(
                PeopleCountMedia.id == media_id,
                PeopleCountMedia.tenant_id == tenant_id,
                PeopleCountMedia.is_delete == False
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_media_with_results(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PeopleCountMedia]:
        """Fetch analysis session by ID with tracking results and gallery_media eagerly loaded, scoped to a tenant."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(PeopleCountMedia)
            .options(
                selectinload(PeopleCountMedia.results),
                selectinload(PeopleCountMedia.gallery_media)
            )
            .where(
                PeopleCountMedia.id == media_id,
                PeopleCountMedia.tenant_id == tenant_id,
                PeopleCountMedia.is_delete == False
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_media(self, tenant_id: uuid.UUID) -> List[PeopleCountMedia]:
        """Fetch all non-deleted analysis sessions for a tenant, loading gallery_media."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(PeopleCountMedia)
            .options(selectinload(PeopleCountMedia.gallery_media))
            .where(
                PeopleCountMedia.tenant_id == tenant_id,
                PeopleCountMedia.is_delete == False
            )
            .order_by(PeopleCountMedia.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_media(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PeopleCountMedia]:
        """Soft delete analysis session and associated results."""
        stmt = select(PeopleCountMedia).where(
            PeopleCountMedia.id == media_id,
            PeopleCountMedia.tenant_id == tenant_id,
            PeopleCountMedia.is_delete == False
        )
        result = await self.db.execute(stmt)
        media = result.scalars().first()
        if media:
            media.is_delete = True
            stmt_results = (
                update(PeopleCountResult)
                .where(PeopleCountResult.media_id == media_id)
                .values(is_delete=True)
            )
            await self.db.execute(stmt_results)
            await self.db.flush()
        return media

    async def update_media_status(self, media_id: uuid.UUID, status: str) -> None:
        """Update processing status."""
        stmt = (
            update(PeopleCountMedia)
            .where(PeopleCountMedia.id == media_id)
            .values(status=status)
        )
        await self.db.execute(stmt)

    async def update_media_results(
        self,
        media_id: uuid.UUID,
        status: str,
        total_people_count: int,
        peak_people_count: int,
        average_people_count: float,
        video_duration_seconds: Optional[float] = None,
        processed_filepath: Optional[str] = None
    ) -> None:
        """Update metrics and status when analysis is complete, saving processed_filepath to GalleryMedia."""
        stmt = (
            update(PeopleCountMedia)
            .where(PeopleCountMedia.id == media_id)
            .values(
                status=status,
                total_people_count=total_people_count,
                peak_people_count=peak_people_count,
                average_people_count=average_people_count,
                video_duration_seconds=video_duration_seconds
            )
        )
        await self.db.execute(stmt)

        if processed_filepath:
            session_stmt = select(PeopleCountMedia.gallery_media_id).where(PeopleCountMedia.id == media_id)
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
        first_frame: int,
        last_frame: int,
        total_frames: int,
        start_time: Optional[float] = None,
        end_time: Optional[float] = None,
        class_name: str = "person"
    ) -> PeopleCountResult:
        """Create a track result entry."""
        result = PeopleCountResult(
            media_id=media_id,
            track_id=track_id,
            first_frame=first_frame,
            last_frame=last_frame,
            total_frames=total_frames,
            start_time=start_time,
            end_time=end_time,
            class_name=class_name
        )
        self.db.add(result)
        await self.db.flush()
        return result

    async def clear_results_by_media_id(self, media_id: uuid.UUID) -> None:
        """Delete previous results before starting a new analysis."""
        stmt = delete(PeopleCountResult).where(PeopleCountResult.media_id == media_id)
        await self.db.execute(stmt)

    async def get_results_by_media_id(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> List[PeopleCountResult]:
        """Fetch all results for a media, verifying tenant scoping."""
        stmt = (
            select(PeopleCountResult)
            .join(PeopleCountMedia, PeopleCountResult.media_id == PeopleCountMedia.id)
            .where(
                PeopleCountResult.media_id == media_id,
                PeopleCountMedia.tenant_id == tenant_id,
                PeopleCountResult.is_delete == False,
                PeopleCountMedia.is_delete == False
            )
            .order_by(PeopleCountResult.track_id.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
