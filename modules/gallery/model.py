import uuid
from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column
from database.base import BaseModel

class GalleryMedia(BaseModel):
    """
    Stores references to uploaded photos and videos scoped per tenant.
    Used as the single repository for raw media analyzed by counting, smoking, and activity services.
    """
    __tablename__ = "gallery_media"

    tenant_id: Mapped[uuid.UUID] = mapped_column(nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    filepath: Mapped[str] = mapped_column(String(512), nullable=False)  # Path to stored file (local or S3/MinIO)
    processed_filepath: Mapped[str | None] = mapped_column(String(512), nullable=True) # Path to processed/annotated output file
    media_type: Mapped[str] = mapped_column(String(20), nullable=False)  # 'photo' | 'video'
    status: Mapped[str] = mapped_column(String(20), default="pending")    # 'pending' | 'processing' | 'completed' | 'failed'
