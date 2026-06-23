import asyncio
import sys
import os
import shutil

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from modules.employees.model import Employee
from modules.peopleanalytics.model import PersonOccurrence
from sqlalchemy import select

async def main():
    dest_dir = "/app/storage/temp_debug"
    os.makedirs(dest_dir, exist_ok=True)
    
    async with SessionLocal() as db:
        # Copy employee photo
        emp_res = await db.execute(select(Employee).where(Employee.employee_code == "12"))
        emp = emp_res.scalars().first()
        if emp and os.path.exists(emp.photo_path):
            shutil.copy(emp.photo_path, os.path.join(dest_dir, "miss_unknown_registered.jpg"))
            print("Copied registered photo of miss unknown.")
        else:
            print("Registered photo of miss unknown not found.")

        # Copy visitor crops
        import uuid
        session_id = uuid.UUID("60998664-aee2-4347-a9c4-c8c9c0916cf4")
        occ_res = await db.execute(select(PersonOccurrence).where(PersonOccurrence.session_id == session_id))
        occurrences = occ_res.scalars().all()
        
        copied_count = 0
        for occ in occurrences:
            if occ.crop_path and os.path.exists(occ.crop_path):
                filename = f"visitor_{str(occ.identity_id)[:4]}_{occ.tracker_id}.jpg"
                shutil.copy(occ.crop_path, os.path.join(dest_dir, filename))
                print(f"Copied visitor crop: {filename}")
                copied_count += 1
                if copied_count >= 5: # copy at most 5 crops to avoid bloat
                    break

if __name__ == "__main__":
    asyncio.run(main())
