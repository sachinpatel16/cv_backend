import uuid
from typing import Optional, List
from sqlalchemy import String, Integer, Float, ForeignKey, Boolean, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.base import BaseModel
from modules.users.model import User
from modules.gallery.model import GalleryMedia


class SmokingSession(BaseModel):
    """
    Represents a single smoking detection analysis job submitted by a user.
    One session corresponds to one uploaded video and one background Celery task.
    """
    __tablename__ = "smoking_sessions"

    tenant_id: Mapped[str] = mapped_column(String(255), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    gallery_media_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("gallery_media.id", ondelete="SET NULL"), nullable=True
    )


    # Job lifecycle status: pending | processing | completed | failed
    status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)

    # Worst-case smoking status across all detected events: clear | holding | smoking_likely | smoking_confirmed
    overall_status: Mapped[str | None] = mapped_column(String(30), nullable=True)

    # Path to the annotated output video produced by SmokingDetector
    video_out_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Frame sampling interval in seconds used during analysis
    interval: Mapped[float] = mapped_column(Float, default=1.0, nullable=False)

    # Relationships
    user: Mapped[Optional["User"]] = relationship()
    gallery_media: Mapped[Optional["GalleryMedia"]] = relationship()
    events: Mapped[List["SmokingEvent"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )

    @property
    def total_events(self) -> int:
        return len(self.events) if self.events else 0


class SmokingEvent(BaseModel):
    """
    Represents a single detected smoking-related observation in a video frame.
    Multiple events belong to one SmokingSession.
    """
    __tablename__ = "smoking_events"

    session_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("smoking_sessions.id", ondelete="CASCADE"), nullable=False
    )

    # Time offset in seconds from the beginning of the video
    timestamp: Mapped[float] = mapped_column(Float, nullable=False)

    # Which tracked person this event belongs to (0-indexed)
    person_id: Mapped[int] = mapped_column(Integer, nullable=False)

    # Detection classification: clear | holding | smoking_likely | smoking_confirmed
    status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Composite risk score (0-6) produced by SmokingDetector
    score: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    # Individual signal flags
    cig_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    tip_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    smoke_detected: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)

    # Continuous signal values
    tip_ratio: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    smoke_area: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    # Bounding boxes stored as JSON lists [x1, y1, x2, y2]
    person_box: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cig_box: Mapped[list | None] = mapped_column(JSON, nullable=True)

    # Path to the annotated JPEG keyframe saved for this event
    frame_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    # Relationship back to the parent session
    session: Mapped["SmokingSession"] = relationship(back_populates="events")
