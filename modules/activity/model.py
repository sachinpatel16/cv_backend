import uuid
from typing import Optional, List
from sqlalchemy import String, Integer, Float, ForeignKey, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY

from database.base import BaseModel

class ActivityMedia(BaseModel):
    """
    Stores references to photos and videos uploaded specifically for Activity and Theft detection.
    """
    __tablename__ = "activity_media"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(512), nullable=False)  # Path in local storage
    output_filepath: Mapped[Optional[str]] = mapped_column(String(512), nullable=True)  # Processed output path
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'photo' | 'video'
    status: Mapped[str] = mapped_column(String(20), default="pending")    # 'pending' | 'processing' | 'completed' | 'failed'

    configs: Mapped[list["ActivityConfig"]] = relationship(back_populates="activity_media", cascade="all, delete-orphan")
    alerts: Mapped[list["ActivityAlert"]] = relationship(back_populates="activity_media", cascade="all, delete-orphan")

    @property
    def config(self) -> Optional["ActivityConfig"]:
        return self.configs[0] if self.configs else None


class ActivityConfig(BaseModel):
    """
    Stores safety and security monitoring parameters (like ROI boundary) for an activity media item.
    """
    __tablename__ = "activity_configs"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    activity_media_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("activity_media.id", ondelete="CASCADE"), nullable=False)
    
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

    activity_media: Mapped["ActivityMedia"] = relationship(back_populates="configs")


class ActivityAlert(BaseModel):
    """
    Stores detected alerts from the pose or theft detection engines.
    """
    __tablename__ = "activity_alerts"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    activity_media_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("activity_media.id", ondelete="CASCADE"), nullable=False)
    
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

    activity_media: Mapped["ActivityMedia"] = relationship(back_populates="alerts")
