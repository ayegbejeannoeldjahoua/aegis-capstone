from __future__ import annotations

from collections import Counter
from typing import Any


ROLE_MONTHLY_TOKEN_BUDGETS: dict[str, int] = {
    "viewer": 120_000,
    "restricted-reader": 120_000,
    "auditor": 180_000,
    "analyst-no-egress": 210_000,
    "analyst": 300_000,
    "analyst-low-budget": 3_000,
    "approval-reviewer": 300_000,
    "engineer": 420_000,
    "runtime-denied-engineer": 180_000,
    "runtime-python-engineer": 480_000,
    "lead": 600_000,
    "tenant-admin": 720_000,
    "platform-admin": 1_200_000,
}

TENANT_MULTIPLIERS: dict[str, float] = {
    "tenant-acmecp": 1.10,
    "tenant-betago": 0.90,
    "tenant-gammac": 1.00,
    "tenant-finsvc": 1.10,
    "tenant-hrops": 0.95,
    "tenant-saleseu": 1.00,
    "tenant-engcore": 1.15,
    "tenant-legalco": 0.90,
    "tenant-it": 1.20,
}

TEAM_MULTIPLIERS: dict[str, float] = {
    "data-science": 1.15,
    "engineering": 1.10,
    "finance": 1.00,
    "hr": 0.85,
    "infrastructure": 1.10,
    "legal": 0.90,
    "marketing": 0.90,
    "ml-platform": 1.15,
    "operations": 1.00,
    "platform": 1.20,
    "research": 1.15,
    "sales": 1.00,
    "security": 1.15,
}

DEFAULT_USER_MONTHLY_TOKEN_BUDGET = 180_000
BUDGET_ROUNDING = 5_000


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value.strip():
        import json

        try:
            parsed = json.loads(value)
        except Exception:  # noqa: BLE001
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _positive_int(value: Any) -> int:
    try:
        number = int(value or 0)
    except (TypeError, ValueError):
        return 0
    return max(0, number)


def _round_budget(value: float) -> int:
    return int(round(value / BUDGET_ROUNDING) * BUDGET_ROUNDING)


def user_monthly_token_budget(
    *,
    tenant_id: str,
    team_id: str,
    role_id: str,
    user_email: str,
    capabilities: dict[str, Any] | str | None = None,
    days_in_month: int = 30,
) -> int:
    """Deterministically assign the monthly budget for one real user.

    User-level monthly budgets are the source of truth for analytics. An
    explicit monthly user cap wins first. Otherwise the role's daily cap seeds
    the selected month, and role/monthly constants are only fallback defaults.
    """

    _ = user_email
    caps = _json_dict(capabilities)
    configured_monthly = _positive_int(caps.get("monthly_token_budget") or caps.get("user_monthly_token_budget"))
    if configured_monthly:
        return configured_monthly

    daily_budget = _positive_int(caps.get("token_budget_per_day"))
    if daily_budget:
        base = daily_budget * max(days_in_month, 1)
    else:
        base = ROLE_MONTHLY_TOKEN_BUDGETS.get(role_id, DEFAULT_USER_MONTHLY_TOKEN_BUDGET)

    multiplier = TENANT_MULTIPLIERS.get(tenant_id, 1.0) * TEAM_MULTIPLIERS.get(team_id, 1.0)
    return max(BUDGET_ROUNDING, _round_budget(base * multiplier))


def build_user_budget_hierarchy(
    assignments: list[dict[str, Any]],
    roles: list[dict[str, Any]],
    *,
    days_in_month: int,
) -> dict[str, Any]:
    """Build all FinOps budget levels from assigned users only."""

    role_caps = {
        (row.get("tenant_id"), row.get("role_id")): row.get("capabilities") or {}
        for row in roles
    }
    user_rows: list[dict[str, Any]] = []
    user_budget_monthly: dict[str, int] = {}
    user_budget_monthly_by_key: Counter[tuple[str, str, str, str]] = Counter()
    tenant_team_role_budget_monthly: Counter[tuple[str, str, str]] = Counter()
    tenant_team_budget_monthly: Counter[tuple[str, str]] = Counter()
    tenant_budget_monthly: Counter[str] = Counter()
    team_budget_monthly: Counter[str] = Counter()
    role_budget_monthly: Counter[str] = Counter()

    for assignment in assignments:
        tenant = assignment.get("tenant_id")
        email = str(assignment.get("user_email") or "").lower()
        if not tenant or not email:
            continue
        team = assignment.get("team_id") or "unknown"
        role = assignment.get("role_id") or "unknown"
        budget = user_monthly_token_budget(
            tenant_id=tenant,
            team_id=team,
            role_id=role,
            user_email=email,
            capabilities=role_caps.get((tenant, role), {}),
            days_in_month=days_in_month,
        )
        user_rows.append({
            "tenant_id": tenant,
            "team_id": team,
            "role_id": role,
            "user_email": email,
            "monthly_token_budget": budget,
            "budget_source": "user_monthly_budget",
        })
        user_budget_monthly[email] = budget
        user_budget_monthly_by_key[(tenant, team, role, email)] += budget
        tenant_team_role_budget_monthly[(tenant, team, role)] += budget
        tenant_team_budget_monthly[(tenant, team)] += budget
        tenant_budget_monthly[tenant] += budget
        team_budget_monthly[team] += budget
        role_budget_monthly[role] += budget

    return {
        "users": user_rows,
        "user_budget_monthly": user_budget_monthly,
        "user_budget_monthly_by_key": user_budget_monthly_by_key,
        "tenant_team_role_budget_monthly": tenant_team_role_budget_monthly,
        "tenant_team_budget_monthly": tenant_team_budget_monthly,
        "tenant_budget_monthly": tenant_budget_monthly,
        "team_budget_monthly": team_budget_monthly,
        "role_budget_monthly": role_budget_monthly,
        "platform_budget_monthly": sum(tenant_budget_monthly.values()),
    }
