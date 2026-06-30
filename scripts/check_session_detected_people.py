import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from modules.peopleanalytics.service import PeopleAnalyticsService
from sqlalchemy import select
from modules.peopleanalytics.model import PeopleAnalyticsSession, PersonOccurrence

async def main():
    async with SessionLocal() as db:
        # Find all completed sessions with people
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.status == "completed",
            PeopleAnalyticsSession.unique_person_count > 0
        ).order_by(PeopleAnalyticsSession.completed_at.desc())
        res = await db.execute(stmt)
        sessions = res.scalars().all()
        if not sessions:
            print("No completed sessions with unique_person_count > 0 found.")
            return

        for session in sessions:
            session_id = session.id
            tenant_id = session.tenant_id
        
            service = PeopleAnalyticsService(db)
            try:
                people = await service.get_session_detected_people(session_id, tenant_id)
            except Exception as e:
                continue
            
            print(f"Session: {session_id} | Video: {session.video_name}")
            print(f"  Status: {session.status}")
            print(f"  Unique: {session.unique_person_count} | Total: {session.total_person_count}")
            print(f"  Visitor count: {session.visitor_count} | Employee count: {session.employee_count}")
            print(f"  First time visitors: {session.first_time_visitor_count}")
            
            # Query raw occurrences
            stmt_occ = select(PersonOccurrence).where(
                PersonOccurrence.session_id == session_id,
                PersonOccurrence.is_delete == False
            ).order_by(PersonOccurrence.first_seen.asc())
            res_occ = await db.execute(stmt_occ)
            raw_occs = res_occ.scalars().all()
            
            print(f"  Total raw occurrences in DB: {len(raw_occs)}")
            for i, occ in enumerate(raw_occs):
                print(f"  Occ #{i}: ID={occ.identity_id}, Tracker={occ.tracker_id}, Crop={occ.crop_path}")
                
            print("  " + "-" * 50)
            
            people = await service.get_session_detected_people(session_id, tenant_id)
            print(f"  DetectedPeople returned by service: {len(people)}")
            for p in people:
                print(f"  - {p.type} Name: {p.name}, ID: {p.identity_id}, Crop: {p.photo_path}")
            print("=" * 60)

if __name__ == "__main__":
    asyncio.run(main())
