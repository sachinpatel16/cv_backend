from pydantic import BaseModel, Field, computed_field
from uuid import UUID
from datetime import datetime
from typing import Optional, List

class FirstTimeVisitorDetail(BaseModel):
    identity_id: UUID
    photo_path: Optional[str] = None
    first_seen: float
    last_seen: float

    @computed_field
    @property
    def dwell_time(self) -> float:
        return round(self.last_seen - self.first_seen, 2)

    class Config:
        from_attributes = True


class FaceAnalyticsSessionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    video_name: str
    video_path: str
    output_video_path: Optional[str] = None
    status: str
    
    similarity_threshold: float
    confidence_threshold: float
    
    unique_person_count: Optional[int] = None
    total_person_count: Optional[int] = None
    first_time_visitor_count: Optional[int] = None
    first_time_visitors: Optional[List[FirstTimeVisitorDetail]] = None
    peak_occupancy: Optional[int] = None
    average_occupancy: Optional[float] = None
    
    occupancy_timeline: Optional[List[dict]] = None
    
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class VisitorAnalyticsReport(BaseModel):
    total_unique_people: int = Field(..., description="Total unique visitor identities registered")
    repeat_visitors_count: int = Field(..., description="Count of people who appeared in more than 1 tracking session")
    repeat_visitor_rate: float = Field(..., description="Percentage of repeat visitors")
    new_visitors_this_month: int = Field(..., description="New visitor identities registered in the last 30 days")


class UploadedVideoResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    original_name: str
    saved_path: str
    created_at: datetime

    class Config:
        from_attributes = True


class VideoProcessItem(BaseModel):
    video_path: str = Field(..., description="Unique saved video path")
    similarity_threshold: Optional[float] = Field(None, ge=0.5, le=1.0, description="Optional per-video similarity threshold")
    confidence_threshold: Optional[float] = Field(None, ge=0.1, le=1.0, description="Optional per-video confidence threshold")


class ProcessVideosRequest(BaseModel):
    videos: List[VideoProcessItem] = Field(..., description="List of videos with their configurations")
    similarity_threshold: float = Field(0.70, ge=0.3, le=1.0, description="Global fallback ReID cosine similarity threshold")
    confidence_threshold: float = Field(0.3, ge=0.1, le=1.0, description="Global fallback face detection confidence threshold")


class SessionDetectedPerson(BaseModel):
    identity_id: UUID
    type: str  # 'employee' | 'visitor'
    name: str
    photo_path: Optional[str] = None
    first_seen: float
    last_seen: float

    @computed_field
    @property
    def dwell_time(self) -> float:
        return round(self.last_seen - self.first_seen, 2)

    class Config:
        from_attributes = True
