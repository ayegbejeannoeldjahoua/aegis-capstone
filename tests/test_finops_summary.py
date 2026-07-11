from __future__ import annotations

from datetime import datetime, timezone

import pytest

from aegis_fabric import dashboard_api
from aegis_fabric.auth import AdminPrincipal
from aegis_fabric.operational_metrics import finops_event_payload
from aegis_fabric.token_budgets import build_user_budget_hierarchy


@pytest.mark.asyncio
async def test_finops_summary_does_not_fake_budget_burn_without_chat_metrics(monkeypatch):
    async def fake_run_db(_fn, *args, **kwargs):
        return {
            "chat_table": False,
            "stage_table": False,
            "finops_table": False,
            "chat_rows": [],
            "stage_rows": [],
            "event_rows": [],
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
    assert budget["event_count"] == 0
    assert result["summary"]["requests_recorded"] == 0
    assert result["summary"]["token_utilization"] == {
        "used_tokens": 0,
        "budget_tokens": 0,
        "usage_percent": 0,
    }
    assert result["summary"]["budget_utilization"] == {
        "used_tokens": 0,
        "budget_tokens": 0,
        "usage_percent": 0,
    }
    assert result["filters"]["tenants"][0] == {"value": "", "label": "All tenants"}
    assert result["bar_chart"]["level"] == "tenant"


@pytest.mark.asyncio
async def test_finops_summary_returns_empty_analytics_contract_without_rows(monkeypatch):
    async def fake_run_db(_fn, *args, **kwargs):
        return {
            "period": {"month": "2026-07", "start": None, "end": None, "days_in_month": 31},
            "chat_table": True,
            "stage_table": True,
            "finops_table": True,
            "chat_rows": [],
            "stage_rows": [],
            "event_rows": [],
            "action_rows": [],
            "tenant_rows": [],
            "budget_denies": 0,
            "roles": [],
            "assignments": [],
        }

    monkeypatch.setattr(dashboard_api, "run_db", fake_run_db)

    result = await dashboard_api.finops_summary(
        month="2026-07",
        principal=AdminPrincipal(scope="platform", tenant_id=None, email="priya@it.example"),
    )

    assert result["summary"]["token_utilization"] == {"used_tokens": 0, "budget_tokens": 0, "usage_percent": 0}
    assert result["summary"]["budget_utilization"] == {"used_tokens": 0, "budget_tokens": 0, "usage_percent": 0}
    assert result["summary"]["budget_refusals"] == 0
    assert result["pie_charts"] == {"tenants": [], "tenant_teams": [], "tenant_team_roles": []}
    assert result["filters"]["tenants"] == [{"value": "", "label": "All tenants"}]
    assert result["bar_chart"] == {
        "level": "tenant",
        "rows": [],
        "selected": {"tenant": "", "team": "", "role": "", "user": ""},
    }
    assert result["notes"] == [
        "No token usage recorded for this month yet.",
        "No token budgets are configured for the selected scope.",
    ]


@pytest.mark.asyncio
async def test_finops_summary_budget_totals_are_derived_from_assigned_users(monkeypatch):
    now = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)
    roles = [
        {"tenant_id": "tenant-it", "role_id": "platform-admin", "capabilities": {"token_budget_per_day": 40_000}},
        {"tenant_id": "tenant-it", "role_id": "lead", "capabilities": {"token_budget_per_day": 20_000}},
        {"tenant_id": "tenant-it", "role_id": "tenant-admin", "capabilities": {"token_budget_per_day": 24_000}},
        {"tenant_id": "tenant-acmecp", "role_id": "analyst", "capabilities": {"token_budget_per_day": 10_000}},
    ]
    assignments = [
        {"tenant_id": "tenant-it", "team_id": "platform", "role_id": "platform-admin", "user_email": "priya@it.example"},
        {"tenant_id": "tenant-it", "team_id": "platform", "role_id": "lead", "user_email": "taylor@it.example"},
        {"tenant_id": "tenant-acmecp", "team_id": "research", "role_id": "analyst", "user_email": "jane@acmecp.example"},
    ]
    hierarchy = build_user_budget_hierarchy(assignments, roles, days_in_month=31)

    async def fake_run_db(fn, *args, **kwargs):
        if fn is dashboard_api.load_monthly_activity:
            return {
                "period": {"month": "2026-07", "start": now, "end": now, "days_in_month": 31},
                "events": [],
                "roles": roles,
                "assignments": assignments,
                "source_counts": {},
            }
        return {
            "period": {"month": "2026-07", "start": now, "end": now, "days_in_month": 31},
            "chat_table": True,
            "stage_table": True,
            "finops_table": True,
            "chat_rows": [],
            "stage_rows": [],
            "event_rows": [],
            "action_rows": [],
            "tenant_rows": [],
            "budget_denies": 0,
            "roles": roles,
            "assignments": assignments,
        }

    monkeypatch.setattr(dashboard_api, "run_db", fake_run_db)

    result = await dashboard_api.finops_summary(
        month="2026-07",
        principal=AdminPrincipal(scope="platform", tenant_id=None, email="priya@it.example"),
    )

    expected_platform_budget = hierarchy["platform_budget_monthly"]
    assert result["summary"]["token_utilization"]["budget_tokens"] == expected_platform_budget
    assert result["summary"]["budget_utilization"]["budget_tokens"] == expected_platform_budget
    assert result["budget_governance"]["current_burn_tokens"] == 0
    assert result["budget_governance"]["remaining_budget_tokens"] == expected_platform_budget
    assert {
        (row["tenant_id"], row["team_id"], row["role_id"]): row["monthly_token_budget"]
        for row in result["budget_governance"]["daily_budgets"]
    } == dict(hierarchy["tenant_team_role_budget_monthly"])
    assert result["pie_charts"]["tenants"] == [
        {
            "label": "tenant-it",
            "tokens": 0,
            "used_tokens": 0,
            "budget_tokens": hierarchy["tenant_budget_monthly"]["tenant-it"],
            "requests": 0,
            "usage_percent": 0,
            "tenant_id": "tenant-it",
        },
        {
            "label": "tenant-acmecp",
            "tokens": 0,
            "used_tokens": 0,
            "budget_tokens": hierarchy["tenant_budget_monthly"]["tenant-acmecp"],
            "requests": 0,
            "usage_percent": 0,
            "tenant_id": "tenant-acmecp",
        },
    ]


@pytest.mark.asyncio
async def test_finops_summary_counts_unmetered_provider_activity_without_fake_cost(monkeypatch):
    now = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)

    async def fake_run_db(_fn, *args, **kwargs):
        return {
            "chat_table": True,
            "stage_table": True,
            "finops_table": True,
            "chat_rows": [],
            "stage_rows": [],
            "event_rows": [
                {
                    "id": 1,
                    "created_at": now,
                    "trace_id": "trace-1",
                    "request_id": None,
                    "tenant_id": "tenant-acmecp",
                    "user_email": "jane@acmecp.example",
                    "role": "analyst",
                    "action": "chat.turn",
                    "decision": "skipped",
                    "provider": "ollama",
                    "model": "llama3.1",
                    "input_tokens": 0,
                    "output_tokens": 0,
                    "total_tokens": 0,
                    "estimated_cost_usd": None,
                    "budget_limit_usd": None,
                    "budget_remaining_usd": None,
                    "budget_limit_tokens": None,
                    "budget_remaining_tokens": None,
                    "budget_profile": {},
                    "reason": None,
                    "reached_model": True,
                    "blocked_before_model": False,
                    "status": "success",
                    "metadata": {},
                }
            ],
            "action_rows": [],
            "tenant_rows": [],
            "budget_denies": 0,
            "roles": [],
        }

    monkeypatch.setattr(dashboard_api, "run_db", fake_run_db)

    result = await dashboard_api.finops_summary(
        hours=24,
        principal=AdminPrincipal(scope="platform", tenant_id=None, email="priya@it.example"),
    )

    assert result["summary"]["requests_recorded"] == 1
    assert result["summary"]["model_routed_requests"] == 1
    assert result["summary"]["estimated_cost_today"] is None
    assert result["summary"]["metering_notice"] == "Requests recorded, token/cost metering unavailable for this provider."
    assert result["breakdowns"]["by_provider"] == []
    assert result["breakdowns"]["requests_by_provider"] == [{"provider": "ollama", "requests": 1}]
    assert result["breakdowns"]["requests_by_model"] == [{"model": "llama3.1", "requests": 1}]
    assert result["budget_governance"]["event_count"] == 1
    assert result["budget_governance"]["decision_counts"] == {"skipped": 1}


@pytest.mark.asyncio
async def test_finops_summary_uses_canonical_monthly_activity_over_partial_finops_events(monkeypatch):
    now = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)

    partial_finops_rows = [
        {
            "id": idx,
            "created_at": now,
            "trace_id": f"finops-trace-{idx}",
            "request_id": None,
            "tenant_id": "tenant-it",
            "user_email": "priya@it.example",
            "role": "platform-admin",
            "action": "chat.turn",
            "decision": "skipped",
            "provider": "openai",
            "model": "gpt-4.1",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "estimated_cost_usd": None,
            "budget_limit_usd": None,
            "budget_remaining_usd": None,
            "budget_limit_tokens": None,
            "budget_remaining_tokens": None,
            "budget_profile": {},
            "reason": None,
            "reached_model": True,
            "blocked_before_model": False,
            "status": "success",
            "metadata": {},
        }
        for idx in range(4)
    ]
    canonical_events = [
        {
            "created_at": now,
            "trace_id": f"canonical-trace-{idx}",
            "tenant_id": "tenant-it" if idx < 40 else "tenant-acmecp",
            "team_id": "platform",
            "role": "platform-admin",
            "user_email": "priya@it.example",
            "provider": "openai",
            "model": "gpt-4.1",
            "input_tokens": 0,
            "output_tokens": 0,
            "total_tokens": 0,
            "token_source": "unmetered",
            "request_status": "success" if idx < 56 else "failed_provider",
            "budget_decision": "skipped",
            "reached_model": True,
            "estimated_cost_usd": None,
            "source_table": "dashboard_chat_metrics" if idx >= 4 else "finops_events",
            "source_confidence": "high",
        }
        for idx in range(57)
    ]

    async def fake_run_db(fn, *args, **kwargs):
        if fn is dashboard_api.load_monthly_activity:
            return {
                "period": {"month": "2026-07", "start": now, "end": now, "days_in_month": 31},
                "events": canonical_events,
                "roles": [],
                "assignments": [],
                "source_counts": {"finops_events": 4, "dashboard_chat_metrics": 57},
            }
        return {
            "period": {"month": "2026-07", "start": now, "end": now, "days_in_month": 31},
            "chat_table": True,
            "stage_table": True,
            "finops_table": True,
            "chat_rows": [],
            "stage_rows": [],
            "event_rows": partial_finops_rows,
            "action_rows": [],
            "tenant_rows": [],
            "budget_denies": 0,
            "roles": [],
            "assignments": [],
        }

    monkeypatch.setattr(dashboard_api, "run_db", fake_run_db)

    result = await dashboard_api.finops_summary(
        month="2026-07",
        principal=AdminPrincipal(scope="platform", tenant_id=None, email="priya@it.example"),
    )

    assert result["summary"]["requests_recorded"] == 57
    assert result["summary"]["model_routed_requests"] == 57
    assert result["budget_governance"]["event_count"] == 57
    assert result["budget_governance"]["unmetered_count"] == 57
    assert result["budget_governance"]["decision_counts"] == {"skipped": 57}
    assert result["budget_governance"]["status_counts"] == {"success": 56, "failed_provider": 1}
    assert result["source_counts"] == {"finops_events": 4, "dashboard_chat_metrics": 57}
    assert result["token_breakdown"]["by_provider"] == [{"provider": "openai", "tokens": 0, "requests": 57}]
    assert result["breakdowns"]["requests_by_provider"] == [{"provider": "openai", "requests": 57}]


def test_finops_event_payload_records_budget_decision_and_model_routing():
    now = datetime(2026, 7, 10, 18, 0, tzinfo=timezone.utc)

    payload = finops_event_payload(
        {
            "trace_id": "trace-2",
            "tenant_id": "tenant-acmecp",
            "subject": "jane@acmecp.example",
            "role_id": "analyst",
            "skill_id": "assistant",
            "status": "success",
            "started_at": now,
            "ended_at": now,
            "prompt_tokens": 12,
            "completion_tokens": 18,
            "tokens_total": 30,
            "estimated_cost_usd": None,
            "cost_instrumented": False,
            "budget_refusal": False,
            "model_provider_errors": 0,
            "policy_decision_count": 3,
            "policy_allow_count": 3,
            "policy_deny_count": 0,
            "stages": [
                {"stage": "model", "duration_ms": 42, "metadata": {"provider": "ollama", "model": "llama3.1"}},
            ],
        },
        {"token_budget_per_day": 1000, "daily_request_quota": 100},
        used_tokens_today=120,
    )

    assert payload["decision"] == "allow"
    assert payload["status"] == "success"
    assert payload["provider"] == "ollama"
    assert payload["model"] == "llama3.1"
    assert payload["token_source"] == "provider"
    assert payload["reached_model"] is True
    assert payload["budget_limit_tokens"] == 1000
    assert payload["budget_remaining_tokens"] == 880
    assert payload["budget_profile"] == {"token_budget_per_day": 1000, "daily_request_quota": 100}
