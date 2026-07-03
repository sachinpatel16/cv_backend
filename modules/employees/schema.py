from pydantic import BaseModel, Field, computed_field
from uuid import UUID
from datetime import datetime
from typing import Optional

class EmployeeCreate(BaseModel):
    first_name: str = Field(..., description="Employee's first name")
    last_name: str = Field(..., description="Employee's last name")
    employee_code: str = Field(..., description="Unique employee code identifier")


class EmployeeResponse(BaseModel):
    id: UUID
    tenant_id: UUID
    first_name: str
    last_name: str
    employee_code: str
    photo_path: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True


class EmployeeAttendanceResponse(BaseModel):
    id: UUID
    session_id: Optional[UUID] = None
    employee: EmployeeResponse
    first_seen: float = Field(..., description="Video timestamp in seconds when first detected")
    last_seen: float = Field(..., description="Video timestamp in seconds when last detected")
    occurrence_count: int = Field(..., description="How many separate tracks matched this employee")
    employee_entry_timestamp: datetime = Field(..., description="Real-world check-in timestamp")
    employee_exit_timestamp: datetime = Field(..., description="Real-world check-out timestamp")
    created_at: datetime

    @computed_field
    @property
    def dwell_time(self) -> float:
        return round((self.employee_exit_timestamp - self.employee_entry_timestamp).total_seconds(), 2)

    class Config:
        from_attributes = True


class GroupPhotoAttendanceResponse(BaseModel):
    session_id: Optional[UUID] = Field(None, description="The unique session ID associated with this group photo attendance run")
    annotated_image_path: str = Field(..., description="Path to the single annotated group photo showing all employees and names")
    attendance_logs: list[EmployeeAttendanceResponse] = Field(..., description="List of attendance check-in logs for matched employees")



class EmployeeVideoProcessItem(BaseModel):
    video_path: str = Field(..., description="Unique saved video path")


class EmployeeProcessVideosRequest(BaseModel):
    videos: list[EmployeeVideoProcessItem] = Field(..., description="List of videos to process")

