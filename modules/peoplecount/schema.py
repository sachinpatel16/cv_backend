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
    filename: str
    filepath: str
    processed_filepath: Optional[str] = None
    media_type: str
    status: str
    total_people_count: Optional[int] = None
    peak_people_count: Optional[int] = None
    average_people_count: Optional[float] = None
    video_duration_seconds: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class PeopleCountMediaDetailResponse(PeopleCountMediaResponse):
    results: List[PeopleCountResultResponse] = []
