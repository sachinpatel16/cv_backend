from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime
from typing import Optional, List, Dict

class ObjectCountResultResponse(BaseModel):
    id: UUID
    media_id: UUID
    track_id: int
    class_name: str
    gender: Optional[str] = None
    first_frame: int
    last_frame: int
    total_frames: int
    start_time: Optional[float] = None
    end_time: Optional[float] = None
    created_at: datetime

    class Config:
        from_attributes = True


class ObjectCountMediaResponse(BaseModel):
    id: UUID
    gallery_media_id: UUID
    status: str
    classify_gender: bool
    classify_vehicle: bool
    classes_to_track: Optional[List[str]] = None
    total_objects_count: Optional[int] = None
    peak_objects_count: Optional[int] = None
    average_objects_count: Optional[float] = None
    video_duration_seconds: Optional[float] = None
    report_summary: Optional[Dict] = None
    progress_percentage: int = 0
    created_at: datetime

    # Populated from gallery_media relationship
    filename: Optional[str] = None
    filepath: Optional[str] = None
    processed_filepath: Optional[str] = None
    media_type: Optional[str] = None

    @classmethod
    def model_validate(cls, obj, *args, **kwargs):
        instance = super().model_validate(obj, *args, **kwargs)
        # Handle lazy/eager loading of gallery_media relationship
        gallery_media = getattr(obj, "gallery_media", None)
        if gallery_media:
            instance.filename = gallery_media.filename
            instance.filepath = gallery_media.filepath
            instance.processed_filepath = gallery_media.processed_filepath
            instance.media_type = gallery_media.media_type
        return instance

    class Config:
        from_attributes = True


class ObjectCountMediaDetailResponse(ObjectCountMediaResponse):
    results: List[ObjectCountResultResponse] = []


class ObjectCountAnalyzeRequest(BaseModel):
    gallery_media_id: UUID
    classes_to_track: Optional[List[str]] = None
    classify_gender: bool = False
    classify_vehicle: bool = False
    confidence_threshold: float = 0.35
    min_track_frames: int = 100
    track_buffer: int = 150
    gmc_method: str = "none"
    reid_classes: Optional[List[str]] = ["person"]
    imgsz: int = 480
    entry_exit_report: bool = False
    line_coords: Optional[List[List[int]]] = None
    device: Optional[str] = None
