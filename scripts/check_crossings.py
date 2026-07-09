import asyncio
import sys
import os
import uuid

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from modules.employees.model import Employee
from modules.peopleanalytics.model import PeopleAnalyticsSession

async def main():
    async with SessionLocal() as db:
        session_id = uuid.UUID('3657af9c-e695-4322-be34-fa1291093528')
        s = await db.get(PeopleAnalyticsSession, session_id)
        if s:
            print("Path:", s.video_path)
        else:
            print("Session not found.")

if __name__ == "__main__":
    asyncio.run(main())
