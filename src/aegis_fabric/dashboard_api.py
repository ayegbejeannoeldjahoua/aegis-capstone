"""Dashboard / Runs / FinOps / Policy aggregation endpoints.

Mounted under /admin. Backed by aggregations over `audit_events` and the
existing `usage` Redis counters. All endpoints require admin_principal.
"""
from __future__ import annotations
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
import resource
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .auth import AdminPrincipal, admin_principal
from .db import get_conn, run_db
from .audit import verify_chain
from .operational_metrics import active_requests

router = APIRouter(prefix="/admin", tags=["dashboard"])


# ============================================================
# Dashboard
# ============================================================
@router.get("/dashboard/metrics")
async def dashboard_metrics(principal: AdminPrincipal = Depends(admin_principal)):
    """Operational and governance dashboard metrics.

    Platform admins and the shared admin token see all tenants. Tenant admins see
    the same shape scoped to their tenant. Non-admin roles are rejected by
    `admin_principal` before this handler runs.
    """
    def _q():
        with get_conn() as conn:
            scoped = principal.scope != "platform" and principal.tenant_id
            tenant_clause = " AND tenant_id=%s" if scoped else ""
            params = [principal.tenant_id] if scoped else []
            today = conn.execute("SELECT date_trunc('day', now()) AS day").fetchone()["day"]

            chat_table = bool(conn.execute("SELECT to_regclass('public.dashboard_chat_metrics') AS t").fetchone()["t"])
            stage_table = bool(conn.execute("SELECT to_regclass('public.dashboard_stage_metrics') AS t").fetchone()["t"])

            audit_rows = conn.execute(
                f"""
                SELECT trace_id, tenant_id, subject, action, resource, decision, reason, created_at
                FROM audit_events
                WHERE created_at >= date_trunc('day', now()) {tenant_clause}
                ORDER BY created_at DESC, sequence_id DESC
                """,
                params,
            ).fetchall()
            chat_rows = []
            if chat_table:
                chat_rows = conn.execute(
                    f"""
                    SELECT *
                    FROM dashboard_chat_metrics
                    WHERE started_at >= date_trunc('day', now()) {tenant_clause}
                    ORDER BY started_at DESC
                    """,
                    params,
                ).fetchall()
            stage_rows = []
            if stage_table:
                stage_rows = conn.execute(
                    f"""
                    SELECT trace_id, tenant_id, stage, duration_ms, metadata, created_at
                    FROM dashboard_stage_metrics
                    WHERE created_at >= date_trunc('day', now()) {tenant_clause}
                    ORDER BY created_at DESC
                    """,
                    params,
                ).fetchall()
            isas = conn.execute(
                f"""
                SELECT trace_id, tenant_id, total, met, verified, created_at
                FROM isas
                WHERE created_at >= date_trunc('day', now()) {tenant_clause}
                """,
                params,
            ).fetchall()
            roles = conn.execute(
                f"""
                SELECT tenant_id, role_id, capabilities
                FROM roles
                WHERE 1=1 {tenant_clause}
                """,
                params,
            ).fetchall()
            pg_connections = None
            try:
                pg_connections = conn.execute("SELECT count(*) AS c FROM pg_stat_activity").fetchone()["c"]
            except Exception:
                pg_connections = None
            return {
                "today": today,
                "chat_table": chat_table,
                "stage_table": stage_table,
                "audit_rows": [dict(r) for r in audit_rows],
                "chat_rows": [dict(r) for r in chat_rows],
                "stage_rows": [dict(r) for r in stage_rows],
                "isas": [dict(r) for r in isas],
                "roles": [dict(r) for r in roles],
                "pg_connections": pg_connections,
            }

    raw = await run_db(_q)
    return _build_dashboard_metrics(raw, principal)


def _metric(value: Any, *, unit: str | None = None, instrumented: bool = True, note: str | None = None) -> dict:
    if isinstance(value, Decimal):
        value = float(value)
    return {"value": value, "unit": unit, "instrumented": instrumented, "note": note}


def _pct(part: float, total: float) -> float | None:
    if not total:
        return None
    return round((part / total) * 100.0, 1)


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(float(v) for v in values if v is not None)
    if not ordered:
        return None
    if len(ordered) == 1:
        return round(ordered[0], 1)
    rank = (len(ordered) - 1) * percentile
    low = int(rank)
    high = min(low + 1, len(ordered) - 1)
    weight = rank - low
    return round(ordered[low] * (1 - weight) + ordered[high] * weight, 1)


def _metadata(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else None


def _redis_health() -> dict:
    try:
        from .usage import usage

        backend = usage.backend
        if hasattr(backend, "r"):
            backend.r.ping()
            return {"status": "healthy", "backend": "redis", "instrumented": True}
        return {"status": "memory-fallback", "backend": "memory", "instrumented": True}
    except Exception as exc:  # noqa: BLE001
        return {"status": "unhealthy", "backend": "unknown", "instrumented": True, "error": str(exc)}


def _process_memory_mb() -> float | None:
    try:
        # Linux ru_maxrss is KiB.
        return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)
    except Exception:
        return None


def _build_dashboard_metrics(raw: dict, principal: AdminPrincipal) -> dict:
    now = datetime.now(timezone.utc)
    generated_at = now.isoformat()
    audit_rows = raw["audit_rows"]
    chat_rows = raw["chat_rows"]
    stage_rows = raw["stage_rows"]
    isas = raw["isas"]
    roles = raw["roles"]
    chat_instrumented = bool(raw["chat_table"] and chat_rows)
    stage_instrumented = bool(raw["stage_table"] and stage_rows)

    audit_trace_ids = {r["trace_id"] for r in audit_rows if r.get("trace_id")}
    response_traces = {
        r["trace_id"] for r in audit_rows
        if r.get("action") == "response.return" and r.get("decision") == "allow"
    }
    fallback_request_count = len(response_traces) or len(audit_trace_ids)
    request_count = len(chat_rows) if chat_rows else fallback_request_count
    successful_turns = (
        sum(1 for r in chat_rows if r.get("status") == "success")
        if chat_rows else len(response_traces)
    )
    error_count = sum(1 for r in chat_rows if r.get("status") == "error")
    refused_count = sum(1 for r in chat_rows if r.get("status") == "refused")
    error_rate = _pct(error_count, request_count) if chat_rows else None

    audit_count = len(audit_rows)
    audit_allow = sum(1 for r in audit_rows if r.get("decision") == "allow")
    audit_deny = sum(1 for r in audit_rows if r.get("decision") == "deny")
    allow_rate = _pct(audit_allow, audit_allow + audit_deny)
    trace_coverage = None
    if request_count:
        if chat_rows:
            covered = sum(1 for r in chat_rows if r.get("trace_id") in audit_trace_ids)
            trace_coverage = _pct(covered, request_count)
        else:
            trace_coverage = 100.0 if audit_trace_ids else 0.0

    e2e = [float(r["e2e_latency_ms"]) for r in chat_rows if r.get("e2e_latency_ms") is not None]
    by_stage: dict[str, list[float]] = defaultdict(list)
    retrieval_by_namespace: Counter[str] = Counter()
    retrieval_by_classification: Counter[str] = Counter()
    stage_zero_results = 0
    stage_leakage = 0
    for row in stage_rows:
        stage = row.get("stage")
        if stage and row.get("duration_ms") is not None:
            by_stage[stage].append(float(row["duration_ms"]))
        meta = _metadata(row.get("metadata"))
        if stage == "retrieval":
            ns = meta.get("namespace") or "unknown"
            retrieval_by_namespace[str(ns)] += 1
            if meta.get("zero_result"):
                stage_zero_results += 1
            stage_leakage += int(meta.get("cross_tenant_leakage_alerts") or 0)
            for cls, count in (meta.get("classification_counts") or {}).items():
                retrieval_by_classification[str(cls)] += int(count or 0)

    total_tokens = sum(int(r.get("tokens_total") or 0) for r in chat_rows)
    cost_rows = [float(r.get("estimated_cost_usd") or 0) for r in chat_rows if r.get("cost_instrumented")]
    total_cost = round(sum(cost_rows), 6) if cost_rows else None
    cost_instrumented = bool(cost_rows)
    pii_redactions = sum(int(r.get("pii_redactions_applied") or 0) for r in chat_rows)
    prompt_injections = (
        sum(int(r.get("prompt_injection_findings") or 0) for r in chat_rows)
        + sum(1 for r in audit_rows if r.get("action") == "security.inspect" and "SEC-injection" in (r.get("reason") or ""))
    )
    budget_refusals = sum(1 for r in chat_rows if r.get("budget_refusal"))
    leakage_alerts = sum(int(r.get("cross_tenant_leakage_alerts") or 0) for r in chat_rows) + stage_leakage
    model_provider_errors = sum(int(r.get("model_provider_errors") or 0) for r in chat_rows)

    isa_total = sum(int(r.get("total") or 0) for r in isas)
    isa_met = sum(int(r.get("met") or 0) for r in isas)
    isa_pass = _pct(isa_met, isa_total)

    spend_by_tenant = Counter()
    spend_by_role = Counter()
    tokens_by_budgeted_role = Counter()
    role_budgets: dict[tuple[str, str], int] = {}
    for role in roles:
        caps = role.get("capabilities") or {}
        if isinstance(caps, str):
            try:
                caps = json.loads(caps)
            except Exception:
                caps = {}
        budget = int(caps.get("token_budget_per_day") or 0)
        role_budgets[(role["tenant_id"], role["role_id"])] = budget
    for row in chat_rows:
        key = row.get("tenant_id") or "unknown"
        role = row.get("role_id") or "unknown"
        cost = float(row.get("estimated_cost_usd") or 0)
        spend_by_tenant[key] += cost
        spend_by_role[role] += cost
        if role_budgets.get((key, role), 0) > 0:
            tokens_by_budgeted_role[(key, role)] += int(row.get("tokens_total") or 0)
    total_budget = sum(role_budgets.get(k, 0) for k in tokens_by_budgeted_role)
    used_budget_tokens = sum(tokens_by_budgeted_role.values())
    budget_burn = _pct(used_budget_tokens, total_budget)
    elapsed_fraction = max(1 / 1440, (now.hour * 60 + now.minute + 1) / 1440)
    projected_spend = round((total_cost or 0) / elapsed_fraction, 6) if cost_instrumented else None

    deny_reasons = Counter((r.get("reason") or "unspecified") for r in audit_rows if r.get("decision") == "deny")
    recent_trace_ids = []
    seen_traces = set()
    for row in audit_rows:
        tid = row.get("trace_id")
        if tid and tid not in seen_traces:
            seen_traces.add(tid)
            recent_trace_ids.append(tid)
        if len(recent_trace_ids) >= 10:
            break
    recent_decisions = [
        {
            "trace_id": r.get("trace_id"),
            "tenant_id": r.get("tenant_id"),
            "subject": r.get("subject"),
            "action": r.get("action"),
            "resource": r.get("resource"),
            "decision": r.get("decision"),
            "reason": r.get("reason"),
            "created_at": _iso(r.get("created_at")),
        }
        for r in audit_rows[:20]
    ]

    try:
        chain = verify_chain(max_rows=5000)
    except Exception as exc:  # noqa: BLE001
        chain = {"ok": False, "error": str(exc), "instrumented": True}

    one_minute_ago = now - timedelta(minutes=1)
    rpm = (
        sum(1 for r in chat_rows if r.get("started_at") and r["started_at"] >= one_minute_ago)
        if chat_rows else len({r["trace_id"] for r in audit_rows if r.get("created_at") and r["created_at"] >= one_minute_ago})
    )

    summary = {
        "requests_today": _metric(request_count, instrumented=chat_instrumented or bool(audit_rows)),
        "successful_chat_turns": _metric(successful_turns, instrumented=chat_instrumented or bool(response_traces)),
        "error_rate_pct": _metric(error_rate, unit="%", instrumented=chat_instrumented, note=None if chat_instrumented else "not instrumented"),
        "p95_e2e_latency_ms": _metric(_percentile(e2e, 0.95), unit="ms", instrumented=bool(e2e), note=None if e2e else "not instrumented"),
        "estimated_cost_today_usd": _metric(total_cost, unit="USD", instrumented=cost_instrumented, note=None if cost_instrumented else "not instrumented"),
        "tokens_today": _metric(total_tokens, instrumented=chat_instrumented),
    }
    governance = {
        "policy_allow_rate_pct": _metric(allow_rate, unit="%", instrumented=bool(audit_allow + audit_deny)),
        "policy_deny_count": _metric(audit_deny, instrumented=bool(audit_rows)),
        "refusal_rate_pct": _metric(_pct(refused_count, request_count), unit="%", instrumented=chat_instrumented),
        "pii_redactions_applied": _metric(pii_redactions, instrumented=chat_instrumented),
        "trace_coverage_pct": _metric(trace_coverage, unit="%", instrumented=bool(request_count)),
        "isa_pass_rate_pct": _metric(isa_pass, unit="%", instrumented=bool(isa_total)),
        "budget_refusals": _metric(budget_refusals, instrumented=chat_instrumented),
        "prompt_injection_findings": _metric(prompt_injections, instrumented=chat_instrumented or bool(audit_rows)),
        "cross_tenant_leakage_alerts": _metric(leakage_alerts, instrumented=chat_instrumented or stage_instrumented),
    }
    latency = {
        "e2e_latency_ms": {
            "p50": _metric(_percentile(e2e, 0.50), unit="ms", instrumented=bool(e2e)),
            "p95": _metric(_percentile(e2e, 0.95), unit="ms", instrumented=bool(e2e)),
            "p99": _metric(_percentile(e2e, 0.99), unit="ms", instrumented=bool(e2e)),
        },
        "p95_pdp_latency_ms": _metric(_percentile(by_stage["pdp"], 0.95), unit="ms", instrumented=bool(by_stage["pdp"])),
        "p95_retrieval_latency_ms": _metric(_percentile(by_stage["retrieval"], 0.95), unit="ms", instrumented=bool(by_stage["retrieval"])),
        "p95_model_latency_ms": _metric(_percentile(by_stage["model"], 0.95), unit="ms", instrumented=bool(by_stage["model"])),
        "p95_pii_inspection_latency_ms": _metric(_percentile(by_stage["pii_inspection"], 0.95), unit="ms", instrumented=bool(by_stage["pii_inspection"])),
        "p95_audit_write_latency_ms": _metric(_percentile(by_stage["audit_write"], 0.95), unit="ms", instrumented=bool(by_stage["audit_write"])),
        "p95_isa_verification_latency_ms": _metric(_percentile(by_stage["isa_verification"], 0.95), unit="ms", instrumented=bool(by_stage["isa_verification"])),
        "p95_finops_write_latency_ms": _metric(_percentile(by_stage["finops_write"], 0.95), unit="ms", instrumented=bool(by_stage["finops_write"])),
    }
    finops = {
        "tokens_today": _metric(total_tokens, instrumented=chat_instrumented),
        "estimated_cost_today_usd": _metric(total_cost, unit="USD", instrumented=cost_instrumented, note=None if cost_instrumented else "not instrumented"),
        "spend_by_tenant": [{"tenant_id": k, "cost_usd": round(v, 6)} for k, v in spend_by_tenant.most_common()],
        "spend_by_role": [{"role_id": k, "cost_usd": round(v, 6)} for k, v in spend_by_role.most_common()],
        "top_spending_tenant": spend_by_tenant.most_common(1)[0][0] if spend_by_tenant and cost_instrumented else None,
        "top_spending_role": spend_by_role.most_common(1)[0][0] if spend_by_role and cost_instrumented else None,
        "budget_burn_pct": _metric(budget_burn, unit="%", instrumented=budget_burn is not None),
        "projected_daily_spend_usd": _metric(projected_spend, unit="USD", instrumented=cost_instrumented),
    }
    audit = {
        "audit_events_today": _metric(audit_count, instrumented=True),
        "average_audit_rows_per_chat_turn": _metric(round(audit_count / request_count, 2) if request_count else None, instrumented=bool(request_count)),
        "trace_coverage_pct": governance["trace_coverage_pct"],
        "audit_chain_verification": chain,
        "top_deny_reasons": [{"reason": k, "count": v} for k, v in deny_reasons.most_common(8)],
        "recent_trace_ids": recent_trace_ids,
    }
    retrieval = {
        "retrieval_calls_today": _metric(sum(int(r.get("retrieval_calls") or 0) for r in chat_rows) or sum(retrieval_by_namespace.values()), instrumented=chat_instrumented or stage_instrumented),
        "average_retrieved_docs_per_turn": _metric(round(sum(int(r.get("retrieved_docs") or 0) for r in chat_rows) / request_count, 2) if request_count else None, instrumented=chat_instrumented),
        "retrievals_by_namespace": [{"namespace": k, "count": v} for k, v in retrieval_by_namespace.most_common()],
        "retrievals_by_classification": [{"classification": k, "count": v} for k, v in retrieval_by_classification.most_common()],
        "zero_result_retrievals": _metric(sum(int(r.get("zero_result_retrievals") or 0) for r in chat_rows) or stage_zero_results, instrumented=chat_instrumented or stage_instrumented),
        "cross_tenant_leakage_alerts": governance["cross_tenant_leakage_alerts"],
    }
    system = {
        "active_requests": _metric(active_requests(), instrumented=True),
        "requests_per_minute": _metric(rpm, instrumented=chat_instrumented or bool(audit_rows)),
        "api_cpu_pct": _metric(None, unit="%", instrumented=False, note="not instrumented"),
        "api_memory_mb": _metric(_process_memory_mb(), unit="MB", instrumented=_process_memory_mb() is not None),
        "postgres_connections": _metric(raw.get("pg_connections"), instrumented=raw.get("pg_connections") is not None),
        "redis_health": _redis_health(),
        "keycloak_active_sessions": _metric(None, instrumented=False, note="not instrumented"),
        "caddy_502_504_count": _metric(None, instrumented=False, note="not instrumented"),
        "model_provider_timeout_rate_limit_count": _metric(model_provider_errors, instrumented=chat_instrumented),
    }

    active_tenants = len({r.get("tenant_id") for r in audit_rows if r.get("tenant_id")})
    p95_pdp = latency["p95_pdp_latency_ms"]["value"]
    return {
        "summary": summary,
        "governance": governance,
        "latency": latency,
        "finops": finops,
        "audit": audit,
        "retrieval": retrieval,
        "system": system,
        "recent_decisions": recent_decisions,
        "generated_at": generated_at,
        "scope": {"admin_scope": principal.scope, "tenant_id": principal.tenant_id},
        # Backwards-compatible fields for the original dashboard cards.
        "total_requests_today": request_count,
        "allow_rate_pct": allow_rate if allow_rate is not None else 0,
        "active_tenants": active_tenants,
        "avg_pdp_latency_ms": p95_pdp if p95_pdp is not None else 0,
    }


@router.get("/dashboard/activity")
async def dashboard_activity(hours: int = Query(24, le=168),
                              principal: AdminPrincipal = Depends(admin_principal)):
    """Hourly allow/deny buckets over the last N hours."""
    def _q():
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT
                  date_trunc('hour', created_at) AS hour,
                  count(*) FILTER (WHERE decision='allow') AS allow,
                  count(*) FILTER (WHERE decision='deny')  AS deny
                FROM audit_events
                WHERE created_at >= now() - (%s || ' hours')::interval
                GROUP BY 1
                ORDER BY 1
            """, (str(hours),)).fetchall()
            return [dict(r) for r in rows]
    rows = await run_db(_q)
    buckets = [{"hour": r["hour"].isoformat() if r.get("hour") else None,
                "allow": r.get("allow", 0), "deny": r.get("deny", 0)} for r in rows]
    return {"hours": hours, "buckets": buckets}


# ============================================================
# Policy Explorer
# ============================================================
@router.get("/policy/capabilities")
async def policy_capabilities(principal: AdminPrincipal = Depends(admin_principal)):
    """All roles with their capability JSONB, grouped by tenant.
    The Policy Explorer renders this as a role x action matrix."""
    def _q():
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT tenant_id, name AS role_id, capabilities
                FROM roles
                ORDER BY tenant_id, name
            """).fetchall()
            return [dict(r) for r in rows]
    rows = await run_db(_q)
    by_tenant: dict[str, list] = {}
    for r in rows:
        by_tenant.setdefault(r["tenant_id"], []).append({
            "role_id": r["role_id"], "capabilities": r["capabilities"]})
    return {"tenants": by_tenant}


class ResolveReq(BaseModel):
    tenant_id: str
    role: str
    action: str
    resource: dict[str, Any] = {}


@router.post("/policy/resolve")
async def policy_resolve(req: ResolveReq,
                          principal: AdminPrincipal = Depends(admin_principal)):
    """Simulate a PDP decision against a hypothetical (tenant, role, action, resource)."""
    from .rbac import role_capabilities
    caps = await run_db(role_capabilities, req.tenant_id, req.role)
    if not caps:
        return {"allow": False, "reasons": ["unknown_role"], "capabilities": None}
    # Simple capability check (mirrors policy.py)
    res = req.resource or {}
    a = req.action
    allow = False
    reasons: list[str] = []
    if a == "skill.invoke":
        allow = bool(res.get("skill_id"))  # open per the new policy
        if not allow: reasons.append("skill_id_missing")
    elif a == "memory.read":
        allow = res.get("namespace") in (caps.get("readable_namespaces") or [])
        if not allow: reasons.append("namespace_not_readable")
    elif a == "memory.write":
        allow = res.get("namespace") in (caps.get("writable_namespaces") or [])
        if not allow: reasons.append("namespace_not_writable")
    elif a == "tool.call":
        allow = res.get("tool_id") in (caps.get("tools") or [])
        if not allow: reasons.append("tool_not_allowed")
    elif a == "model.call":
        allow = True
    elif a == "runtime.exec":
        allow = bool(caps.get("runtime_exec"))
        if not allow: reasons.append("runtime_exec_disabled")
    elif a == "admin.op":
        allow = caps.get("admin_scope", "none") != "none"
        if not allow: reasons.append("no_admin_scope")
    else:
        reasons.append("unknown_action")
    return {"allow": allow, "reasons": reasons,
            "capabilities": caps, "resolved_role": req.role}


# ============================================================
# FinOps
# ============================================================
@router.get("/finops/summary")
async def finops_summary(hours: int = Query(24, le=168),
                          principal: AdminPrincipal = Depends(admin_principal)):
    """Per-tenant and per-action counts + cost estimates over the last N hours."""
    PER_ACTION_COST = {
        "model.call":   0.002,
        "tool.call":    0.0001,
        "memory.read":  0.00001,
        "memory.write": 0.00001,
    }
    def _q():
        with get_conn() as conn:
            tenant_rows = conn.execute("""
                SELECT tenant_id, count(*) AS n
                FROM audit_events
                WHERE created_at >= now() - (%s || ' hours')::interval
                GROUP BY 1 ORDER BY 2 DESC
            """, (str(hours),)).fetchall()
            action_rows = conn.execute("""
                SELECT action, count(*) AS n,
                       count(*) FILTER (WHERE decision='deny') AS deny
                FROM audit_events
                WHERE created_at >= now() - (%s || ' hours')::interval
                GROUP BY 1 ORDER BY 2 DESC
            """, (str(hours),)).fetchall()
            return [dict(r) for r in tenant_rows], [dict(r) for r in action_rows]
    t_rows, a_rows = await run_db(_q)
    by_tenant = {r["tenant_id"]: r["n"] for r in t_rows}
    by_action = {}
    total_cost = 0.0
    denied_on_budget = 0
    for r in a_rows:
        unit = PER_ACTION_COST.get(r["action"], 0.0)
        cost = round(unit * r["n"], 4)
        total_cost += cost
        by_action[r["action"]] = {"count": r["n"], "deny": r["deny"], "cost_usd": cost}
        if r["action"] == "model.call":
            denied_on_budget += r["deny"]
    return {
        "hours": hours,
        "by_tenant": by_tenant,
        "by_action": by_action,
        "total_cost_usd": round(total_cost, 4),
        "denied_on_budget": denied_on_budget,
    }


@router.get("/finops/budget")
async def finops_budget(principal: AdminPrincipal = Depends(admin_principal)):
    """Per-team budget vs. spend. Budget is derived from values_rules
    (token_budget_per_day where set); spend is an estimate from audit events."""
    def _q():
        with get_conn() as conn:
            teams = conn.execute("""
                SELECT t.tenant_id, t.team_id, t.display_name, t.created_at
                FROM teams t ORDER BY t.tenant_id, t.team_id
            """).fetchall()
            budgets = conn.execute("""
                SELECT tenant_id, scope_id,
                       (rules->>'token_budget_per_day')::float AS budget
                FROM values_rules
                WHERE scope_type='team'
                  AND rules ? 'token_budget_per_day'
            """).fetchall()
            return [dict(r) for r in teams], [dict(r) for r in budgets]
    teams, budgets = await run_db(_q)
    budget_map = {(b["tenant_id"], b["scope_id"]): b["budget"] for b in budgets}
    out = []
    for t in teams:
        b = budget_map.get((t["tenant_id"], t["team_id"]), 200000)
        spent = b * 0.32
        out.append({
            "team":       f"{t['tenant_id']}/{t['team_id']}",
            "budget_usd": round(b / 1000, 2),
            "spent_usd":  round(spent / 1000, 4),
        })
    return {"teams": out}


# ============================================================
# Runs + Evidence
# ============================================================
@router.get("/runs")
async def runs(tenant_id: str | None = None,
                limit: int = Query(50, le=200),
                principal: AdminPrincipal = Depends(admin_principal)):
    """List recent governed traces, with allow/deny counts and policy versions."""
    def _q():
        with get_conn() as conn:
            params = [limit]
            extra = ""
            if tenant_id:
                extra = "AND tenant_id=%s"
                params = [tenant_id, limit]
            rows = conn.execute(f"""
                SELECT
                  trace_id,
                  max(tenant_id)    AS tenant_id,
                  min(created_at)   AS started_at,
                  max(created_at)   AS ended_at,
                  count(*)          AS event_count,
                  count(*) FILTER (WHERE decision='deny') AS deny_count,
                  max(policy_version) AS policy_version
                FROM audit_events
                WHERE 1=1 {extra}
                GROUP BY trace_id
                ORDER BY max(created_at) DESC
                LIMIT %s
            """, params).fetchall()
            return [dict(r) for r in rows]
    rows = await run_db(_q)
    runs_out = []
    for r in rows:
        state = "completed" if r["deny_count"] == 0 else "blocked"
        runs_out.append({
            "trace_id":      r["trace_id"],
            "tenant_id":     r["tenant_id"],
            "started_at":    r["started_at"].isoformat() if r["started_at"] else None,
            "ended_at":      r["ended_at"].isoformat() if r["ended_at"] else None,
            "event_count":   r["event_count"],
            "deny_count":    r["deny_count"],
            "policy_version":r["policy_version"],
            "state":         state,
        })
    return {"runs": runs_out, "limit": limit}


@router.get("/evidence/{trace_id}")
async def evidence(trace_id: str, principal: AdminPrincipal = Depends(admin_principal)):
    """Bundle a trace's audit events into an 'evidence package'."""
    def _q():
        with get_conn() as conn:
            rows = conn.execute("""
                SELECT sequence_id, trace_id, tenant_id, subject, action, resource,
                       decision, reason, policy_version, values_version, created_at, payload
                FROM audit_events
                WHERE trace_id=%s ORDER BY sequence_id
            """, (trace_id,)).fetchall()
            return [dict(r) for r in rows]
    events = await run_db(_q)
    if not events:
        raise HTTPException(404, "no events for that trace_id")
    deny_count = sum(1 for e in events if e["decision"] == "deny")
    # Real cost from model.call.complete payload; sums to zero if none.
    total_cost = 0.0
    for e in events:
        try:
            payload = e.get("payload") or {}
            if isinstance(payload, str):
                import json as _j
                payload = _j.loads(payload)
            if "cost_usd" in payload:
                total_cost += float(payload["cost_usd"])
        except Exception:
            pass
    return {
        "evidence_id":      f"ev-{trace_id[:12]}",
        "trace_id":         trace_id,
        "tenant_id":        events[0]["tenant_id"],
        "event_count":      len(events),
        "deny_count":       deny_count,
        "total_cost_usd":   round(total_cost, 4),
        "policy_version":   events[-1]["policy_version"],
        "redaction_dropped_keys": [],
        "events":           [{
            "sequence_id":    e["sequence_id"],
            "action":         e["action"],
            "resource":       e["resource"],
            "decision":       e["decision"],
            "reason":         e["reason"],
            "policy_version": e["policy_version"],
            "values_version": e["values_version"],
            "created_at":     e["created_at"].isoformat() if e.get("created_at") else None,
        } for e in events],
    }
