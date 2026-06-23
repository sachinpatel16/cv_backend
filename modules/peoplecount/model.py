import uuid
from sqlalchemy import String, Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.base import BaseModel

class PeopleCountMedia(BaseModel):
    """
    Stores references to uploaded video or photo files for people counting.
    """
    __tablename__ = "people_count_media"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(512), nullable=False)  # Path to local file
    processed_filepath: Mapped[str | None] = mapped_column(String(512), nullable=True)  # Path to processed/annotated file
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'photo' | 'video'
    status: Mapped[str] = mapped_column(String(20), default="pending")    # 'pending' | 'processing' | 'completed' | 'failed'
    
    total_people_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Total unique people counted
    peak_people_count: Mapped[int | None] = mapped_column(Integer, nullable=True)   # Max people in any single frame
    average_people_count: Mapped[float | None] = mapped_column(Float, nullable=True) # Average people count per frame
    video_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True) # Duration of the video
    
    # Relationship to tracked people results
    results: Mapped[list["PeopleCountResult"]] = relationship(
        back_populates="media", cascade="all, delete-orphan"
    )


class PeopleCountResult(BaseModel):
    """
    Stores individual track summaries for the detected people.
    """
    __tablename__ = "people_count_results"

    media_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("people_count_media.id", ondelete="CASCADE"), nullable=False)
    track_id: Mapped[int] = mapped_column(Integer, nullable=False) # STrack track_id
    class_name: Mapped[str] = mapped_column(String(50), default="person")
    
    first_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    last_frame: Mapped[int] = mapped_column(Integer, nullable=False)
    total_frames: Mapped[int] = mapped_column(Integer, nullable=False)
    
    # Optional timestamps (if media is video)
    start_time: Mapped[float | None] = mapped_column(Float, nullable=True)
    end_time: Mapped[float | None] = mapped_column(Float, nullable=True)

    media: Mapped["PeopleCountMedia"] = relationship(back_populates="results")
