import uuid
from typing import Optional, List
from datetime import datetime
from sqlalchemy import String, Integer, Float, ForeignKey, Boolean, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from pgvector.sqlalchemy import Vector

from database.base import BaseModel

class UploadedVideo(BaseModel):
    """
    Tracks raw CCTV video files uploaded per tenant.
    """
    __tablename__ = "uploaded_videos"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(nullable=True)
    original_name: Mapped[str] = mapped_column(String(255), nullable=False)
    saved_path: Mapped[str] = mapped_column(String(512), nullable=False)


class PeopleAnalyticsSession(BaseModel):
    """
    Represents a video/image analytics processing session.
    """
    __tablename__ = "people_analytics_sessions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    video_name: Mapped[str] = mapped_column(String(255), nullable=False)
    video_path: Mapped[str] = mapped_column(String(512), nullable=False)
    output_video_path: Mapped[str | None] = mapped_column(String(512), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="pending")  # 'pending' | 'processing' | 'completed' | 'failed'
    
    # Coordinates of counting line
    line_start: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)  # [x, y]
    line_end: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)  # [x, y]
    
    similarity_threshold: Mapped[float] = mapped_column(Float, default=0.85)
    confidence_threshold: Mapped[float] = mapped_column(Float, default=0.3)
    
    # Aggregated results reports
    unique_person_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_person_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    first_time_visitor_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peak_occupancy: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_occupancy: Mapped[float | None] = mapped_column(Float, nullable=True)
    entry_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    exit_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    
    # Store occupancy history over video timeline (e.g. [{"time_sec": 10.5, "occupancy": 3}, ...])
    occupancy_timeline: Mapped[list[dict] | None] = mapped_column(JSONB, nullable=True)

    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    employee_attendance: Mapped[list["EmployeeAttendanceLog"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    occurrences: Mapped[list["PersonOccurrence"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    crossings: Mapped[list["LineCrossingLog"]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )


class EmployeeAttendanceLog(BaseModel):
    """
    Logs presence of registered employees detected in an analytics session.
    """
    __tablename__ = "employee_attendance_logs"

    session_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("people_analytics_sessions.id", ondelete="CASCADE"), nullable=True)
    employee_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("employees.id", ondelete="CASCADE"), nullable=False)
    first_seen: Mapped[float] = mapped_column(Float, default=0.0, nullable=False) # Video timestamp in seconds
    last_seen: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)  # Video timestamp in seconds
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)

    employee_entry_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)
    employee_exit_timestamp: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=text("now()"), nullable=False)

    session: Mapped[Optional["PeopleAnalyticsSession"]] = relationship(back_populates="employee_attendance")
    employee: Mapped["Employee"] = relationship(back_populates="attendance_logs")


class PersonIdentity(BaseModel):
    """
    Represents an anonymous unique visitor tracked across runs via ReID.
    """
    __tablename__ = "person_identities"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    class_id: Mapped[int] = mapped_column(Integer, default=0) # 0 = person

    # Relationships
    embeddings: Mapped[list["PersonEmbedding"]] = relationship(
        back_populates="identity", cascade="all, delete-orphan"
    )
    occurrences: Mapped[list["PersonOccurrence"]] = relationship(
        back_populates="identity", cascade="all, delete-orphan"
    )
    crossings: Mapped[list["LineCrossingLog"]] = relationship(
        back_populates="identity", cascade="all, delete-orphan"
    )


class PersonEmbedding(BaseModel):
    """
    Stores 512-dimensional visual embeddings of anonymous visitors.
    """
    __tablename__ = "person_embeddings"

    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("person_identities.id", ondelete="CASCADE"), nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False)
    bbox: Mapped[list[int] | None] = mapped_column(ARRAY(Integer), nullable=True)
    timestamp: Mapped[float | None] = mapped_column(Float, nullable=True) # Timestamp in video start (seconds)

    identity: Mapped["PersonIdentity"] = relationship(back_populates="embeddings")


class PersonOccurrence(BaseModel):
    """
    Logs separate track appearances of an anonymous person inside an analytics session.
    """
    __tablename__ = "person_occurrences"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people_analytics_sessions.id", ondelete="CASCADE"), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("person_identities.id", ondelete="CASCADE"), nullable=False)
    tracker_id: Mapped[int] = mapped_column(Integer, nullable=False) # Tracker ID in this run
    first_seen: Mapped[float] = mapped_column(Float, nullable=False) # Start timestamp (seconds)
    last_seen: Mapped[float] = mapped_column(Float, nullable=False)  # End timestamp (seconds)
    crop_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    session: Mapped["PeopleAnalyticsSession"] = relationship(back_populates="occurrences")
    identity: Mapped["PersonIdentity"] = relationship(back_populates="occurrences")


class LineCrossingLog(BaseModel):
    """
    Logs line crossing events for anonymous visitors.
    """
    __tablename__ = "line_crossing_logs"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people_analytics_sessions.id", ondelete="CASCADE"), nullable=False)
    identity_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("person_identities.id", ondelete="CASCADE"), nullable=False)
    tracker_id: Mapped[int] = mapped_column(Integer, nullable=False)
    timestamp: Mapped[float] = mapped_column(Float, nullable=False) # Crossing timestamp (seconds)
    direction: Mapped[str] = mapped_column(String(10), nullable=False) # 'in' | 'out'

    session: Mapped["PeopleAnalyticsSession"] = relationship(back_populates="crossings")
    identity: Mapped["PersonIdentity"] = relationship(back_populates="crossings")
