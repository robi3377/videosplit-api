import logging
import time
from typing import Optional

import redis.asyncio as aioredis

from app.saas_layer.core.config import settings

logger = logging.getLogger(__name__)

_redis_client: Optional[aioredis.Redis] = None


async def get_redis() -> Optional[aioredis.Redis]:
    """
    Return the singleton async Redis client.
    Returns None if Redis is unavailable (so callers can fail open).
    """
    global _redis_client
    if _redis_client is None:
        try:
            _redis_client = aioredis.from_url(
                settings.REDIS_URL,
                encoding="utf-8",
                decode_responses=True,
                socket_connect_timeout=2,
                socket_timeout=2,
            )
            # Verify connection
            await _redis_client.ping()
            logger.info("Redis connected: %s", settings.REDIS_URL)
        except Exception as exc:
            logger.warning("Redis unavailable (%s) — rate limiting disabled", exc)
            _redis_client = None
    return _redis_client


async def close_redis() -> None:
    """Close the Redis connection. Called on app shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None
        logger.info("Redis connection closed")


async def check_rate_limit(
    key: str,
    max_requests: int,
    window_seconds: int = 60,
) -> tuple[bool, int]:
    """
    Sliding-window rate limit using Redis INCR + EXPIRE.

    Returns (allowed: bool, current_count: int).
    If Redis is unavailable, returns (True, 0) — fail open.
    """
    redis = await get_redis()
    if redis is None:
        return True, 0

    try:
        full_key = f"{settings.REDIS_KEY_PREFIX}:rl:{key}"
        count = await redis.incr(full_key)
        if count == 1:
            await redis.expire(full_key, window_seconds)
        allowed = count <= max_requests
        return allowed, count
    except Exception as exc:
        logger.warning("Redis rate-limit check failed (%s) — allowing request", exc)
        return True, 0


def rate_limit_key(user_id: int, endpoint: str) -> str:
    """
    Build a namespaced rate-limit key scoped to the current 1-minute bucket.
    Example: "videosplit:rl:user:42:split:28455120"
    """
    minute_bucket = int(time.time() // 60)
    return f"user:{user_id}:{endpoint}:{minute_bucket}"
