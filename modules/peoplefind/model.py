import uuid
from sqlalchemy import String, Integer, Float, ForeignKey, Boolean
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.dialects.postgresql import ARRAY
from pgvector.sqlalchemy import Vector
from database.base import BaseModel

class MediaSource(BaseModel):
    """
    Stores references to original photos and videos uploaded by the Admin.
    """
    __tablename__ = "media_sources"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(512), nullable=False)  # Path in MinIO or Local storage
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'photo' | 'video'
    status: Mapped[str] = mapped_column(String(20), default="pending")    # 'pending' | 'processing' | 'completed' | 'failed'
    
    # Relationship to extracted faces
    faces: Mapped[list["FaceEmbedding"]] = relationship(back_populates="media_source", cascade="all, delete-orphan")


class FaceEmbedding(BaseModel):
    """
    Stores 512-dimensional face vectors and coordinates extracted from MediaSources.
    """
    __tablename__ = "face_embeddings"

    media_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("media_sources.id", ondelete="CASCADE"), nullable=False)
    face_idx: Mapped[int] = mapped_column(Integer, nullable=False)  # Position of face in image/frame
    bbox: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False)  # [x1, y1, x2, y2]
    
    # Stores the 512-dimensional vector natively in PostgreSQL pgvector.
    embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False)
    
    # Timestamp in seconds from video start. (Null for static photos)
    timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)

    media_source: Mapped["MediaSource"] = relationship(back_populates="faces")


class FaceSearchSession(BaseModel):
    """
    Created whenever a user uploads their photo to search for occurrences.
    """
    __tablename__ = "face_search_sessions"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    selfie_path: Mapped[str] = mapped_column(String(512), nullable=False)  # Reference selfie image file path
    selfie_embedding: Mapped[list[float]] = mapped_column(Vector(512), nullable=False) # Extracted search face vector
    threshold: Mapped[float] = mapped_column(Float, default=0.45)
    status: Mapped[str] = mapped_column(String(20), default="pending")      # 'pending' | 'completed' | 'failed'

    results: Mapped[list["FaceSearchResult"]] = relationship(back_populates="session", cascade="all, delete-orphan")


class FaceSearchResult(BaseModel):
    """
    Contains matches between search sessions and event media faces.
    """
    __tablename__ = "face_search_results"

    session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("face_search_sessions.id", ondelete="CASCADE"), nullable=False)
    media_source_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("media_sources.id", ondelete="CASCADE"), nullable=False)
    similarity: Mapped[float] = mapped_column(Float, nullable=False)
    bbox: Mapped[list[int]] = mapped_column(ARRAY(Integer), nullable=False) # Bbox of the match
    timestamp: Mapped[float | None] = mapped_column(Float, nullable=True)   # Timestamp if inside a video
    
    # Verification flag: True = Confirmed, False = Rejected, None = Pending review
    is_confirmed: Mapped[bool | None] = mapped_column(Boolean, nullable=True, default=None)

    session: Mapped["FaceSearchSession"] = relationship(back_populates="results")
    media_source: Mapped["MediaSource"] = relationship()
