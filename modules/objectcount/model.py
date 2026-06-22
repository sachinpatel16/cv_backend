import uuid
from sqlalchemy import String, Integer, Float, ForeignKey, JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.base import BaseModel

class ObjectCountMedia(BaseModel):
    """
    Stores references to uploaded video or photo files for object counting and tracking.
    """
    __tablename__ = "object_count_media"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(512), nullable=False)  # Path to local file
    processed_filepath: Mapped[str | None] = mapped_column(String(512), nullable=True)  # Path to processed/annotated file
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'photo' | 'video'
    status: Mapped[str] = mapped_column(String(20), default="pending")    # 'pending' | 'processing' | 'completed' | 'failed'
    
    # Tracking options used for the latest analysis
    classify_gender: Mapped[bool] = mapped_column(default=False, server_default="false")
    classify_vehicle: Mapped[bool] = mapped_column(default=False, server_default="false")
    classes_to_track: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    
    # Analysis metrics
    total_objects_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    peak_objects_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    average_objects_count: Mapped[float | None] = mapped_column(Float, nullable=True)
    video_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    
    # Detailed counts and breakdown report as JSON
    report_summary: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # Relationship to tracked results
    results: Mapped[list["ObjectCountResult"]] = relationship(
        back_populates="media", cascade="all, delete-orphan"
    )


class ObjectCountResult(BaseModel):
    """
    Stores individual track summaries for the detected and tracked objects.
    """
    __tablename__ = "object_count_results"

    media_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("object_count_media.id", ondelete="CASCADE"), nullable=False)
    track_id: Mapped[int] = mapped_column(Integer, nullable=False) # Track ID
    class_name: Mapped[str] = mapped_column(String(50), nullable=False)
    gender: Mapped[str | None] = mapped_column(String(20), nullable=True) # Resolved gender if person class
    
    first_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    total_frames: Mapped[int] = mapped_column(Integer, nullable=False)
    
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    media: Mapped["ObjectCountMedia"] = relationship(back_populates="results")
