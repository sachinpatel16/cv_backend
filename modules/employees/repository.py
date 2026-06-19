import uuid
from typing import List, Tuple, Optional
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from modules.employees.model import Employee, EmployeeEmbedding
from modules.peopleanalytics.model import EmployeeAttendanceLog, PeopleAnalyticsSession

class EmployeeRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def create_employee(
        self, tenant_id: uuid.UUID, first_name: str, last_name: str, employee_code: str, photo_path: str
    ) -> Employee:
        employee = Employee(
            tenant_id=tenant_id,
            first_name=first_name,
            last_name=last_name,
            employee_code=employee_code,
            photo_path=photo_path,
            is_active=True
        )
        self.db.add(employee)
        await self.db.flush()
        return employee

    async def get_employee_by_id(self, employee_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Employee]:
        stmt = select(Employee).where(
            Employee.id == employee_id,
            Employee.tenant_id == tenant_id,
            Employee.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_employee_by_code(self, employee_code: str, tenant_id: uuid.UUID) -> Optional[Employee]:
        stmt = select(Employee).where(
            Employee.employee_code == employee_code,
            Employee.tenant_id == tenant_id,
            Employee.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()

    async def get_all_employees(self, tenant_id: uuid.UUID) -> List[Employee]:
        stmt = select(Employee).where(
            Employee.tenant_id == tenant_id,
            Employee.is_delete == False
        ).order_by(Employee.created_at.desc())
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def delete_employee(self, employee_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[Employee]:
        employee = await self.get_employee_by_id(employee_id, tenant_id)
        if employee:
            employee.is_delete = True
            stmt_emb = update(EmployeeEmbedding).where(
                EmployeeEmbedding.employee_id == employee_id
            ).values(is_delete=True)
            await self.db.execute(stmt_emb)
            await self.db.flush()
        return employee

    async def create_employee_embedding(
        self, employee_id: uuid.UUID, embedding: list[float], bbox: Optional[list[int]] = None
    ) -> EmployeeEmbedding:
        ee = EmployeeEmbedding(
            employee_id=employee_id,
            embedding=embedding,
            bbox=bbox
        )
        self.db.add(ee)
        await self.db.flush()
        return ee

    async def find_similar_employee(
        self, tenant_id: uuid.UUID, target_embedding: list[float], threshold: float
    ) -> Optional[Tuple[Employee, float]]:
        """
        Searches the registered employees database for matching visual features.
        """
        distance_limit = 1.0 - threshold
        similarity_expr = (1.0 - EmployeeEmbedding.embedding.cosine_distance(target_embedding)).label("similarity")

        stmt = (
            select(Employee, similarity_expr)
            .join(EmployeeEmbedding, EmployeeEmbedding.employee_id == Employee.id)
            .where(
                Employee.tenant_id == tenant_id,
                Employee.is_delete == False,
                Employee.is_active == True,
                EmployeeEmbedding.is_delete == False,
                EmployeeEmbedding.embedding.cosine_distance(target_embedding) <= distance_limit
            )
            .order_by(EmployeeEmbedding.embedding.cosine_distance(target_embedding))
            .limit(1)
        )
        result = await self.db.execute(stmt)
        row = result.first()
        return (row[0], float(row[1])) if row else None

    async def get_employee_attendance_report(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> List[EmployeeAttendanceLog]:
        stmt = (
            select(EmployeeAttendanceLog)
            .join(PeopleAnalyticsSession, EmployeeAttendanceLog.session_id == PeopleAnalyticsSession.id)
            .options(selectinload(EmployeeAttendanceLog.employee))
            .where(
                EmployeeAttendanceLog.session_id == session_id,
                PeopleAnalyticsSession.tenant_id == tenant_id,
                EmployeeAttendanceLog.is_delete == False,
                PeopleAnalyticsSession.is_delete == False
            )
            .order_by(EmployeeAttendanceLog.first_seen.asc())
        )
        result = await self.db.execute(stmt)
        return list(result.scalars().all())

    async def get_session_by_id(self, session_id: uuid.UUID, tenant_id: uuid.UUID) -> Optional[PeopleAnalyticsSession]:
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.id == session_id,
            PeopleAnalyticsSession.tenant_id == tenant_id,
            PeopleAnalyticsSession.is_delete == False
        )
        result = await self.db.execute(stmt)
        return result.scalars().first()
