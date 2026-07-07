import uuid
from typing import Optional, List
from sqlalchemy import String, Integer, Float, ForeignKey, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY

from database.base import BaseModel
from modules.gallery.model import GalleryMedia

class ActivityConfig(BaseModel):
    """
    Stores safety and security monitoring parameters (like ROI boundary) for a gallery media item.
    """
    __tablename__ = "activity_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    gallery_media_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gallery_media.id", ondelete="CASCADE"), nullable=False)
    
    # Store polygon points as a JSON list of coordinates, e.g. [[100, 150], [200, 150], ...]
    polygon_points: Mapped[Optional[List[List[int]]]] = mapped_column(JSON, nullable=True)
    
    # Toggle flags to disable/enable checks
    detect_fall: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    detect_aggression: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    detect_intrusion: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    detect_loitering: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    loitering_threshold: Mapped[float] = mapped_column(Float, default=15.0, server_default="15.0")

    detect_occupancy: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    occupancy_limit: Mapped[int] = mapped_column(Integer, default=5, server_default="5")

    detect_sleeping: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    detect_walking: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")

    # Selected custom activity labels to track
    selected_activities: Mapped[Optional[List[str]]] = mapped_column(JSON, nullable=True)

    gallery_media: Mapped["GalleryMedia"] = relationship()


class ActivityAlert(BaseModel):
    """
    Stores detected alerts from the pose or theft detection engines.
    """
    __tablename__ = "activity_alerts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    gallery_media_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("gallery_media.id", ondelete="CASCADE"), nullable=False)
    
    # Tracking ID of the person from YOLO tracker
    track_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    
    # E.g. 'falling', 'slipping', 'aggression', 'roi_intrusion'
    activity_type: Mapped[str] = mapped_column(String(50), nullable=False)
    
    # Keyframe timestamp in seconds where the alert happened
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)
    
    # Bounding box of the person [x1, y1, x2, y2]
    bbox: Mapped[Optional[List[int]]] = mapped_column(ARRAY(Integer), nullable=True)
    
    # File path of the black-masked crop snapshot or annotated keyframe
    snapshot_path: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)
    
    # Alert severity level: 'info', 'warning', 'critical'
    severity: Mapped[str] = mapped_column(String(20), default="warning")

    gallery_media: Mapped["GalleryMedia"] = relationship()
