from pydantic import BaseModel, Field
from uuid import UUID
from datetime import datetime

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
    session_id: UUID
    employee: EmployeeResponse
    first_seen: float = Field(..., description="Video timestamp in seconds when first detected")
    last_seen: float = Field(..., description="Video timestamp in seconds when last detected")
    occurrence_count: int = Field(..., description="How many separate tracks matched this employee")
    created_at: datetime

    class Config:
        from_attributes = True
