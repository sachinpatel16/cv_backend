import uuid
from sqlalchemy import String, Integer, Float, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship
from database.base import BaseModel
from modules.gallery.model import GalleryMedia

class PeopleCountMedia(BaseModel):
    """
    Represents a people counting analysis session on a gallery media item.
    """
    __tablename__ = "people_count_media"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    gallery_media_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("gallery_media.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="pending")    # 'pending' | 'processing' | 'completed' | 'failed'
    
    total_people_count: Mapped[int | None] = mapped_column(Integer, nullable=True)  # Total unique people counted
    peak_people_count: Mapped[int | None] = mapped_column(Integer, nullable=True)   # Max people in any single frame
    average_people_count: Mapped[float | None] = mapped_column(Float, nullable=True) # Average people count per frame
    video_duration_seconds: Mapped[float | None] = mapped_column(Float, nullable=True) # Duration of the video
    
    # Relationships
    gallery_media: Mapped["GalleryMedia"] = relationship()
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
