import uuid
from typing import List, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from modules.activity.model import ActivityConfig, ActivityAlert
from modules.gallery.model import GalleryMedia

class ActivityRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_activity_config(self, gallery_media_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[ActivityConfig]:
        """Fetch the configuration rules for a gallery media source."""
        stmt = select(ActivityConfig).where(
            ActivityConfig.gallery_media_id == gallery_media_id,
            ActivityConfig.tenant_id == tenant_id,
            ActivityConfig.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def upsert_activity_config(
        self, gallery_media_id: uuid.UUID, tenant_id: uuid.UUID, polygon_points: Optional[list],
        detect_fall: bool, detect_aggression: bool, detect_intrusion: bool,
        detect_loitering: bool, loitering_threshold: float,
        detect_occupancy: bool, occupancy_limit: int,
        detect_sleeping: bool, detect_walking: bool,
        selected_activities: Optional[List[str]] = None
    ) -> ActivityConfig:
        """Create or update ROI/detection configurations for a gallery media source."""
        config = await self.get_activity_config(gallery_media_id, tenant_id)
        if not config:
            config = ActivityConfig(
                tenant_id=tenant_id,
                gallery_media_id=gallery_media_id,
                polygon_points=polygon_points,
                detect_fall=detect_fall,
                detect_aggression=detect_aggression,
                detect_intrusion=detect_intrusion,
                detect_loitering=detect_loitering,
                loitering_threshold=loitering_threshold,
                detect_occupancy=detect_occupancy,
                occupancy_limit=occupancy_limit,
                detect_sleeping=detect_sleeping,
                detect_walking=detect_walking,
                selected_activities=selected_activities
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
            config.selected_activities = selected_activities
        await self.db.flush()
        return config

    async def create_activity_alert(
        self, tenant_id: uuid.UUID, gallery_media_id: uuid.UUID, track_id: Optional[int],
        activity_type: str, timestamp: float, bbox: Optional[list],
        snapshot_path: Optional[str], severity: str
    ) -> ActivityAlert:
        """Store an activity detection alert."""
        alert = ActivityAlert(
            tenant_id=tenant_id,
            gallery_media_id=gallery_media_id,
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
        self, tenant_id: uuid.UUID, gallery_media_id: Optional[uuid.UUID] = None,
        activity_type: Optional[str] = None, severity: Optional[str] = None
    ) -> List[ActivityAlert]:
        """Query detected activity alerts with optional filters."""
        stmt = select(ActivityAlert).where(
            ActivityAlert.tenant_id == tenant_id,
            ActivityAlert.is_delete == False
        )
        if gallery_media_id:
            stmt = stmt.where(ActivityAlert.gallery_media_id == gallery_media_id)
        if activity_type:
            stmt = stmt.where(ActivityAlert.activity_type == activity_type)
        if severity:
            stmt = stmt.where(ActivityAlert.severity == severity)
        
        stmt = stmt.order_by(ActivityAlert.timestamp.asc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_alerts_summary(self, tenant_id: uuid.UUID, gallery_media_id: Optional[uuid.UUID] = None) -> dict:
        """Generate analytics summary statistics of alerts."""
        stmt_base = select(ActivityAlert).where(
            ActivityAlert.tenant_id == tenant_id,
            ActivityAlert.is_delete == False
        )
        if gallery_media_id:
            stmt_base = stmt_base.where(ActivityAlert.gallery_media_id == gallery_media_id)
        
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
