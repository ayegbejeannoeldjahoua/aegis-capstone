from __future__ import annotations

from aegis_fabric.token_budgets import build_user_budget_hierarchy, user_monthly_token_budget


def test_budget_hierarchy_is_derived_from_user_monthly_budgets_only():
    assignments = [
        {"tenant_id": "tenant-it", "team_id": "platform", "role_id": "platform-admin", "user_email": "priya@it.example"},
        {"tenant_id": "tenant-it", "team_id": "platform", "role_id": "lead", "user_email": "taylor@it.example"},
        {"tenant_id": "tenant-it", "team_id": "infrastructure", "role_id": "engineer", "user_email": "alex@it.example"},
        {"tenant_id": "tenant-acmecp", "team_id": "research", "role_id": "analyst", "user_email": "jane@acmecp.example"},
    ]
    roles = [
        {"tenant_id": "tenant-it", "role_id": "platform-admin", "capabilities": {"token_budget_per_day": 40_000}},
        {"tenant_id": "tenant-it", "role_id": "lead", "capabilities": {"token_budget_per_day": 20_000}},
        {"tenant_id": "tenant-it", "role_id": "engineer", "capabilities": {"token_budget_per_day": 10_000}},
        {"tenant_id": "tenant-it", "role_id": "tenant-admin", "capabilities": {"token_budget_per_day": 24_000}},
        {"tenant_id": "tenant-acmecp", "role_id": "analyst", "capabilities": {"token_budget_per_day": 10_000}},
    ]

    hierarchy = build_user_budget_hierarchy(assignments, roles, days_in_month=31)

    expected_user_budgets = {
        (row["tenant_id"], row["team_id"], row["role_id"], row["user_email"]): user_monthly_token_budget(
            tenant_id=row["tenant_id"],
            team_id=row["team_id"],
            role_id=row["role_id"],
            user_email=row["user_email"],
            capabilities=next(
                role["capabilities"]
                for role in roles
                if role["tenant_id"] == row["tenant_id"] and role["role_id"] == row["role_id"]
            ),
            days_in_month=31,
        )
        for row in assignments
    }

    assert dict(hierarchy["user_budget_monthly_by_key"]) == expected_user_budgets
    assert hierarchy["tenant_team_role_budget_monthly"][("tenant-it", "platform", "platform-admin")] == (
        expected_user_budgets[("tenant-it", "platform", "platform-admin", "priya@it.example")]
    )
    assert hierarchy["tenant_team_budget_monthly"][("tenant-it", "platform")] == (
        expected_user_budgets[("tenant-it", "platform", "platform-admin", "priya@it.example")]
        + expected_user_budgets[("tenant-it", "platform", "lead", "taylor@it.example")]
    )
    assert hierarchy["tenant_budget_monthly"]["tenant-it"] == (
        hierarchy["tenant_team_budget_monthly"][("tenant-it", "platform")]
        + hierarchy["tenant_team_budget_monthly"][("tenant-it", "infrastructure")]
    )
    assert hierarchy["platform_budget_monthly"] == sum(hierarchy["tenant_budget_monthly"].values())
    assert ("tenant-it", "platform", "tenant-admin") not in hierarchy["tenant_team_role_budget_monthly"]
