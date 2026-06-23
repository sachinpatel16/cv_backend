import asyncio
import sys
import os

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from modules.peopleanalytics.service import PeopleAnalyticsService
from sqlalchemy import select
from modules.peopleanalytics.model import PeopleAnalyticsSession

async def main():
    async with SessionLocal() as db:
        # Find the latest completed session
        stmt = select(PeopleAnalyticsSession).where(
            PeopleAnalyticsSession.status == "completed"
        ).order_by(PeopleAnalyticsSession.completed_at.desc()).limit(1)
        res = await db.execute(stmt)
        session = res.scalars().first()
        if not session:
            print("No completed sessions found.")
            return

        session_id = session.id
        tenant_id = session.tenant_id
        
        service = PeopleAnalyticsService(db)
        people = await service.get_session_detected_people(session_id, tenant_id)
        
        print(f"Latest completed session: {session_id}")
        print(f"Total / Unique People count in DB session results: {session.unique_person_count}")
        print(f"Detected {len(people)} people list items:")
        for p in people:
            print(f"- Type: {p.type}")
            print(f"  Name: {p.name}")
            print(f"  ID: {p.identity_id}")
            print(f"  First seen: {p.first_seen}s")
            print(f"  Last seen: {p.last_seen}s")
            print(f"  Photo/Crop: {p.photo_path}")
            print("-" * 35)

if __name__ == "__main__":
    asyncio.run(main())
