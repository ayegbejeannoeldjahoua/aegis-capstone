"""v1.7.0 budgets: per-role rate limit, daily quota, daily token budget (in-memory backend)."""
import aegis_fabric.usage as usage_mod
from aegis_fabric.usage import UsageLimiter, estimate_tokens


def test_rate_limit_per_role():
    u = UsageLimiter()
    out = [u.check_request("acme", "s1", 2, 0)[0] for _ in range(3)]
    assert out == [True, True, False]


def test_daily_quota():
    u = UsageLimiter()
    res = [u.check_request("acme", "s2", 100, 2) for _ in range(3)]
    assert [r[0] for r in res] == [True, True, False]
    assert res[2][1] == "daily_quota_exceeded"


def test_token_budget():
    u = UsageLimiter()
    assert u.check_token_budget("acme", "analyst", 100, 60) == (True, None)
    u.add_tokens("acme", "analyst", 60)
    ok, reason = u.check_token_budget("acme", "analyst", 100, 60)
    assert ok is False and reason == "token_budget_exceeded"


def test_zero_budget_is_unlimited():
    u = UsageLimiter()
    assert u.check_token_budget("acme", "analyst", 0, 10_000_000)[0] is True


def test_fails_open_on_backend_error(monkeypatch):
    u = UsageLimiter()

    class Boom:
        def incr_minute(self, k): raise RuntimeError("redis down")
        def get_day(self, k): raise RuntimeError("redis down")
        def incr_day(self, k, by=1): raise RuntimeError("redis down")

    u.backend = Boom()
    monkeypatch.setattr(usage_mod.settings, "budget_fail_open", True)
    assert u.check_request("acme", "s", 1, 1)[0] is True              # fail open
    assert u.check_token_budget("acme", "r", 100, 999)[0] is True     # fail open


def test_estimate_tokens():
    assert estimate_tokens("a" * 40) == 10
