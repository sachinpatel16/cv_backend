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
    unique_faces_count: Optional[int] = None

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


class UserHistoryPayload(BaseModel):
    id: UUID
    first_name: str
    last_name: str
    email: str
    role: str

    class Config:
        from_attributes = True


class SearchSessionHistoryResponse(BaseModel):
    id: UUID
    selfie_path: str
    threshold: float
    status: str
    created_at: datetime
    user: Optional[UserHistoryPayload] = None
    total_matches: int
    matched_images: List[str]

    class Config:
        from_attributes = True


# --- UNIQUE FACES RESPONSE ---
class FaceOccurrence(BaseModel):
    id: UUID
    bbox: List[int]
    timestamp: Optional[float] = None
    face_idx: int

    class Config:
        from_attributes = True


class UniqueFaceResponse(BaseModel):
    cluster_id: int
    representative_face_id: UUID
    bbox: List[int]
    timestamp: Optional[float] = None
    total_occurrences: int
    occurrences: List[FaceOccurrence]

    class Config:
        from_attributes = True


# --- TENANT-WIDE UNIQUE FACES GALLERY RESPONSE ---
class UniqueFaceOccurrence(BaseModel):
    id: UUID
    media_source_id: UUID
    filename: str
    filepath: str
    media_type: str
    bbox: List[int]
    timestamp: Optional[float] = None
    face_idx: int

    class Config:
        from_attributes = True


class TenantUniqueFaceResponse(BaseModel):
    cluster_id: int
    representative_face_id: UUID
    representative_media_source_id: UUID
    representative_filepath: str
    bbox: List[int]
    timestamp: Optional[float] = None
    total_occurrences: int
    occurrences: List[UniqueFaceOccurrence]

    class Config:
        from_attributes = True



