import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from modules.peopleanalytics.model import EmployeeAttendanceLog
from modules.employees.model import Employee
from sqlalchemy import select

async def main():
    session_id_str = "60998664-aee2-4347-a9c4-c8c9c0916cf4"
    import uuid
    session_id = uuid.UUID(session_id_str)
    
    async with SessionLocal() as db:
        stmt = select(EmployeeAttendanceLog).where(EmployeeAttendanceLog.session_id == session_id)
        logs = (await db.execute(stmt)).scalars().all()
        if not logs:
            print(f"No employees checked in for session {session_id_str}.")
            return
            
        print(f"Employees checked in for session {session_id_str}:")
        for log in logs:
            emp_res = await db.execute(select(Employee).where(Employee.id == log.employee_id))
            emp = emp_res.scalars().first()
            name = f"{emp.first_name} {emp.last_name}" if emp else "Unknown"
            print(f"- {name} (Employee Code: {emp.employee_code if emp else 'N/A'})")
            print(f"  First seen: {log.first_seen}s")
            print(f"  Last seen: {log.last_seen}s")
            print(f"  Occurrences: {log.occurrence_count}")
            print("-" * 30)

if __name__ == "__main__":
    asyncio.run(main())
