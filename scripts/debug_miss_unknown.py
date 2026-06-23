import asyncio
import sys
import os

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
from services.ai.face_recognition import face_rec_service
from sqlalchemy import select

async def main():
    async with SessionLocal() as db:
        emp_res = await db.execute(select(Employee).where(Employee.employee_code == "12"))
        emp = emp_res.scalars().first()
        if not emp:
            print("Employee not found.")
            return
            
        print(f"Checking employee: {emp.first_name} {emp.last_name}")
        print(f"Photo path: {emp.photo_path}")
        
        if not os.path.exists(emp.photo_path):
            print("ERROR: Photo file does not exist on disk!")
            return
            
        print(f"File size: {os.path.getsize(emp.photo_path)} bytes")
        
        # Load and run face extraction on the registered image
        with open(emp.photo_path, "rb") as f:
            img_bytes = f.read()
            
        try:
            faces = face_rec_service.extract_faces(img_bytes)
            print(f"Number of faces detected in registered photo: {len(faces)}")
            for idx, face in enumerate(faces):
                print(f"  - Face {idx}: Bounding box = {face['bbox']}")
                # Print sample of the embedding
                emb = face['embedding']
                print(f"    Embedding sample (first 5): {emb[:5]}")
        except Exception as e:
            print(f"Error during face extraction: {e}")

if __name__ == "__main__":
    asyncio.run(main())
