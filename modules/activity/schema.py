from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List

# --- CONFIGURATION SCHEMAS ---
class ActivityConfigBase(BaseModel):
    detect_fall: bool = True
    detect_aggression: bool = True
    detect_intrusion: bool = True
    detect_loitering: bool = True
    loitering_threshold: float = 15.0
    detect_occupancy: bool = True
    occupancy_limit: int = 5
    detect_sleeping: bool = True
    detect_walking: bool = True
    selected_activities: Optional[List[str]] = Field(
        None,
        description="Specific custom activities from labels.txt to detect. If null/empty, defaults apply."
    )
    polygon_points: Optional[List[List[int]]] = Field(
        None, 
        description="Coordinates of the Region of Interest polygon, e.g. [[x1, y1], [x2, y2], ...]"
    )

class ActivityConfigPayload(ActivityConfigBase):
    gallery_media_id: UUID

class ActivityConfigResponse(ActivityConfigBase):
    id: UUID
    gallery_media_id: UUID
    created_at: datetime

    class Config:
        from_attributes = True


class ActivityProcessPayload(ActivityConfigBase):
    interval: float = Field(1.0, description="Frame sampling interval in seconds")


# --- MEDIA RESPONSE MAPS ---
class ActivityMediaResponse(BaseModel):
    id: UUID
    filename: str
    filepath: str
    processed_filepath: Optional[str] = None
    media_type: str
    status: str
    created_at: datetime
    config: Optional[ActivityConfigResponse] = None

    class Config:
        from_attributes = True


class ActivityProcessStatusResponse(BaseModel):
    gallery_media_id: UUID
    status: str
    processed_filepath: Optional[str] = None
    config: Optional[ActivityConfigResponse] = None

    class Config:
        from_attributes = True


# --- ALERT REPORT SCHEMAS ---
class ActivityAlertResponse(BaseModel):
    id: UUID
    gallery_media_id: UUID
    track_id: Optional[int] = None
    activity_type: str
    timestamp: float
    bbox: Optional[List[int]] = None
    snapshot_path: Optional[str] = None
    severity: str
    created_at: datetime

    class Config:
        from_attributes = True


class ActivityAlertSummary(BaseModel):
    total_alerts: int
    by_type: dict
    by_severity: dict
