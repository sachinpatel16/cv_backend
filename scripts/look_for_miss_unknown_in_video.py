import asyncio
import sys
import os
import cv2
import numpy as np

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
    video_path = "storage/people_analytics_inputs/e555b489-b357-470d-abd9-33648e6aec50/e2175a4c-c15e-4942-b81e-905008041524.mp4"
    dest_dir = "storage/temp_debug/miss_unknown_search"
    os.makedirs(dest_dir, exist_ok=True)
    
    async with SessionLocal() as db:
        # Load employee embedding
        emp_res = await db.execute(select(Employee).where(Employee.employee_code == "12"))
        emp = emp_res.scalars().first()
        if not emp:
            print("Employee 'miss unknown' not found.")
            return
            
        emb_res = await db.execute(select(EmployeeEmbedding).where(EmployeeEmbedding.employee_id == emp.id))
        emp_emb_obj = emb_res.scalars().first()
        if not emp_emb_obj:
            print("No registered face embedding for miss unknown.")
            return
            
        emp_emb = np.array(emp_emb_obj.embedding, dtype=np.float32)
        emp_emb = emp_emb / np.linalg.norm(emp_emb)
        print(f"Scanning video for: {emp.first_name} {emp.last_name}")

        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            print(f"Could not open video {video_path}")
            return
            
        fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        frame_idx = 0
        matches_found = []
        
        while cap.isOpened():
            ret, frame = cap.read()
            if not ret or frame is None:
                break
                
            # Check every 5 frames to speed up search
            if frame_idx % 5 != 0:
                frame_idx += 1
                continue
                
            timestamp = frame_idx / fps
            
            # Encode frame to JPEG
            _, encoded_img = cv2.imencode(".jpg", frame)
            frame_bytes = encoded_img.tobytes()
            
            try:
                faces = face_rec_service.extract_faces(frame_bytes)
                for idx, face in enumerate(faces):
                    v_emb = np.array(face["embedding"], dtype=np.float32)
                    v_norm = np.linalg.norm(v_emb)
                    if v_norm > 0:
                        v_emb = v_emb / v_norm
                        
                    sim = float(np.dot(emp_emb, v_emb))
                    if sim > 0.30:  # Check anything above 0.30
                        bbox = face["bbox"]
                        x1, y1, x2, y2 = bbox
                        crop = frame[max(0, y1):min(frame.shape[0], y2), max(0, x1):min(frame.shape[1], x2)]
                        
                        crop_name = f"match_frame_{frame_idx}_sim_{sim:.4f}.jpg"
                        crop_path = os.path.join(dest_dir, crop_name)
                        cv2.imwrite(crop_path, crop)
                        
                        matches_found.append({
                            "frame": frame_idx,
                            "timestamp": timestamp,
                            "sim": sim,
                            "crop_path": crop_path
                        })
            except Exception as e:
                print(f"Error at frame {frame_idx}: {e}")
                
            frame_idx += 1
            
        cap.release()
        
        print(f"\nScan complete. Found {len(matches_found)} potential matches above 0.30 similarity:")
        # Sort matches by similarity descending
        matches_found.sort(key=lambda x: x["sim"], reverse=True)
        for m in matches_found[:10]:
            print(f"- Similarity {m['sim']:.4f} at {m['timestamp']:.2f}s (Frame {m['frame']}), saved to {m['crop_path']}")

if __name__ == "__main__":
    asyncio.run(main())
