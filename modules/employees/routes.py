import uuid
from typing import List, Optional
from fastapi import APIRouter, Depends, File, UploadFile, Form, status, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from database.session import get_db
from shared.schemas.response import StandardResponse
from shared.dependencies.auth import require_admin, require_viewer
from modules.users.model import User
from modules.employees.service import EmployeeService
from modules.employees.schema import EmployeeResponse, EmployeeAttendanceResponse

router = APIRouter(prefix="/employees", tags=["Employee Registry"])


def verify_tenant(user: User) -> uuid.UUID:
    """Helper to verify and return the tenant_id from the authenticated user."""
    if not user.tenant_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The active user account is not associated with any tenant namespace."
        )
    return user.tenant_id


@router.post(
    "",
    response_model=StandardResponse[EmployeeResponse],
    status_code=status.HTTP_201_CREATED
)
async def register_new_employee(
    first_name: str = Form(..., description="Employee first name"),
    last_name: str = Form(..., description="Employee last name"),
    employee_code: str = Form(..., description="Unique employee identifier code"),
    file: UploadFile = File(..., description="Registration picture of the employee"),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Registers a new employee, uploads their picture, extracts visual ReID embeddings, and stores them.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    employee = await service.register_employee(
        tenant_id=tenant_id,
        first_name=first_name,
        last_name=last_name,
        employee_code=employee_code,
        file=file
    )
    return StandardResponse(
        message="Employee registered successfully.",
        status=status.HTTP_201_CREATED,
        data=EmployeeResponse.model_validate(employee)
    )


@router.get(
    "",
    response_model=StandardResponse[List[EmployeeResponse]],
    status_code=status.HTTP_200_OK
)
async def list_employees(
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Lists all active registered employees in the tenant namespace.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    employees = await service.get_all_employees(tenant_id)
    return StandardResponse(
        message=f"Successfully retrieved {len(employees)} employee(s).",
        status=status.HTTP_200_OK,
        data=[EmployeeResponse.model_validate(e) for e in employees]
    )


@router.get(
    "/{employee_id}",
    response_model=StandardResponse[EmployeeResponse],
    status_code=status.HTTP_200_OK
)
async def get_employee_details(
    employee_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Fetches the profile details of a single employee.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    employee = await service.get_employee(employee_id, tenant_id)
    return StandardResponse(
        message="Employee details retrieved.",
        status=status.HTTP_200_OK,
        data=EmployeeResponse.model_validate(employee)
    )


@router.put(
    "/{employee_id}",
    response_model=StandardResponse[EmployeeResponse],
    status_code=status.HTTP_200_OK
)
async def update_employee_profile(
    employee_id: uuid.UUID,
    first_name: Optional[str] = Form(None),
    last_name: Optional[str] = Form(None),
    employee_code: Optional[str] = Form(None),
    file: Optional[UploadFile] = File(None),
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Updates employee profile details. Re-extracts visual embeddings if a new photo file is provided.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    employee = await service.update_employee(
        employee_id=employee_id,
        tenant_id=tenant_id,
        first_name=first_name,
        last_name=last_name,
        employee_code=employee_code,
        file=file
    )
    return StandardResponse(
        message="Employee profile updated successfully.",
        status=status.HTTP_200_OK,
        data=EmployeeResponse.model_validate(employee)
    )


@router.delete(
    "/{employee_id}",
    response_model=StandardResponse[None],
    status_code=status.HTTP_200_OK
)
async def delete_employee(
    employee_id: uuid.UUID,
    current_user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db)
):
    """
    Soft deletes an employee and removes their profile image from storage.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    await service.delete_employee(employee_id, tenant_id)
    return StandardResponse(
        message="Employee profile deleted successfully.",
        status=status.HTTP_200_OK,
        data=None
    )


@router.get(
    "/sessions/{session_id}/attendance",
    response_model=StandardResponse[List[EmployeeAttendanceResponse]],
    status_code=status.HTTP_200_OK
)
async def get_session_employee_attendance(
    session_id: uuid.UUID,
    current_user: User = Depends(require_viewer),
    db: AsyncSession = Depends(get_db)
):
    """
    Retrieves the Employee Attendance check-in report computed during the video analysis.
    """
    tenant_id = verify_tenant(current_user)
    service = EmployeeService(db)
    logs = await service.get_session_attendance(session_id, tenant_id)
    return StandardResponse(
        message=f"Retrieved {len(logs)} attendance logs.",
        status=status.HTTP_200_OK,
        data=[EmployeeAttendanceResponse.model_validate(l) for l in logs]
    )
