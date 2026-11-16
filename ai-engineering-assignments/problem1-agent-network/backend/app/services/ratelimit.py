"""Fixed-window rate limiter on Redis. Fails open (and logs) if Redis is unreachable so an outage of the
cache does not take the API down; auth and validation still apply."""
from __future__ import annotations

import logging
import time

from redis.exceptions import RedisError

from app.services.queueing import get_redis

log = logging.getLogger(__name__)


def hit(key: str, limit: int, window_seconds: int) -> tuple[bool, int]:
    """Count one request. Returns (allowed, retry_after_seconds)."""
    bucket = int(time.time() // window_seconds)
    redis_key = f"rl:{key}:{bucket}"
    try:
        r = get_redis()
        pipe = r.pipeline()
        pipe.incr(redis_key)
        pipe.expire(redis_key, window_seconds + 1)
        count, _ = pipe.execute()
    except RedisError as exc:
        log.warning("rate limiter unavailable (%s); failing open", exc)
        return True, 0
    if count > limit:
        return False, window_seconds - int(time.time() % window_seconds)
    return True, 0
