import uuid
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from modules.smokingdetect.model import SmokingSession, SmokingEvent


class SmokingDetectRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    # ------------------------------------------------------------------
    # SmokingSession CRUD
    # ------------------------------------------------------------------

    async def create_session(
        self,
        db: AsyncSession,
        user_id: Optional[uuid.UUID],
        tenant_id: str,
        media_id: Optional[uuid.UUID],
        interval: float,
    ) -> SmokingSession:
        """Create a new smoking detection session in 'pending' state."""
        session = SmokingSession(
            tenant_id=tenant_id,
            user_id=user_id,
            media_id=media_id,
            interval=interval,
            status="pending",
            overall_status=None,
            video_out_path=None,
        )
        db.add(session)
        await db.flush()
        return session

    async def get_session(
        self,
        session_id: uuid.UUID,
        tenant_id: str,
    ) -> Optional[SmokingSession]:
        """Fetch a single session by ID, scoped to a tenant."""
        stmt = select(SmokingSession).where(
            SmokingSession.id == session_id,
            SmokingSession.tenant_id == tenant_id,
            SmokingSession.is_delete == False,
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_session_with_events(
        self,
        session_id: uuid.UUID,
        tenant_id: str,
    ) -> Optional[SmokingSession]:
        """Fetch a session by ID with events eagerly loaded, scoped to tenant."""
        from sqlalchemy.orm import selectinload

        stmt = (
            select(SmokingSession)
            .options(selectinload(SmokingSession.events))
            .where(
                SmokingSession.id == session_id,
                SmokingSession.tenant_id == tenant_id,
                SmokingSession.is_delete == False,
            )
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_sessions_history(
        self,
        tenant_id: str,
        user_id: Optional[uuid.UUID] = None,
    ) -> List[SmokingSession]:
        """
        Fetch all non-deleted sessions for a tenant, eagerly loading the user relationship.
        Optionally filter by user_id for non-admin callers.
        """
        from sqlalchemy.orm import selectinload

        stmt = (
            select(SmokingSession)
            .options(selectinload(SmokingSession.user))
            .where(
                SmokingSession.tenant_id == tenant_id,
                SmokingSession.is_delete == False,
            )
        )
        if user_id is not None:
            stmt = stmt.where(SmokingSession.user_id == user_id)
        stmt = stmt.order_by(SmokingSession.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_session_status(
        self,
        session_id: uuid.UUID,
        status: str,
        overall_status: Optional[str] = None,
        video_out_path: Optional[str] = None,
    ) -> None:
        """Update the lifecycle status (and optional outcome fields) for a session."""
        values: dict = {"status": status}
        if overall_status is not None:
            values["overall_status"] = overall_status
        if video_out_path is not None:
            values["video_out_path"] = video_out_path

        stmt = (
            update(SmokingSession)
            .where(SmokingSession.id == session_id)
            .values(**values)
        )
        await self.db.execute(stmt)

    # ------------------------------------------------------------------
    # SmokingEvent CRUD
    # ------------------------------------------------------------------

    async def create_event(
        self,
        session_id: uuid.UUID,
        event_dict: dict,
    ) -> SmokingEvent:
        """
        Persist a single detection result (dict from SmokingDetector.analyse_video)
        as a SmokingEvent row.

        Expected keys in event_dict:
            timestamp, person_id, status, signals.score, signals.cig,
            signals.tip, signals.smoke, signals.tip_ratio, signals.smoke_area,
            signals.person_box, signals.cig_box
        """
        signals = event_dict.get("signals", {})
        event = SmokingEvent(
            session_id=session_id,
            timestamp=event_dict["timestamp"],
            person_id=event_dict["person_id"],
            status=event_dict["status"],
            score=signals.get("score", 0),
            cig_detected=bool(signals.get("cig", False)),
            tip_detected=bool(signals.get("tip", False)),
            smoke_detected=bool(signals.get("smoke", False)),
            tip_ratio=float(signals.get("tip_ratio", 0.0)),
            smoke_area=float(signals.get("smoke_area", 0.0)),
            person_box=signals.get("person_box"),
            cig_box=signals.get("cig_box"),
            frame_path=event_dict.get("frame_path"),
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def get_session_events(
        self,
        session_id: uuid.UUID,
    ) -> List[SmokingEvent]:
        """Fetch all events for a session ordered by timestamp."""
        stmt = (
            select(SmokingEvent)
            .where(
                SmokingEvent.session_id == session_id,
                SmokingEvent.is_delete == False,
            )
            .order_by(SmokingEvent.timestamp)
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())
