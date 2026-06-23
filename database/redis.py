import asyncio
import json
import logging
import os
from typing import Optional, Any
import redis.asyncio as aioredis
from configs.base import settings

logger = logging.getLogger(__name__)

redis_client: Optional[aioredis.Redis] = None
redis_pid: Optional[int] = None
redis_loop: Optional[asyncio.AbstractEventLoop] = None

async def init_redis() -> None:
    """Initialize Redis async client and verify connection with ping."""
    global redis_client, redis_pid, redis_loop
    try:
        redis_client = aioredis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True
        )
        # Verify connection
        await redis_client.ping()
        redis_pid = os.getpid()
        redis_loop = asyncio.get_running_loop()
        logger.info(f"Successfully connected to Redis cache at {settings.REDIS_URL} (pid={redis_pid})")
    except Exception as e:
        logger.error(f"Failed to connect to Redis cache at {settings.REDIS_URL}: {e}")
        redis_client = None
        redis_pid = None
        redis_loop = None

async def close_redis() -> None:
    """Gracefully close the Redis connection pool."""
    global redis_client, redis_pid, redis_loop
    if redis_client:
        try:
            await redis_client.close()
            logger.info("Closed Redis cache connection.")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}")
        finally:
            redis_client = None
            redis_pid = None
            redis_loop = None

def get_redis_client() -> Optional[aioredis.Redis]:
    """Get the active Redis client."""
    global redis_client, redis_pid, redis_loop
    if redis_client is not None:
        try:
            current_loop = asyncio.get_running_loop()
        except RuntimeError:
            current_loop = None

        # If the process PID or event loop has changed, reset the client
        if os.getpid() != redis_pid or current_loop is not redis_loop:
            logger.info("Redis client loop or PID mismatch detected (e.g. child process fork). Resetting client.")
            redis_client = None
            redis_pid = None
            redis_loop = None

    return redis_client

async def get_cached(key: str) -> Optional[Any]:
    """Retrieve and deserialize value from cache."""
    client = get_redis_client()
    if not client:
        return None
    try:
        data = await client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Error reading from Redis cache (key={key}): {e}")
    return None

async def set_cached(key: str, value: Any, expire: int = 3600) -> None:
    """Serialize and store value in cache with an expiration time."""
    client = get_redis_client()
    if not client:
        return
    try:
        await client.setex(key, expire, json.dumps(value))
    except Exception as e:
        logger.warning(f"Error writing to Redis cache (key={key}): {e}")

async def delete_cached(*keys: str) -> None:
    """Delete one or more keys from the cache."""
    client = get_redis_client()
    if not client or not keys:
        return
    try:
        await client.delete(*keys)
    except Exception as e:
        logger.warning(f"Error deleting keys {keys} from Redis cache: {e}")

async def clear_cache_by_pattern(pattern: str) -> None:
    """Clear all cache keys matching the given glob pattern."""
    client = get_redis_client()
    if not client:
        return
    try:
        # Use SCAN keys sequentially to avoid blocking the Redis server in production
        cursor = 0
        keys_to_delete = []
        while True:
            cursor, keys = await client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                keys_to_delete.extend(keys)
            if cursor == 0:
                break
        
        if keys_to_delete:
            await client.delete(*keys_to_delete)
            logger.info(f"Cleared {len(keys_to_delete)} keys matching pattern: {pattern}")
    except Exception as e:
        logger.warning(f"Error clearing pattern '{pattern}' from Redis cache: {e}")
