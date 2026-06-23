import asyncio
import sys
import os
import numpy as np

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database.session import SessionLocal
from modules.employees.model import Employee, EmployeeEmbedding
from modules.peopleanalytics.model import PersonIdentity, PersonEmbedding, PersonOccurrence
from sqlalchemy import select

async def main():
    session_id_str = "60998664-aee2-4347-a9c4-c8c9c0916cf4"
    emp_name = "miss  unknown"
    
    async with SessionLocal() as db:
        # 1. Fetch employee and embedding
        emp_res = await db.execute(select(Employee).where(Employee.first_name == "miss", Employee.last_name == "unknown"))
        emp = emp_res.scalars().first()
        if not emp:
            # Try by code 12
            emp_res = await db.execute(select(Employee).where(Employee.employee_code == "12"))
            emp = emp_res.scalars().first()
            
        if not emp:
            print("Employee 'miss unknown' not found.")
            return
            
        emb_res = await db.execute(select(EmployeeEmbedding).where(EmployeeEmbedding.employee_id == emp.id))
        emp_emb_obj = emb_res.scalars().first()
        if not emp_emb_obj:
            print(f"Employee {emp.first_name} {emp.last_name} has no registered face embedding.")
            return
            
        emp_emb = np.array(emp_emb_obj.embedding, dtype=np.float32)
        emp_emb = emp_emb / np.linalg.norm(emp_emb)
        print(f"Loaded embedding for {emp.first_name} {emp.last_name} (Code: {emp.employee_code}).")

        # 2. Get all occurrences in this session
        import uuid
        session_id = uuid.UUID(session_id_str)
        occ_res = await db.execute(select(PersonOccurrence).where(PersonOccurrence.session_id == session_id))
        occurrences = occ_res.scalars().all()
        print(f"Found {len(occurrences)} visitor occurrences in session {session_id_str}:")
        
        # 3. For each unique identity in this session, check its embeddings
        unique_identities = set(occ.identity_id for occ in occurrences)
        print(f"Unique visitor identities in session: {len(unique_identities)}")
        
        for identity_id in unique_identities:
            # Get embeddings for this identity
            p_emb_res = await db.execute(select(PersonEmbedding).where(PersonEmbedding.identity_id == identity_id))
            p_embs = p_emb_res.scalars().all()
            print(f"\nIdentity {identity_id} (Visitor #{str(identity_id)[:4]}) has {len(p_embs)} embedding(s):")
            
            best_sim = -1.0
            for idx, p_emb_obj in enumerate(p_embs):
                v_emb = np.array(p_emb_obj.embedding, dtype=np.float32)
                v_norm = np.linalg.norm(v_emb)
                if v_norm > 0:
                    v_emb = v_emb / v_norm
                
                sim = float(np.dot(emp_emb, v_emb))
                print(f"  - Embedding {idx} (timestamp {p_emb_obj.timestamp}s): Similarity to 'miss unknown' = {sim:.4f}")
                if sim > best_sim:
                    best_sim = sim
            print(f"  -> Best similarity for Visitor #{str(identity_id)[:4]} = {best_sim:.4f}")

if __name__ == "__main__":
    asyncio.run(main())
