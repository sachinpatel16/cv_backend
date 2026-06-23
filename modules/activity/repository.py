import uuid
from typing import List, Optional
from sqlalchemy import select, update, and_
from sqlalchemy.ext.asyncio import AsyncSession
from modules.activity.model import ActivityMedia, ActivityConfig, ActivityAlert

class ActivityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_activity_media(
        self, tenant_id: uuid.UUID, filename: str, filepath: str, media_type: str
    ) -> ActivityMedia:
        """Create a new activity media source entry (photo or video)."""
        media = ActivityMedia(
            tenant_id=tenant_id,
            filename=filename,
            filepath=filepath,
            media_type=media_type,
            status="pending"
        )
        self.db.add(media)
        await self.db.flush()
        return media

    async def get_activity_media_by_id(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[ActivityMedia]:
        """Fetch activity media source by ID, scoped to tenant."""
        stmt = select(ActivityMedia).where(
            ActivityMedia.id == media_id,
            ActivityMedia.tenant_id == tenant_id,
            ActivityMedia.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_activity_media_by_filename(self, filename: str, tenant_id: uuid.UUID) -> Optional[ActivityMedia]:
        """Fetch activity media source by filename, scoped to tenant."""
        stmt = select(ActivityMedia).where(
            ActivityMedia.filename == filename,
            ActivityMedia.tenant_id == tenant_id,
            ActivityMedia.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_activity_media(self, tenant_id: uuid.UUID) -> List[ActivityMedia]:
        """Fetch all non-deleted activity media for a tenant."""
        stmt = (
            select(ActivityMedia)
            .where(
                ActivityMedia.tenant_id == tenant_id,
                ActivityMedia.is_delete == False
            )
            .order_by(ActivityMedia.created_at.desc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def update_media_status(self, media_id: uuid.UUID, status: str) -> None:
        """Update indexing status of an activity media source."""
        stmt = (
            update(ActivityMedia)
            .where(ActivityMedia.id == media_id)
            .values(status=status)
        )
        await self.db.execute(stmt)

    async def delete_activity_media(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[ActivityMedia]:
        """Soft delete activity media and its associated configurations and alerts."""
        media = await self.get_activity_media_by_id(media_id, tenant_id)
        if media:
            media.is_delete = True
            
            # Also soft delete related config and alerts
            await self.db.execute(
                update(ActivityConfig)
                .where(ActivityConfig.activity_media_id == media_id)
                .values(is_delete=True)
            )
            await self.db.execute(
                update(ActivityAlert)
                .where(ActivityAlert.activity_media_id == media_id)
                .values(is_delete=True)
            )
            await self.db.flush()
        return media

    async def get_activity_config(self, media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[ActivityConfig]:
        """Fetch the configuration rules for a media source."""
        stmt = select(ActivityConfig).where(
            ActivityConfig.activity_media_id == media_id,
            ActivityConfig.tenant_id == tenant_id,
            ActivityConfig.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def upsert_activity_config(
        self, media_id: uuid.UUID, tenant_id: uuid.UUID, polygon_points: Optional[list],
        detect_fall: bool, detect_aggression: bool, detect_intrusion: bool,
        detect_loitering: bool, loitering_threshold: float,
        detect_occupancy: bool, occupancy_limit: int,
        detect_sleeping: bool, detect_walking: bool
    ) -> ActivityConfig:
        """Create or update ROI/detection configurations for a media source."""
        config = await self.get_activity_config(media_id, tenant_id)
        if not config:
            config = ActivityConfig(
                tenant_id=tenant_id,
                activity_media_id=media_id,
                polygon_points=polygon_points,
                detect_fall=detect_fall,
                detect_aggression=detect_aggression,
                detect_intrusion=detect_intrusion,
                detect_loitering=detect_loitering,
                loitering_threshold=loitering_threshold,
                detect_occupancy=detect_occupancy,
                occupancy_limit=occupancy_limit,
                detect_sleeping=detect_sleeping,
                detect_walking=detect_walking
            )
            self.db.add(config)
        else:
            config.polygon_points = polygon_points
            config.detect_fall = detect_fall
            config.detect_aggression = detect_aggression
            config.detect_intrusion = detect_intrusion
            config.detect_loitering = detect_loitering
            config.loitering_threshold = loitering_threshold
            config.detect_occupancy = detect_occupancy
            config.occupancy_limit = occupancy_limit
            config.detect_sleeping = detect_sleeping
            config.detect_walking = detect_walking
        await self.db.flush()
        return config

    async def create_activity_alert(
        self, tenant_id: uuid.UUID, media_id: uuid.UUID, track_id: Optional[int],
        activity_type: str, timestamp: float, bbox: Optional[list],
        snapshot_path: Optional[str], severity: str
    ) -> ActivityAlert:
        """Store an activity detection alert."""
        alert = ActivityAlert(
            tenant_id=tenant_id,
            activity_media_id=media_id,
            track_id=track_id,
            activity_type=activity_type,
            timestamp=timestamp,
            bbox=bbox,
            snapshot_path=snapshot_path,
            severity=severity
        )
        self.db.add(alert)
        await self.db.flush()
        return alert

    async def get_alerts(
        self, tenant_id: uuid.UUID, media_id: Optional[uuid.UUID] = None,
        activity_type: Optional[str] = None, severity: Optional[str] = None
    ) -> List[ActivityAlert]:
        """Query detected activity alerts with optional filters."""
        stmt = select(ActivityAlert).where(
            ActivityAlert.tenant_id == tenant_id,
            ActivityAlert.is_delete == False
        )
        if media_id:
            stmt = stmt.where(ActivityAlert.activity_media_id == media_id)
        if activity_type:
            stmt = stmt.where(ActivityAlert.activity_type == activity_type)
        if severity:
            stmt = stmt.where(ActivityAlert.severity == severity)
        
        stmt = stmt.order_by(ActivityAlert.timestamp.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_alerts_summary(self, tenant_id: uuid.UUID, media_id: Optional[uuid.UUID] = None) -> dict:
        """Generate analytics summary statistics of alerts."""
        stmt_base = select(ActivityAlert).where(
            ActivityAlert.tenant_id == tenant_id,
            ActivityAlert.is_delete == False
        )
        if media_id:
            stmt_base = stmt_base.where(ActivityAlert.activity_media_id == media_id)
        
        result = await self.db.execute(stmt_base)
        alerts = result.scalars().all()
        
        summary = {
            "total_alerts": len(alerts),
            "by_type": {},
            "by_severity": {}
        }
        for a in alerts:
            summary["by_type"][a.activity_type] = summary["by_type"].get(a.activity_type, 0) + 1
            summary["by_severity"][a.severity] = summary["by_severity"].get(a.severity, 0) + 1
        return summary
