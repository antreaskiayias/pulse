import os
import redis.asyncio as redis

_pool = None

def get_redis():
    global _pool
    if _pool is None:
        _pool = redis.from_url(
            os.getenv("REDIS_URL", "redis://localhost:6379"),
            decode_responses=True,
        )
    return _pool
