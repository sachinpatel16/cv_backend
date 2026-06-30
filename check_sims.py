import asyncio
import numpy as np
from main import app
from database.session import SessionLocal
from modules.employees.model import Employee, EmployeeEmbedding
from modules.peopleanalytics.model import EmployeeAttendanceLog, PersonOccurrence, PersonEmbedding
from sqlalchemy import select

async def main():
    async with SessionLocal() as db:
        # Check employee attendance logs
        res = await db.execute(select(EmployeeAttendanceLog).where(EmployeeAttendanceLog.session_id == '98e31786-f142-4667-852a-274d6af4c665'))
        logs = res.scalars().all()
        print("=== EMPLOYEE ATTENDANCE LOGS ===")
        print("Count:", len(logs))
        for l in logs:
            emp_res = await db.execute(select(Employee).where(Employee.id == l.employee_id))
            emp = emp_res.scalars().first()
            name = emp.first_name if emp else "unknown"
            print("  Employee:", name, "first_seen:", l.first_seen)

        # Check visitor occurrences and compare against all employees
        print("")
        print("=== VISITOR OCCURRENCES vs EMPLOYEE EMBEDDINGS ===")
        res_emp = await db.execute(select(Employee).where(Employee.tenant_id == 'efc13bf0-8e19-4984-b6e9-a6781d7e4f02'))
        employees = res_emp.scalars().all()
        emp_embs = {}
        for emp in employees:
            emb_res = await db.execute(select(EmployeeEmbedding).where(EmployeeEmbedding.employee_id == emp.id))
            emb_rec = emb_res.scalars().first()
            if emb_rec:
                e = np.array(emb_rec.embedding, dtype=np.float32)
                e = e / np.linalg.norm(e)
                emp_embs[emp.first_name] = e

        res_occ = await db.execute(select(PersonOccurrence).where(PersonOccurrence.session_id == '98e31786-f142-4667-852a-274d6af4c665'))
        for occ in res_occ.scalars().all():
            res_emb = await db.execute(select(PersonEmbedding).where(PersonEmbedding.identity_id == occ.identity_id))
            emb_rec = res_emb.scalars().first()
            if emb_rec:
                v = np.array(emb_rec.embedding, dtype=np.float32)
                v = v / np.linalg.norm(v)
                print("")
                print("Visitor", str(occ.identity_id)[:8], "(tracker", occ.tracker_id, "):")
                for name, e_emb in emp_embs.items():
                    sim = float(np.dot(e_emb, v))
                    print("  vs", name, ":", round(sim, 4))

asyncio.run(main())
