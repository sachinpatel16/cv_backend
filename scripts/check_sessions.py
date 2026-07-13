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
from sqlalchemy import select

async def main():
    async with SessionLocal() as db:
        res = await db.execute(select(PeopleAnalyticsSession))
        sessions = res.scalars().all()
        if not sessions:
            print("No sessions found in the database.")
            return
            
        print(f"Found {len(sessions)} session(s):")
        for s in sessions:
            print(f"- ID: {s.id}")
            print(f"  Status: {s.status}")
            print(f"  Video Path: {s.video_path}")
            print(f"  Output Video Path: {s.output_video_path}")
            print(f"  Unique People: {s.unique_person_count}")
            print(f"  Total People: {s.total_person_count}")
            print(f"  Peak Occupancy: {s.peak_occupancy}")
            print(f"  Flags: EMP={s.track_employees}, NEW_VIS={s.register_new_visitors}, REP_VIS={s.track_repeat_visitors}, LINE={s.line_crossing_analysis}, OCC={s.track_occupancy}")
            print(f"  Created At: {s.created_at}")
            print(f"  Completed At: {s.completed_at}")
            print("-" * 40)

if __name__ == "__main__":
    asyncio.run(main())
