import json
import logging
from typing import Optional, Any
import redis.asyncio as aioredis
from configs.base import settings

logger = logging.getLogger(__name__)

redis_client: Optional[aioredis.Redis] = None

async def init_redis() -> None:
    """Initialize Redis async client and verify connection with ping."""
    global redis_client
    try:
        redis_client = aioredis.Redis.from_url(
            settings.REDIS_URL,
            decode_responses=True
        )
        # Verify connection
        await redis_client.ping()
        logger.info(f"Successfully connected to Redis cache at {settings.REDIS_URL}")
    except Exception as e:
        logger.error(f"Failed to connect to Redis cache at {settings.REDIS_URL}: {e}")
        redis_client = None

async def close_redis() -> None:
    """Gracefully close the Redis connection pool."""
    global redis_client
    if redis_client:
        try:
            await redis_client.close()
            logger.info("Closed Redis cache connection.")
        except Exception as e:
            logger.warning(f"Error closing Redis connection: {e}")
        finally:
            redis_client = None

def get_redis_client() -> Optional[aioredis.Redis]:
    """Get the active Redis client."""
    return redis_client

async def get_cached(key: str) -> Optional[Any]:
    """Retrieve and deserialize value from cache."""
    if not redis_client:
        return None
    try:
        data = await redis_client.get(key)
        if data:
            return json.loads(data)
    except Exception as e:
        logger.warning(f"Error reading from Redis cache (key={key}): {e}")
    return None

async def set_cached(key: str, value: Any, expire: int = 3600) -> None:
    """Serialize and store value in cache with an expiration time."""
    if not redis_client:
        return
    try:
        await redis_client.setex(key, expire, json.dumps(value))
    except Exception as e:
        logger.warning(f"Error writing to Redis cache (key={key}): {e}")

async def delete_cached(*keys: str) -> None:
    """Delete one or more keys from the cache."""
    if not redis_client or not keys:
        return
    try:
        await redis_client.delete(*keys)
    except Exception as e:
        logger.warning(f"Error deleting keys {keys} from Redis cache: {e}")

async def clear_cache_by_pattern(pattern: str) -> None:
    """Clear all cache keys matching the given glob pattern."""
    if not redis_client:
        return
    try:
        # Use SCAN keys sequentially to avoid blocking the Redis server in production
        cursor = 0
        keys_to_delete = []
        while True:
            cursor, keys = await redis_client.scan(cursor=cursor, match=pattern, count=100)
            if keys:
                keys_to_delete.extend(keys)
            if cursor == 0:
                break
        
        if keys_to_delete:
            await redis_client.delete(*keys_to_delete)
            logger.info(f"Cleared {len(keys_to_delete)} keys matching pattern: {pattern}")
    except Exception as e:
        logger.warning(f"Error clearing pattern '{pattern}' from Redis cache: {e}")
