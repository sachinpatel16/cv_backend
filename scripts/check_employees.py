import asyncio
import sys
import os

# Add root folder to python path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import all models to register them with SQLAlchemy
from modules.peopleanalytics.model import (
    PeopleAnalyticsSession,
    EmployeeAttendanceLog,
    PersonIdentity,
    PersonEmbedding,
    PersonOccurrence,
    LineCrossingLog,
    UploadedVideo
)
from modules.employees.model import Employee, EmployeeEmbedding
from database.session import SessionLocal
from sqlalchemy import select

async def main():
    async with SessionLocal() as db:
        res = await db.execute(select(Employee))
        employees = res.scalars().all()
        if not employees:
            print("No employees found in the database.")
            return
            
        print(f"Found {len(employees)} employee(s):")
        for emp in employees:
            emb_res = await db.execute(select(EmployeeEmbedding).where(EmployeeEmbedding.employee_id == emp.id))
            emb = emb_res.scalars().first()
            has_embedding = "Yes" if emb else "No"
            print(f"- Name: {emp.first_name} {emp.last_name}")
            print(f"  ID: {emp.id}")
            print(f"  Code: {emp.employee_code}")
            print(f"  Photo Path: {emp.photo_path}")
            print(f"  Active: {emp.is_active}")
            print(f"  Deleted: {emp.is_delete}")
            print(f"  Has Embedding: {has_embedding}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())
