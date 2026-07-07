from pydantic import BaseModel
from uuid import UUID
from datetime import datetime
from typing import Optional, List

class PeopleCountResultResponse(BaseModel):
    id: UUID
    media_id: UUID
    track_id: int
    class_name: str
    first_frame: int
    last_frame: int
    total_frames: int
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PeopleCountMediaResponse(BaseModel):
    id: UUID
    gallery_media_id: UUID
    status: str
    total_people_count: Optional[int] = None
    peak_people_count: Optional[int] = None
    average_people_count: Optional[float] = None
    video_duration_seconds: Optional[float] = None
    created_at: datetime

    # Populated from gallery_media relationship
    filename: Optional[str] = None
    filepath: Optional[str] = None
    processed_filepath: Optional[str] = None
    media_type: Optional[str] = None

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        instance = super().model_validate(obj, *args, **kwargs)
        gallery_media = getattr(obj, "gallery_media", None)
        if gallery_media:
            instance.filename = gallery_media.filename
            instance.filepath = gallery_media.filepath
            instance.processed_filepath = gallery_media.processed_filepath
            instance.media_type = gallery_media.media_type
        return instance

    class Config:
        from_attributes = True


class PeopleCountMediaDetailResponse(PeopleCountMediaResponse):
    results: List[PeopleCountResultResponse] = []


class PeopleCountAnalyzeRequest(BaseModel):
    gallery_media_id: UUID
    min_track_frames: int = 300
    track_buffer: int = 150
    confidence_threshold: float = 0.35
