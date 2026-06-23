from pydantic import BaseModel, computed_field
from uuid import UUID
from datetime import datetime
from typing import Optional, List


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------

class SubmitVideoRequest(BaseModel):
    """Query/form parameters for the video upload endpoint."""
    interval: float = 1.0
    save_frames: bool = True


# ---------------------------------------------------------------------------
# Response sub-schemas
# ---------------------------------------------------------------------------

class SmokingEventOut(BaseModel):
    """Serialised representation of a single SmokingEvent DB row."""
    id: UUID
    session_id: UUID
    timestamp: float
    person_id: int
    status: str
    score: int
    cig_detected: bool
    tip_detected: bool
    smoke_detected: bool
    tip_ratio: float
    smoke_area: float
    person_box: Optional[list] = None
    cig_box: Optional[list] = None
    frame_path: Optional[str] = None

    class Config:
        from_attributes = True


class SmokingSessionOut(BaseModel):
    """Full session response including all detected events (used for status / detail endpoints)."""
    id: UUID
    status: str
    overall_status: Optional[str] = None
    video_out_path: Optional[str] = None
    interval: float
    created_at: datetime
    events: List[SmokingEventOut] = []

    @computed_field
    @property
    def job_id(self) -> UUID:
        """Mirrors peoplefind convention — exposes session id as job_id."""
        return self.id

    class Config:
        from_attributes = True


# ---------------------------------------------------------------------------
# History / list response schemas
# ---------------------------------------------------------------------------

class SmokingSessionUserOut(BaseModel):
    """Slim user payload embedded inside SmokingSessionHistoryOut."""
    id: UUID
    email: str
    role: str

    class Config:
        from_attributes = True


class SmokingSessionHistoryOut(BaseModel):
    """Summary row returned by the /sessions/history endpoint."""
    id: UUID
    status: str
    overall_status: Optional[str] = None
    interval: float
    created_at: datetime
    total_events: int
    user: Optional[SmokingSessionUserOut] = None

    class Config:
        from_attributes = True
