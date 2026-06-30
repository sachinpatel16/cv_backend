import json
import uuid
import numpy as np
from sqlalchemy import select
from database.redis import get_redis_client, get_cached, set_cached, delete_cached
from modules.employees.model import Employee, EmployeeEmbedding

async def get_cached_employee_embeddings(db, tenant_id: uuid.UUID) -> list[tuple[Employee, np.ndarray]]:
    """
    Retrieves employee details and their face embeddings for a tenant.
    Utilizes Redis to share the cache across workers/APIs, and falls back to
    the PostgreSQL database on cache miss, populating Redis.
    """
    cache_key = f"tenant:{tenant_id}:employee_face_embeddings"
    
    # Ensure Redis client is initialized
    redis_client = get_redis_client()
    if not redis_client:
        from database.redis import init_redis
        try:
            await init_redis()
            redis_client = get_redis_client()
        except Exception:
            redis_client = None
            
    cached_data = await get_cached(cache_key) if redis_client else None
    
    if cached_data is not None:
        results = []
        for item in cached_data:
            emp = Employee(
                id=uuid.UUID(item["id"]),
                tenant_id=tenant_id,
                first_name=item["first_name"],
                last_name=item["last_name"],
                employee_code=item["employee_code"],
                photo_path=item["photo_path"]
            )
            emb = np.array(item["embedding"], dtype=np.float32)
            results.append((emp, emb))
        return results
        
    # Cache miss: query database
    stmt = (
        select(Employee, EmployeeEmbedding.embedding)
        .join(EmployeeEmbedding, EmployeeEmbedding.employee_id == Employee.id)
        .where(
            Employee.tenant_id == tenant_id,
            Employee.is_delete == False,
            Employee.is_active == True,
            EmployeeEmbedding.is_delete == False
        )
    )
    res = await db.execute(stmt)
    rows = res.all()
    
    results = []
    cache_to_save = []
    for emp, emb in rows:
        # Convert emb to numpy array for consistency
        emb_arr = np.array(emb, dtype=np.float32)
        results.append((emp, emb_arr))
        cache_to_save.append({
            "id": str(emp.id),
            "first_name": emp.first_name,
            "last_name": emp.last_name,
            "employee_code": emp.employee_code,
            "photo_path": emp.photo_path,
            "embedding": emb_arr.tolist()
        })
        
    # Save to Redis (expires in 24 hours)
    if redis_client:
        await set_cached(cache_key, cache_to_save, expire=86400)
        
    return results

async def invalidate_employee_embeddings_cache(tenant_id: uuid.UUID) -> None:
    """Invalidates the cached employee embeddings for a tenant in Redis."""
    cache_key = f"tenant:{tenant_id}:employee_face_embeddings"
    redis_client = get_redis_client()
    if not redis_client:
        from database.redis import init_redis
        try:
            await init_redis()
            redis_client = get_redis_client()
        except Exception:
            redis_client = None
    if redis_client:
        await delete_cached(cache_key)
