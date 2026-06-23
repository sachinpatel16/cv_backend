import asyncio
import os
import sys
import numpy as np
from sqlalchemy import select, delete

# Add parent directory to sys.path so we can import modules
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from database.session import SessionLocal
from modules.employees.model import Employee, EmployeeEmbedding
from modules.peopleanalytics.model import EmployeeAttendanceLog
from services.ai.face_recognition import face_rec_service
from modules.employees.cache import invalidate_employee_embeddings_cache

async def migrate():
    print("Starting employee face embedding migration...")
    async with SessionLocal() as db:
        stmt = select(Employee).where(Employee.is_delete == False)
        res = await db.execute(stmt)
        employees = res.scalars().all()
        
        print(f"Found {len(employees)} active employees in the database.")
        
        success_count = 0
        failure_count = 0
        
        for emp in employees:
            print(f"Processing employee {emp.first_name} {emp.last_name} ({emp.employee_code})...")
            if not emp.photo_path or not os.path.exists(emp.photo_path):
                print(f"  [WARNING] Photo file does not exist at '{emp.photo_path}'. Skipping.")
                failure_count += 1
                continue
                
            try:
                with open(emp.photo_path, "rb") as f:
                    image_bytes = f.read()
                    
                faces = face_rec_service.extract_faces(image_bytes)
                if not faces:
                    print("  [WARNING] No faces detected in photo. Skipping.")
                    failure_count += 1
                    continue
                    
                largest_face = max(faces, key=lambda f: (f["bbox"][2] - f["bbox"][0]) * (f["bbox"][3] - f["bbox"][1]))
                embedding = largest_face["embedding"]
                bbox = largest_face["bbox"]
                
                # Delete existing embedding
                await db.execute(delete(EmployeeEmbedding).where(EmployeeEmbedding.employee_id == emp.id))
                
                # Create new embedding
                new_emb = EmployeeEmbedding(
                    employee_id=emp.id,
                    embedding=embedding,
                    bbox=bbox
                )
                db.add(new_emb)
                await db.flush()
                
                # Invalidate Redis cache
                await invalidate_employee_embeddings_cache(emp.tenant_id)
                
                print("  [SUCCESS] Face embedding extracted and updated successfully.")
                success_count += 1
            except Exception as e:
                print(f"  [ERROR] Failed to process employee: {e}")
                failure_count += 1
                
        await db.commit()
        print(f"\nMigration completed: {success_count} succeeded, {failure_count} failed.")

if __name__ == "__main__":
    asyncio.run(migrate())
