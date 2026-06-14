from __future__ import annotations

import time
from collections import defaultdict, deque

from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.ratelimit")


class SlidingWindowLimiter:
    """In-process per-key sliding window. Per-replica; resets on restart."""

    def __init__(self, per_minute: int):
        self.per_minute = per_minute
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def allow(self, key: str) -> bool:
        if not settings.rate_limit_enabled:
            return True
        now = time.monotonic()
        window = self._hits[key]
        cutoff = now - 60.0
        while window and window[0] < cutoff:
            window.popleft()
        if len(window) >= self.per_minute:
            return False
        window.append(now)
        return True


class RedisLimiter:
    """Fixed-window counter shared across replicas via Redis (INCR + EXPIRE).

    Consistent for the whole fleet regardless of which replica serves a request.
    Fails OPEN on a Redis error so a limiter outage never takes down the API."""

    def __init__(self, per_minute: int, url: str):
        import redis  # imported lazily so redis is only required when selected

        self.per_minute = per_minute
        self.client = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
        self.client.ping()  # surface connection problems at construction time

    def allow(self, key: str) -> bool:
        if not settings.rate_limit_enabled:
            return True
        window = int(time.time() // 60)
        rkey = f"aegis:rl:{key}:{window}"
        try:
            pipe = self.client.pipeline()
            pipe.incr(rkey)
            pipe.expire(rkey, 90)
            count = pipe.execute()[0]
            return int(count) <= self.per_minute
        except Exception as e:  # noqa: BLE001
            logger.warning("redis rate-limit error, failing open: %s", e)
            return True


def build_limiter():
    if settings.rate_limit_backend == "redis":
        try:
            lim = RedisLimiter(settings.rate_limit_per_minute, settings.redis_url)
            logger.info("rate limiting: redis backend at %s", settings.redis_url)
            return lim
        except Exception as e:  # noqa: BLE001
            logger.warning("redis limiter unavailable (%s); using in-process limiter", e)
    return SlidingWindowLimiter(settings.rate_limit_per_minute)


limiter = build_limiter()
