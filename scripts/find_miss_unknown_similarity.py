import asyncio
import sys
import os
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from modules.employees.model import Employee, EmployeeEmbedding
from modules.peopleanalytics.model import PersonIdentity, PersonEmbedding, PersonOccurrence, PeopleAnalyticsSession
from sqlalchemy import select

async def main():
    async with SessionLocal() as db:
        # 1. Fetch employee and embedding
        emp_res = await db.execute(select(Employee).where(Employee.employee_code == "12"))
        emp = emp_res.scalars().first()
        if not emp:
            print("Employee 'miss unknown' (Code 12) not found.")
            return
            
        emb_res = await db.execute(select(EmployeeEmbedding).where(EmployeeEmbedding.employee_id == emp.id))
        emp_emb_obj = emb_res.scalars().first()
        if not emp_emb_obj:
            print("No registered face embedding for miss unknown.")
            return
            
        emp_emb = np.array(emp_emb_obj.embedding, dtype=np.float32)
        emp_emb = emp_emb / np.linalg.norm(emp_emb)
        print(f"Loaded registered embedding for miss unknown (ID: {emp.id}).")

        # 2. Get all visitor embeddings in the system
        stmt = select(PersonEmbedding, PersonOccurrence, PeopleAnalyticsSession).join(
            PersonOccurrence, PersonOccurrence.identity_id == PersonEmbedding.identity_id
        ).join(
            PeopleAnalyticsSession, PeopleAnalyticsSession.id == PersonOccurrence.session_id
        )
        results = (await db.execute(stmt)).all()
        
        print(f"Comparing against {len(results)} visitor embedding records in the database:")
        
        matches = []
        for p_emb_obj, occ, session in results:
            v_emb = np.array(p_emb_obj.embedding, dtype=np.float32)
            v_norm = np.linalg.norm(v_emb)
            if v_norm > 0:
                v_emb = v_emb / v_norm
            
            sim = float(np.dot(emp_emb, v_emb))
            matches.append({
                "sim": sim,
                "session_id": str(session.id),
                "video": session.video_name,
                "timestamp": p_emb_obj.timestamp,
                "crop_path": occ.crop_path,
                "identity_id": str(occ.identity_id)
            })
            
        # Sort matches by similarity score descending
        matches.sort(key=lambda x: x["sim"], reverse=True)
        
        print("\nTop 10 highest similarity matches across all sessions:")
        for idx, m in enumerate(matches[:10]):
            print(f"{idx+1}. Similarity: {m['sim']:.4f}")
            print(f"   Session ID: {m['session_id']}")
            print(f"   Video: {m['video']}")
            print(f"   Timestamp: {m['timestamp']}s")
            print(f"   Visitor ID: {m['identity_id']}")
            print(f"   Crop Path: {m['crop_path']}")
            print("-" * 30)

if __name__ == "__main__":
    asyncio.run(main())
