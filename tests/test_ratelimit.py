import aegis_fabric.ratelimit as rl


def test_memory_limiter_blocks_over_limit(monkeypatch):
    monkeypatch.setattr(rl.settings, "rate_limit_enabled", True)
    lim = rl.SlidingWindowLimiter(3)
    assert all(lim.allow("k") for _ in range(3))
    assert lim.allow("k") is False
    assert lim.allow("other") is True


def test_memory_limiter_disabled(monkeypatch):
    monkeypatch.setattr(rl.settings, "rate_limit_enabled", False)
    lim = rl.SlidingWindowLimiter(1)
    assert all(lim.allow("k") for _ in range(5))


class _Pipe:
    def __init__(self, rc):
        self.rc = rc
        self.ops = []

    def incr(self, k):
        self.ops.append(("incr", k))
        return self

    def expire(self, k, t):
        self.ops.append(("expire", k))
        return self

    def execute(self):
        if self.rc.fail:
            raise RuntimeError("redis down")
        out = []
        for op in self.ops:
            if op[0] == "incr":
                self.rc.store[op[1]] = self.rc.store.get(op[1], 0) + 1
                out.append(self.rc.store[op[1]])
            else:
                out.append(True)
        return out


class FakeRedis:
    def __init__(self):
        self.store = {}
        self.fail = False

    def ping(self):
        return True

    def pipeline(self):
        return _Pipe(self)


def _redis_limiter(per_minute, fake):
    lim = rl.RedisLimiter.__new__(rl.RedisLimiter)  # bypass __init__ (no live redis)
    lim.per_minute = per_minute
    lim.client = fake
    return lim


def test_redis_limiter_counts(monkeypatch):
    monkeypatch.setattr(rl.settings, "rate_limit_enabled", True)
    lim = _redis_limiter(2, FakeRedis())
    assert lim.allow("k") is True
    assert lim.allow("k") is True
    assert lim.allow("k") is False  # 3rd in window > 2


def test_redis_limiter_fails_open(monkeypatch):
    monkeypatch.setattr(rl.settings, "rate_limit_enabled", True)
    fr = FakeRedis()
    fr.fail = True
    lim = _redis_limiter(1, fr)
    assert lim.allow("k") is True  # limiter error must not block traffic
