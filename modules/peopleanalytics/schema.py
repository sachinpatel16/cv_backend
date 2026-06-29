from pydantic import BaseModel, Field, computed_field
from uuid import UUID
from datetime import datetime
from typing import Optional, List

from modules.employees.schema import EmployeeResponse



# --- PEOPLE ANALYTICS SESSIONS SCHEMAS ---

class PeopleAnalyticsSessionResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    video_name: str
    video_path: str
    output_video_path: Optional[str] = None
    status: str
    
    line_start: Optional[List[int]] = None
    line_end: Optional[List[int]] = None
    similarity_threshold: float
    confidence_threshold: float
    
    unique_person_count: Optional[int] = None
    total_person_count: Optional[int] = None
    first_time_visitor_count: Optional[int] = None
    peak_occupancy: Optional[int] = None
    average_occupancy: Optional[float] = None
    entry_count: Optional[int] = None
    exit_count: Optional[int] = None
    
    occupancy_timeline: Optional[List[dict]] = None
    
    created_at: datetime
    completed_at: Optional[datetime] = None

    class Config:
        from_attributes = True


# --- CROSS-VIDEO VISITOR ANALYTICS DASHBOARD SCHEMAS ---

class VisitorAnalyticsReport(BaseModel):
    total_unique_people: int = Field(..., description="Total unique visitor identities registered")
    repeat_visitors_count: int = Field(..., description="Count of people who appeared in more than 1 tracking session")
    repeat_visitor_rate: float = Field(..., description="Percentage of repeat visitors")
    new_visitors_this_month: int = Field(..., description="New visitor identities registered in the last 30 days")


# --- CCTV UPLOAD AND RUN PROCESS SCHEMAS ---

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
    line_start: Optional[List[int]] = Field(None, description="Coordinates [x, y] of counting line start")
    line_end: Optional[List[int]] = Field(None, description="Coordinates [x, y] of counting line end")
    similarity_threshold: Optional[float] = Field(None, ge=0.5, le=1.0, description="Optional per-video similarity threshold")
    confidence_threshold: Optional[float] = Field(None, ge=0.1, le=1.0, description="Optional per-video confidence threshold")


class ProcessVideosRequest(BaseModel):
    videos: List[VideoProcessItem] = Field(..., description="List of videos with their configurations")
    line_start: Optional[List[int]] = Field(None, description="Global fallback coordinates [x, y] of counting line start")
    line_end: Optional[List[int]] = Field(None, description="Global fallback coordinates [x, y] of counting line end")
    similarity_threshold: float = Field(0.85, ge=0.5, le=1.0, description="Global fallback ReID cosine similarity threshold")
    confidence_threshold: float = Field(0.3, ge=0.1, le=1.0, description="Global fallback YOLO confidence threshold")


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


class VisitorAttendanceResponse(BaseModel):
    id: UUID
    session_id: Optional[UUID] = None
    identity_id: UUID
    first_seen: float = Field(..., description="Video timestamp in seconds when first detected")
    last_seen: float = Field(..., description="Video timestamp in seconds when last detected")
    occurrence_count: int = Field(..., description="How many separate frames matched this visitor")
    visitor_entry_timestamp: datetime = Field(..., description="Real-world check-in timestamp")
    visitor_exit_timestamp: datetime = Field(..., description="Real-world check-out timestamp")
    created_at: datetime

    @computed_field
    @property
    def dwell_time(self) -> float:
        return round((self.visitor_exit_timestamp - self.visitor_entry_timestamp).total_seconds(), 2)

    class Config:
        from_attributes = True
