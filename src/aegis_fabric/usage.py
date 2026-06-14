"""Stateful usage governance: per-role request rate, daily request quota, and a
daily token budget. Backed by Redis (shared across replicas) with an in-process
fallback. Fails OPEN by default (a counter-store outage must never block work);
set AEGIS_BUDGET_FAIL_OPEN=false for hard cost protection.
"""
from __future__ import annotations

import time
from collections import defaultdict

from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.usage")


def _day() -> str:
    return time.strftime("%Y%m%d", time.gmtime())


def estimate_tokens(text: str) -> int:
    """Rough token estimate (~4 chars/token) for providers that return no usage (e.g. Ollama)."""
    return max(1, len(text or "") // 4)


class _MemoryUsage:
    """Per-replica counters; reset on restart. Used when Redis isn't selected/available."""

    def __init__(self) -> None:
        self._minute: dict[str, tuple[int, int]] = {}
        self._day: dict[str, int] = defaultdict(int)
        self._conc: dict[str, int] = defaultdict(int)

    def incr_conc(self, key: str) -> int:
        self._conc[key] += 1
        return self._conc[key]

    def decr_conc(self, key: str) -> int:
        self._conc[key] = max(0, self._conc[key] - 1)
        return self._conc[key]

    def incr_minute(self, key: str) -> int:
        w = int(time.time() // 60)
        win, c = self._minute.get(key, (w, 0))
        c = (c + 1) if win == w else 1
        self._minute[key] = (w, c)
        return c

    def get_day(self, key: str) -> int:
        return self._day.get(f"{key}:{_day()}", 0)

    def incr_day(self, key: str, by: int = 1) -> int:
        k = f"{key}:{_day()}"
        self._day[k] += by
        return self._day[k]


class _RedisUsage:
    def __init__(self, url: str) -> None:
        import redis

        self.r = redis.Redis.from_url(url, socket_timeout=1, socket_connect_timeout=1)
        self.r.ping()

    def incr_minute(self, key: str) -> int:
        w = int(time.time() // 60)
        rk = f"aegis:rl:{key}:{w}"
        pipe = self.r.pipeline()
        pipe.incr(rk)
        pipe.expire(rk, 90)
        return int(pipe.execute()[0])

    def get_day(self, key: str) -> int:
        v = self.r.get(f"aegis:day:{key}:{_day()}")
        return int(v) if v else 0

    def incr_day(self, key: str, by: int = 1) -> int:
        rk = f"aegis:day:{key}:{_day()}"
        pipe = self.r.pipeline()
        pipe.incrby(rk, by)
        pipe.expire(rk, 93600)  # ~26h
        return int(pipe.execute()[0])

    def incr_conc(self, key: str) -> int:
        rk = f"aegis:conc:{key}"
        pipe = self.r.pipeline()
        pipe.incr(rk)
        pipe.expire(rk, 120)  # safety TTL so a crashed request frees its slot
        return int(pipe.execute()[0])

    def decr_conc(self, key: str) -> int:
        return int(self.r.decr(f"aegis:conc:{key}"))


class UsageLimiter:
    def __init__(self) -> None:
        self.backend = None
        if settings.rate_limit_backend == "redis":
            try:
                self.backend = _RedisUsage(settings.redis_url)
                logger.info("usage governance: redis backend at %s", settings.redis_url)
            except Exception as e:  # noqa: BLE001
                logger.warning("usage redis unavailable (%s); using in-process counters", e)
        if self.backend is None:
            self.backend = _MemoryUsage()

    def _guard(self, fn, default):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            mode = "open" if settings.budget_fail_open else "closed"
            logger.warning("usage backend error, fail-%s: %s", mode, e)
            if settings.budget_fail_open:
                return default
            raise

    def check_request(self, tenant: str, sub: str, per_minute: int, daily_quota: int) -> tuple[bool, str | None]:
        """Per-role per-minute rate limit + daily request quota; counts the request."""
        if not settings.rate_limit_enabled:
            return True, None
        limit = per_minute if per_minute and per_minute > 0 else settings.rate_limit_per_minute
        key = f"{tenant}:{sub}"
        if self._guard(lambda: self.backend.incr_minute(key), default=1) > limit:
            return False, "rate_limited"
        if daily_quota and daily_quota > 0:
            if self._guard(lambda: self.backend.incr_day(f"req:{key}", 1), default=1) > daily_quota:
                return False, "daily_quota_exceeded"
        return True, None

    def check_token_budget(self, tenant: str, role: str, budget: int, projected: int) -> tuple[bool, str | None]:
        if not budget or budget <= 0:
            return True, None
        ok = self._guard(lambda: self.backend.get_day(f"tok:{tenant}:{role}") + projected <= budget, default=True)
        return ok, (None if ok else "token_budget_exceeded")

    def add_tokens(self, tenant: str, role: str, tokens: int) -> None:
        if tokens and tokens > 0:
            self._guard(lambda: self.backend.incr_day(f"tok:{tenant}:{role}", int(tokens)), default=0)

    def acquire_slot(self, tenant: str, sub: str, max_concurrent: int) -> bool:
        if not max_concurrent or max_concurrent <= 0:
            return True
        cur = self._guard(lambda: self.backend.incr_conc(f"{tenant}:{sub}"), default=1)
        if cur > max_concurrent:
            self._guard(lambda: self.backend.decr_conc(f"{tenant}:{sub}"), default=0)
            return False
        return True

    def release_slot(self, tenant: str, sub: str, max_concurrent: int) -> None:
        if max_concurrent and max_concurrent > 0:
            self._guard(lambda: self.backend.decr_conc(f"{tenant}:{sub}"), default=0)


usage = UsageLimiter()
