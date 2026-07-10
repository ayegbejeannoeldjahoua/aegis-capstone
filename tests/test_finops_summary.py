from __future__ import annotations

import pytest

from aegis_fabric import dashboard_api
from aegis_fabric.auth import AdminPrincipal


@pytest.mark.asyncio
async def test_finops_summary_does_not_fake_budget_burn_without_chat_metrics(monkeypatch):
    async def fake_run_db(_fn):
        return {
            "chat_table": False,
            "stage_table": False,
            "chat_rows": [],
            "stage_rows": [],
            "action_rows": [],
            "tenant_rows": [],
            "budget_denies": 2,
            "roles": [
                {
                    "tenant_id": "tenant-acmecp",
                    "role_id": "analyst",
                    "capabilities": {"token_budget_per_day": 1000},
                }
            ],
        }

    monkeypatch.setattr(dashboard_api, "run_db", fake_run_db)

    result = await dashboard_api.finops_summary(
        hours=24,
        principal=AdminPrincipal(scope="platform", tenant_id=None, email="priya@it.example"),
    )

    budget = result["budget_governance"]
    assert budget["daily_budgets"] == []
    assert budget["current_burn_tokens"] is None
    assert budget["remaining_budget_tokens"] is None
    assert budget["budget_refusal_count"] == 2
    assert {
        "metric": "budget_utilization",
        "reason": "dashboard_chat_metrics is required for real token-budget burn",
    } in result["instrumentation_gaps"]
