import uuid
from typing import List, Tuple, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from modules.peoplefind.model import MediaSource, FaceEmbedding, FaceSearchSession, FaceSearchResult

class PeopleFindRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_media_source(
        self, tenant_id: uuid.UUID, filename: str, filepath: str, media_type: str
    ) -> MediaSource:
        """Create a new media source entry (photo or video)."""
        media = MediaSource(
            tenant_id=tenant_id,
            filename=filename,
            filepath=filepath,
            media_type=media_type,
            status="pending"
        )
        self.db.add(media)
        await self.db.flush()
        return media

    async def get_media_source_by_id(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[MediaSource]:
        """Fetch media source by ID, scoped to a specific tenant."""
        stmt = select(MediaSource).where(
            MediaSource.id == media_id,
            MediaSource.tenant_id == tenant_id,
            MediaSource.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_media_source_by_filename(self, filename: str, tenant_id: uuid.UUID) -> Optional[MediaSource]:
        """Fetch media source by filename and tenant, scoped to active tenant."""
        stmt = select(MediaSource).where(
            MediaSource.filename == filename,
            MediaSource.tenant_id == tenant_id,
            MediaSource.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_media_sources(self, tenant_id: uuid.UUID) -> List[MediaSource]:
        """Fetch all non-deleted media sources for a specific tenant, sorted by creation time."""
        stmt = (
            select(MediaSource)
            .where(
                MediaSource.tenant_id == tenant_id,
                MediaSource.is_delete == False
            )
            .order_by(MediaSource.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_media_source(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[MediaSource]:
        """Soft delete a media source and its associated faces, scoped to tenant."""
        stmt = select(MediaSource).where(
            MediaSource.id == media_id,
            MediaSource.tenant_id == tenant_id,
            MediaSource.is_delete == False
        )
        result = await self.db.execute(stmt)
        media = result.scalars().first()
        if media:
            media.is_delete = True
            stmt_faces = (
                update(FaceEmbedding)
                .where(FaceEmbedding.media_source_id == media_id)
                .values(is_delete=True)
            )
            await self.db.execute(stmt_faces)
            await self.db.flush()
        return media

    async def update_media_source_status(self, media_id: uuid.UUID, status: str) -> None:
        """Update indexing status of a media source."""
        stmt = (
            update(MediaSource)
            .where(MediaSource.id == media_id)
            .values(status=status)
        )
        await self.db.execute(stmt)

    async def create_face_embedding(
        self, media_source_id: uuid.UUID, face_idx: int, bbox: list[int], embedding: list[float], timestamp: Optional[float] = None
    ) -> FaceEmbedding:
        """Store face coordinates and vector embedding for a detected face."""
        face = FaceEmbedding(
            media_source_id=media_source_id,
            face_idx=face_idx,
            bbox=bbox,
            embedding=embedding,
            timestamp=timestamp
        )
        self.db.add(face)
        await self.db.flush()
        return face

    async def create_search_session(
        self, tenant_id: uuid.UUID, selfie_path: str, selfie_embedding: list[float], threshold: float, user_id: Optional[uuid.UUID] = None
    ) -> FaceSearchSession:
        """Create a new search session record."""
        session = FaceSearchSession(
            tenant_id=tenant_id,
            user_id=user_id,
            selfie_path=selfie_path,
            selfie_embedding=selfie_embedding,
            threshold=threshold,
            status="pending"
        )
        self.db.add(session)
        await self.db.flush()
        return session

    async def get_search_session_by_id(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[FaceSearchSession]:
        """Fetch search session by ID, scoped to tenant."""
        stmt = select(FaceSearchSession).where(
            FaceSearchSession.id == session_id,
            FaceSearchSession.tenant_id == tenant_id,
            FaceSearchSession.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_search_session_with_results(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[FaceSearchSession]:
        """Fetch search session by ID with results and media sources eagerly loaded, scoped to tenant."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(FaceSearchSession)
            .options(
                selectinload(FaceSearchSession.results).selectinload(FaceSearchResult.media_source)
            )
            .where(
                FaceSearchSession.id == session_id,
                FaceSearchSession.tenant_id == tenant_id,
                FaceSearchSession.is_delete == False
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_search_sessions_history(
        self, tenant_id: uuid.UUID, user_id: Optional[uuid.UUID] = None
    ) -> List[FaceSearchSession]:
        """Fetch all non-deleted search sessions for a specific tenant, eagerly loading user, results, and media sources."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(FaceSearchSession)
            .options(
                selectinload(FaceSearchSession.user),
                selectinload(FaceSearchSession.results).selectinload(FaceSearchResult.media_source)
            )
            .where(
                FaceSearchSession.tenant_id == tenant_id,
                FaceSearchSession.is_delete == False
            )
        )
        if user_id is not None:
            stmt = stmt.where(FaceSearchSession.user_id == user_id)
        stmt = stmt.order_by(FaceSearchSession.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_search_session_status(self, session_id: uuid.UUID, status: str) -> None:
        """Update matching status of a search session."""
        stmt = (
            update(FaceSearchSession)
            .where(FaceSearchSession.id == session_id)
            .values(status=status)
        )
        await self.db.execute(stmt)

    async def create_search_result(
        self, session_id: uuid.UUID, media_source_id: uuid.UUID, similarity: float, bbox: list[int], timestamp: Optional[float] = None
    ) -> FaceSearchResult:
        """Create a search match result entry."""
        result = FaceSearchResult(
            session_id=session_id,
            media_source_id=media_source_id,
            similarity=similarity,
            bbox=bbox,
            timestamp=timestamp
        )
        self.db.add(result)
        await self.db.flush()
        return result

    async def find_similar_faces(
        self, tenant_id: uuid.UUID, target_embedding: list[float], threshold: float
    ) -> List[Tuple[FaceEmbedding, float]]:
        """
        Queries all FaceEmbeddings using pgvector's cosine distance.
        Filters by threshold (similarity >= threshold) and scopes results to the active tenant.
        """
        # Cosine distance in pgvector is between 0 and 2.
        # similarity = 1 - cosine_distance.
        # similarity >= threshold  -->  cosine_distance <= 1 - threshold
        distance_limit = 1.0 - threshold
        
        # Define similarity expression
        similarity_expr = (1.0 - FaceEmbedding.embedding.cosine_distance(target_embedding)).label("similarity")

        stmt = (
            select(FaceEmbedding, similarity_expr)
            .join(MediaSource, FaceEmbedding.media_source_id == MediaSource.id)
            .where(
                MediaSource.tenant_id == tenant_id,
                MediaSource.is_delete == False,
                FaceEmbedding.is_delete == False,
                FaceEmbedding.embedding.cosine_distance(target_embedding) <= distance_limit
            )
            .order_by(FaceEmbedding.embedding.cosine_distance(target_embedding))
        )
        
        result = await self.db.execute(stmt)
        # Returns list of tuples: (FaceEmbedding, similarity_score)
        return [(row[0], float(row[1])) for row in result.all()]

    async def get_session_results(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> List[FaceSearchResult]:
        """Fetch all matched results for a given search session."""
        from sqlalchemy.orm import selectinload
        stmt = (
            select(FaceSearchResult)
            .join(FaceSearchSession, FaceSearchResult.session_id == FaceSearchSession.id)
            .join(MediaSource, FaceSearchResult.media_source_id == MediaSource.id)
            .options(
                selectinload(FaceSearchResult.media_source)
            )
            .where(
                FaceSearchResult.session_id == session_id,
                FaceSearchSession.tenant_id == tenant_id,
                FaceSearchResult.is_delete == False,
                MediaSource.is_delete == False
            )
            .order_by(FaceSearchResult.similarity.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())



    async def bulk_delete_media_sources(self, tenant_id: uuid.UUID) -> List[str]:
        """Soft delete all media sources and return their filepaths for physical deletion."""
        stmt = select(MediaSource).where(
            MediaSource.tenant_id == tenant_id,
            MediaSource.is_delete == False
        )
        result = await self.db.execute(stmt)
        media_sources = list(result.scalars().all())
        
        filepaths = []
        for media in media_sources:
            media.is_delete = True
            filepaths.append(media.filepath)
            
        if media_sources:
            media_ids = [m.id for m in media_sources]
            stmt_faces = (
                update(FaceEmbedding)
                .where(FaceEmbedding.media_source_id.in_(media_ids))
                .values(is_delete=True)
            )
            await self.db.execute(stmt_faces)
            await self.db.flush()
            
        return filepaths
