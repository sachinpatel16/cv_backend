from pydantic import BaseModel, Field, computed_field
from uuid import UUID
from datetime import datetime
from typing import Optional, List

# --- MEDIA SOURCES (ADMIN SIDE) ---
class MediaSourceBase(BaseModel):
    filename: str
    media_type: str

class MediaSourceResponse(MediaSourceBase):
    id: UUID
    filepath: str
    status: str
    created_at: datetime

    class Config:
        from_attributes = True

class SearchResultResponse(BaseModel):
    id: UUID
    session_id: UUID
    similarity: float
    bbox: List[int]
    timestamp: Optional[float] = None
    media_source: MediaSourceResponse

    class Config:
        from_attributes = True

# --- FACE SEARCH SESSIONS (USER SIDE) ---
class SearchSessionResponse(BaseModel):
    id: UUID
    selfie_path: str
    threshold: float
    status: str
    created_at: datetime
    results: List[SearchResultResponse] = []

    @computed_field
    @property
    def job_id(self) -> UUID:
        return self.id

    class Config:
        from_attributes = True


