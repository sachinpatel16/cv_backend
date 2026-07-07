from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional

class GalleryMediaBase(BaseModel):
    filename: str
    media_type: str

class GalleryMediaResponse(GalleryMediaBase):
    id: UUID
    filepath: str
    processed_filepath: Optional[str] = None
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class GalleryMediaDetailResponse(GalleryMediaResponse):
    pass
