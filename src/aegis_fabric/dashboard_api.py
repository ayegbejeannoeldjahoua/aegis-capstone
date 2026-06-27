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


def _number(value: Any) -> float | int | None:
    if isinstance(value, Decimal):
        return float(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, (int, float)):
        return value
    try:
        return float(value)
    except Exception:
        return None


def _json_dict(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _gap(gaps: list[dict[str, str]], metric: str, reason: str) -> None:
    gaps.append({"metric": metric, "reason": reason})


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
    chat_table_available = bool(raw["chat_table"])
    stage_table_available = bool(raw["stage_table"])
    gaps: list[dict[str, str]] = []

    audit_trace_ids = {r["trace_id"] for r in audit_rows if r.get("trace_id")}
    response_traces = {
        r["trace_id"] for r in audit_rows
        if r.get("action") == "response.return" and r.get("decision") == "allow"
    }
    fallback_request_count = len(response_traces) or len(audit_trace_ids)
    request_count = len(chat_rows) if chat_table_available else fallback_request_count
    successful_turns = (
        sum(1 for r in chat_rows if r.get("status") == "success")
        if chat_table_available else len(response_traces)
    )
    error_count = sum(1 for r in chat_rows if r.get("status") == "error")
    refused_count = sum(1 for r in chat_rows if r.get("status") == "refused")
    error_rate = _pct(error_count, request_count) if chat_table_available and request_count else None

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
    stage_docs_returned = 0
    stage_leakage = 0
    pdp_latency_by_trace_action: dict[tuple[str, str], float] = {}
    for row in stage_rows:
        stage = row.get("stage")
        if stage and row.get("duration_ms") is not None:
            duration = float(row["duration_ms"])
            by_stage[stage].append(duration)
        meta = _metadata(row.get("metadata"))
        if stage == "pdp":
            action = str(meta.get("action") or "")
            trace_id = row.get("trace_id")
            if trace_id and action:
                pdp_latency_by_trace_action[(trace_id, action)] = float(row.get("duration_ms") or 0)
        if stage == "retrieval":
            ns = meta.get("namespace") or "unknown"
            retrieval_by_namespace[str(ns)] += 1
            docs = int(meta.get("docs") or 0)
            stage_docs_returned += docs
            if meta.get("zero_result"):
                stage_zero_results += 1
            stage_leakage += int(meta.get("cross_tenant_leakage_alerts") or 0)
            for cls, count in (meta.get("classification_counts") or {}).items():
                retrieval_by_classification[str(cls)] += int(count or 0)

    pii_redactions = sum(int(r.get("pii_redactions_applied") or 0) for r in chat_rows)
    prompt_injections = (
        sum(int(r.get("prompt_injection_findings") or 0) for r in chat_rows)
        + sum(1 for r in audit_rows if r.get("action") == "security.inspect" and "SEC-injection" in (r.get("reason") or ""))
    )
    leakage_alerts = sum(int(r.get("cross_tenant_leakage_alerts") or 0) for r in chat_rows) + stage_leakage
    model_provider_errors = sum(int(r.get("model_provider_errors") or 0) for r in chat_rows)

    isa_total = sum(int(r.get("total") or 0) for r in isas)
    isa_met = sum(int(r.get("met") or 0) for r in isas)
    isa_pass = _pct(isa_met, isa_total)

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
            "timestamp": _iso(r.get("created_at")),
            "trace_id": r.get("trace_id"),
            "tenant_id": r.get("tenant_id"),
            "subject": r.get("subject"),
            "action": r.get("action"),
            "resource": r.get("resource"),
            "decision": r.get("decision"),
            "reason": r.get("reason"),
            "latency_ms": pdp_latency_by_trace_action.get((r.get("trace_id"), r.get("action"))),
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

    active_tenants = len(
        {
            r.get("tenant_id")
            for r in [*audit_rows, *chat_rows]
            if r.get("tenant_id")
        }
    )
    leakage_computable = chat_table_available or stage_table_available
    access_posture = "isolated" if leakage_computable and leakage_alerts == 0 else ("alert" if leakage_alerts else "unknown")
    if not chat_table_available:
        _gap(gaps, "request_lifecycle", "dashboard_chat_metrics is not available")
        _gap(gaps, "end_to_end_latency", "request lifecycle timing table is not available")
        _gap(gaps, "error_rate", "request status counters are not available")
    elif not e2e:
        _gap(gaps, "end_to_end_latency", "no chat turns with request lifecycle timings recorded today")
    if not stage_table_available:
        _gap(gaps, "stage_latency", "dashboard_stage_metrics is not available")
        _gap(gaps, "retrieval_dimensions", "retrieval stage telemetry is not available")
        _gap(gaps, "cross_tenant_leakage_alerts", "retrieved document tenant IDs are not recorded")
    elif not stage_rows:
        _gap(gaps, "stage_latency", "no stage timings recorded today")
    if not isa_total:
        _gap(gaps, "isa_pass_rate", "no ISA verification rows recorded today")
    if raw.get("pg_connections") is None:
        _gap(gaps, "postgres_connections", "pg_stat_activity is not available to this database user")
    _gap(gaps, "api_cpu_pct", "process CPU sampling is not connected")
    _gap(gaps, "keycloak_active_sessions", "Keycloak session telemetry is not connected")
    _gap(gaps, "caddy_502_504_count", "Caddy log/error counters are not connected")

    summary = {
        "requests_today": request_count,
        "successful_chat_turns": successful_turns,
        "error_rate": error_rate,
        "p95_end_to_end_latency_ms": _percentile(e2e, 0.95),
        "active_tenants": active_tenants,
        "access_posture": access_posture,
    }
    governance = {
        "policy_allow_rate": allow_rate,
        "policy_deny_count": audit_deny,
        "trace_coverage": trace_coverage,
        "isa_pass_rate": isa_pass,
        "prompt_injection_findings": prompt_injections,
        "cross_tenant_leakage_alerts": leakage_alerts if leakage_computable else None,
        "access_posture": access_posture,
        "refusal_rate": _pct(refused_count, request_count) if chat_table_available and request_count else None,
        "pii_redactions_applied": pii_redactions if chat_table_available else None,
    }
    latency = {
        "end_to_end": {
            "p50_ms": _percentile(e2e, 0.50),
            "p95_ms": _percentile(e2e, 0.95),
            "p99_ms": _percentile(e2e, 0.99),
        },
        "pdp": {"p95_ms": _percentile(by_stage["pdp"], 0.95)},
        "retrieval": {"p95_ms": _percentile(by_stage["retrieval"], 0.95)},
        "model": {"p95_ms": _percentile(by_stage["model"], 0.95)},
        "audit_write": {"p95_ms": _percentile(by_stage["audit_write"], 0.95)},
        "isa": {"p95_ms": _percentile(by_stage["isa_verification"], 0.95)},
    }
    audit = {
        "events_today": audit_count,
        "avg_rows_per_turn": round(audit_count / request_count, 2) if request_count else None,
        "trace_coverage": trace_coverage,
        "chain_verification": chain,
        "top_deny_reasons": [{"reason": k, "count": v} for k, v in deny_reasons.most_common(8)],
        "recent_trace_ids": recent_trace_ids,
    }
    retrieval_calls = sum(int(r.get("retrieval_calls") or 0) for r in chat_rows)
    documents_returned = sum(int(r.get("retrieved_docs") or 0) for r in chat_rows)
    zero_result_count = sum(int(r.get("zero_result_retrievals") or 0) for r in chat_rows)
    if not chat_table_available:
        retrieval_calls = sum(retrieval_by_namespace.values())
        documents_returned = stage_docs_returned
        zero_result_count = stage_zero_results
    retrieval = {
        "calls_today": retrieval_calls,
        "documents_returned_today": documents_returned,
        "avg_docs_per_turn": round(documents_returned / request_count, 2) if request_count else None,
        "by_namespace": [{"namespace": k, "count": v} for k, v in retrieval_by_namespace.most_common()],
        "by_classification": [{"classification": k, "count": v} for k, v in retrieval_by_classification.most_common()],
        "zero_result_count": zero_result_count,
        "cross_tenant_leakage_alerts": governance["cross_tenant_leakage_alerts"],
    }
    redis = _redis_health()
    system = {
        "active_requests": active_requests(),
        "requests_per_minute": rpm,
        "api_memory_mb": _process_memory_mb(),
        "postgres_connections": raw.get("pg_connections"),
        "model_provider_timeout_rate_limit_count": model_provider_errors if chat_table_available else None,
        "health": {
            "api": {"status": "healthy"},
            "postgres": {"status": "healthy" if raw.get("pg_connections") is not None else "unknown"},
            "redis": redis,
            "model_provider": {"status": "degraded" if model_provider_errors else "healthy", "errors": model_provider_errors},
        },
    }

    return {
        "summary": summary,
        "governance": governance,
        "latency": latency,
        "audit": audit,
        "retrieval": retrieval,
        "system": system,
        "recent_decisions": recent_decisions,
        "instrumentation_gaps": gaps,
        "generated_at": generated_at,
        "scope": {"admin_scope": principal.scope, "tenant_id": principal.tenant_id},
        # Backwards-compatible fields for the original dashboard cards.
        "total_requests_today": request_count,
        "allow_rate_pct": allow_rate if allow_rate is not None else 0,
        "active_tenants": active_tenants,
        "avg_pdp_latency_ms": latency["pdp"]["p95_ms"] if latency["pdp"]["p95_ms"] is not None else 0,
    }


@router.get("/dashboard/activity")
async def dashboard_activity(hours: int = Query(24, le=168),
                              principal: AdminPrincipal = Depends(admin_principal)):
    """Hourly allow/deny buckets over the last N hours."""
    def _q():
        with get_conn() as conn:
            scoped = principal.scope != "platform" and principal.tenant_id
            tenant_clause = " AND tenant_id=%s" if scoped else ""
            params = [str(hours), principal.tenant_id] if scoped else [str(hours)]
            rows = conn.execute(f"""
                SELECT
                  date_trunc('hour', created_at) AS hour,
                  count(*) FILTER (WHERE decision='allow') AS allow,
                  count(*) FILTER (WHERE decision='deny')  AS deny
                FROM audit_events
                WHERE created_at >= now() - (%s || ' hours')::interval {tenant_clause}
                GROUP BY 1
                ORDER BY 1
            """, params).fetchall()
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
    """Cost, token, and budget governance over the last N hours.

    Costs are returned only when a real cost value was recorded by the model
    usage path. Audit action counts are preserved for activity context, but are
    no longer multiplied by synthetic per-action prices.
    """
    def _q():
        with get_conn() as conn:
            scoped = principal.scope != "platform" and principal.tenant_id
            tenant_clause = " AND tenant_id=%s" if scoped else ""
            params = [str(hours), principal.tenant_id] if scoped else [str(hours)]
            chat_table = bool(conn.execute("SELECT to_regclass('public.dashboard_chat_metrics') AS t").fetchone()["t"])
            stage_table = bool(conn.execute("SELECT to_regclass('public.dashboard_stage_metrics') AS t").fetchone()["t"])
            chat_rows = []
            if chat_table:
                chat_rows = conn.execute(
                    f"""
                    SELECT *
                    FROM dashboard_chat_metrics
                    WHERE started_at >= now() - (%s || ' hours')::interval {tenant_clause}
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
                    WHERE created_at >= now() - (%s || ' hours')::interval {tenant_clause}
                    ORDER BY created_at DESC
                    """,
                    params,
                ).fetchall()
            action_rows = conn.execute(f"""
                SELECT action, count(*) AS n,
                       count(*) FILTER (WHERE decision='deny') AS deny
                FROM audit_events
                WHERE created_at >= now() - (%s || ' hours')::interval {tenant_clause}
                GROUP BY 1 ORDER BY 2 DESC
            """, params).fetchall()
            tenant_rows = conn.execute(f"""
                SELECT tenant_id, count(*) AS n
                FROM audit_events
                WHERE created_at >= now() - (%s || ' hours')::interval {tenant_clause}
                GROUP BY 1 ORDER BY 2 DESC
            """, params).fetchall()
            budget_denies = conn.execute(f"""
                SELECT count(*) AS n
                FROM audit_events
                WHERE created_at >= now() - (%s || ' hours')::interval {tenant_clause}
                  AND decision='deny'
                  AND (reason ILIKE '%%budget%%' OR reason ILIKE '%%quota%%')
            """, params).fetchone()["n"]
            roles = conn.execute(
                f"""
                SELECT tenant_id, role_id, capabilities
                FROM roles
                WHERE 1=1 {tenant_clause}
                ORDER BY tenant_id, role_id
                """,
                [principal.tenant_id] if scoped else [],
            ).fetchall()
            return {
                "chat_table": chat_table,
                "stage_table": stage_table,
                "chat_rows": [dict(r) for r in chat_rows],
                "stage_rows": [dict(r) for r in stage_rows],
                "action_rows": [dict(r) for r in action_rows],
                "tenant_rows": [dict(r) for r in tenant_rows],
                "budget_denies": int(budget_denies or 0),
                "roles": [dict(r) for r in roles],
            }

    raw = await run_db(_q)
    chat_rows = raw["chat_rows"]
    stage_rows = raw["stage_rows"]
    chat_table_available = bool(raw["chat_table"])
    stage_table_available = bool(raw["stage_table"])
    gaps: list[dict[str, str]] = []

    total_tokens = sum(int(r.get("tokens_total") or 0) for r in chat_rows) if chat_table_available else None
    input_tokens = sum(int(r.get("prompt_tokens") or 0) for r in chat_rows) if chat_table_available else None
    output_tokens = sum(int(r.get("completion_tokens") or 0) for r in chat_rows) if chat_table_available else None
    request_count = len(chat_rows) if chat_table_available else 0
    successful_turns = sum(1 for r in chat_rows if r.get("status") == "success") if chat_table_available else 0
    cost_rows = [
        float(r.get("estimated_cost_usd") or 0)
        for r in chat_rows
        if r.get("cost_instrumented") and r.get("estimated_cost_usd") is not None
    ]
    total_cost = round(sum(cost_rows), 6) if cost_rows else None
    cost_available = bool(cost_rows)
    budget_refusals = (
        sum(1 for r in chat_rows if r.get("budget_refusal"))
        if chat_table_available else raw["budget_denies"]
    )
    elapsed_fraction = max(1 / 1440, (datetime.now(timezone.utc).hour * 60 + datetime.now(timezone.utc).minute + 1) / 1440)
    projected_daily_spend = round((total_cost or 0) / elapsed_fraction, 6) if cost_available else None
    avg_cost_per_turn = round(total_cost / successful_turns, 6) if cost_available and successful_turns else None

    role_budgets: dict[tuple[str, str], int] = {}
    for role in raw["roles"]:
        caps = _json_dict(role.get("capabilities"))
        budget = int(caps.get("token_budget_per_day") or 0)
        role_budgets[(role["tenant_id"], role["role_id"])] = budget

    tokens_by_tenant: Counter[str] = Counter()
    tokens_by_role: Counter[str] = Counter()
    tokens_by_role_key: Counter[tuple[str, str]] = Counter()
    tokens_by_hour: Counter[str] = Counter()
    spend_by_tenant: Counter[str] = Counter()
    spend_by_role: Counter[str] = Counter()
    spend_by_hour: Counter[str] = Counter()
    model_by_trace: dict[str, dict[str, Any]] = {}
    tokens_by_model: Counter[str] = Counter()
    tokens_by_provider: Counter[str] = Counter()
    for row in stage_rows:
        if row.get("stage") != "model":
            continue
        meta = _metadata(row.get("metadata"))
        model = str(meta.get("model") or "unknown")
        provider = str(meta.get("provider") or "unknown")
        tokens = int(meta.get("tokens_total") or 0)
        trace_id = row.get("trace_id")
        if trace_id and trace_id not in model_by_trace:
            model_by_trace[trace_id] = {"model": model, "provider": provider, "latency_ms": row.get("duration_ms")}
        tokens_by_model[model] += tokens
        tokens_by_provider[provider] += tokens

    spend_by_model: Counter[str] = Counter()
    spend_by_provider: Counter[str] = Counter()
    for row in chat_rows:
        tenant = row.get("tenant_id") or "unknown"
        role = row.get("role_id") or "unknown"
        tokens = int(row.get("tokens_total") or 0)
        tokens_by_tenant[tenant] += tokens
        tokens_by_role[role] += tokens
        tokens_by_role_key[(tenant, role)] += tokens
        started = row.get("started_at")
        hour = started.replace(minute=0, second=0, microsecond=0).isoformat() if hasattr(started, "replace") else "unknown"
        tokens_by_hour[hour] += tokens
        if row.get("cost_instrumented") and row.get("estimated_cost_usd") is not None:
            cost = float(row.get("estimated_cost_usd") or 0)
            spend_by_tenant[tenant] += cost
            spend_by_role[role] += cost
            spend_by_hour[hour] += cost
            model_info = model_by_trace.get(row.get("trace_id")) or {}
            if model_info.get("model"):
                spend_by_model[model_info["model"]] += cost
            if model_info.get("provider"):
                spend_by_provider[model_info["provider"]] += cost

    budget_rows = []
    for (tenant, role), budget in role_budgets.items():
        if budget <= 0:
            continue
        used = int(tokens_by_role_key.get((tenant, role), 0))
        utilization = _pct(used, budget) or 0.0
        budget_rows.append({
            "tenant_id": tenant,
            "role_id": role,
            "token_budget_per_day": budget,
            "tokens_used": used,
            "remaining_tokens": max(0, budget - used),
            "utilization_pct": utilization,
        })
    total_budget = sum(r["token_budget_per_day"] for r in budget_rows)
    used_budget_tokens = sum(r["tokens_used"] for r in budget_rows)
    budget_utilization = _pct(used_budget_tokens, total_budget) if total_budget else None
    budget_risks = sorted(
        [r for r in budget_rows if r["utilization_pct"] >= 75],
        key=lambda r: r["utilization_pct"],
        reverse=True,
    )[:8]

    if not chat_table_available:
        _gap(gaps, "tokens_today", "dashboard_chat_metrics is not available")
        _gap(gaps, "budget_refusals", "budget refusals are only available from audit fallback")
    if not cost_available:
        _gap(gaps, "estimated_cost", "model-call cost attribution is not recorded yet")
        _gap(gaps, "spend_breakdowns", "cost breakdowns require estimated_cost_usd on chat metrics")
    if not stage_table_available:
        _gap(gaps, "model_provider_breakdowns", "dashboard_stage_metrics is not available")
    elif not tokens_by_model:
        _gap(gaps, "model_provider_breakdowns", "no model stage telemetry recorded in this window")
    if not budget_rows:
        _gap(gaps, "budget_utilization", "no token_budget_per_day values are configured for scoped roles")

    def _cost_rows(counter: Counter[str], key: str) -> list[dict[str, Any]]:
        return [{key: k, "cost_usd": round(v, 6)} for k, v in counter.most_common() if v or cost_available]

    def _token_rows(counter: Counter[str], key: str) -> list[dict[str, Any]]:
        return [{key: k, "tokens": int(v)} for k, v in counter.most_common()]

    by_action = {
        r["action"]: {"count": int(r["n"]), "deny": int(r["deny"]), "cost_usd": None}
        for r in raw["action_rows"]
    }
    recent_events = []
    for row in chat_rows[:25]:
        model_info = model_by_trace.get(row.get("trace_id")) or {}
        recent_events.append({
            "timestamp": _iso(row.get("started_at")),
            "trace_id": row.get("trace_id"),
            "tenant_id": row.get("tenant_id"),
            "role": row.get("role_id"),
            "model": model_info.get("model"),
            "provider": model_info.get("provider"),
            "input_tokens": int(row.get("prompt_tokens") or 0),
            "output_tokens": int(row.get("completion_tokens") or 0),
            "total_tokens": int(row.get("tokens_total") or 0),
            "estimated_cost": float(row.get("estimated_cost_usd")) if row.get("estimated_cost_usd") is not None else None,
            "budget_status": "refused" if row.get("budget_refusal") else "ok",
        })

    return {
        "hours": hours,
        "summary": {
            "tokens_today": total_tokens,
            "estimated_cost_today": total_cost,
            "avg_cost_per_turn": avg_cost_per_turn,
            "budget_utilization_pct": budget_utilization,
            "budget_refusals": budget_refusals,
            "projected_daily_spend": projected_daily_spend,
        },
        "breakdowns": {
            "by_tenant": _cost_rows(spend_by_tenant, "tenant_id") if cost_available else [],
            "by_role": _cost_rows(spend_by_role, "role_id") if cost_available else [],
            "by_model": _cost_rows(spend_by_model, "model") if cost_available else [],
            "by_provider": _cost_rows(spend_by_provider, "provider") if cost_available else [],
            "by_hour": [{"hour": k, "cost_usd": round(v, 6)} for k, v in sorted(spend_by_hour.items())] if cost_available else [],
        },
        "token_breakdown": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "by_tenant": _token_rows(tokens_by_tenant, "tenant_id"),
            "by_role": _token_rows(tokens_by_role, "role_id"),
            "by_model": _token_rows(tokens_by_model, "model"),
            "by_provider": _token_rows(tokens_by_provider, "provider"),
            "by_hour": [{"hour": k, "tokens": int(v)} for k, v in sorted(tokens_by_hour.items())],
        },
        "budget_governance": {
            "daily_budgets": budget_rows,
            "current_burn_tokens": used_budget_tokens if budget_rows else None,
            "remaining_budget_tokens": max(0, total_budget - used_budget_tokens) if budget_rows else None,
            "budget_refusal_count": budget_refusals,
            "top_budget_risks": budget_risks,
        },
        "recent_events": recent_events,
        "budget_risks": budget_risks,
        "instrumentation_gaps": gaps,
        "scope": {"admin_scope": principal.scope, "tenant_id": principal.tenant_id},
        # Compatibility with the original FinOps widgets.
        "by_tenant": {r["tenant_id"]: int(r["n"]) for r in raw["tenant_rows"]},
        "by_action": by_action,
        "total_cost_usd": total_cost,
        "denied_on_budget": budget_refusals,
    }


@router.get("/finops/budget")
async def finops_budget(principal: AdminPrincipal = Depends(admin_principal)):
    """Per-role token budget vs. today's real token usage."""
    def _q():
        with get_conn() as conn:
            scoped = principal.scope != "platform" and principal.tenant_id
            tenant_clause = " AND tenant_id=%s" if scoped else ""
            roles = conn.execute(
                f"""
                SELECT tenant_id, role_id, capabilities
                FROM roles
                WHERE 1=1 {tenant_clause}
                ORDER BY tenant_id, role_id
                """,
                [principal.tenant_id] if scoped else [],
            ).fetchall()
            chat_table = bool(conn.execute("SELECT to_regclass('public.dashboard_chat_metrics') AS t").fetchone()["t"])
            usage_rows = []
            if chat_table:
                usage_rows = conn.execute(
                    f"""
                    SELECT tenant_id, role_id, sum(tokens_total)::bigint AS tokens
                    FROM dashboard_chat_metrics
                    WHERE started_at >= date_trunc('day', now()) {tenant_clause}
                    GROUP BY tenant_id, role_id
                    """,
                    [principal.tenant_id] if scoped else [],
                ).fetchall()
            return [dict(r) for r in roles], [dict(r) for r in usage_rows], chat_table

    roles, usage_rows, chat_table = await run_db(_q)
    usage_map = {(r["tenant_id"], r["role_id"]): int(r["tokens"] or 0) for r in usage_rows}
    out = []
    for role in roles:
        caps = _json_dict(role.get("capabilities"))
        budget = int(caps.get("token_budget_per_day") or 0)
        if budget <= 0:
            continue
        used = usage_map.get((role["tenant_id"], role["role_id"]), 0) if chat_table else None
        pct = _pct(used or 0, budget) if used is not None else None
        out.append({
            "team": f"{role['tenant_id']}/{role['role_id']}",
            "tenant_id": role["tenant_id"],
            "role_id": role["role_id"],
            "budget_tokens": budget,
            "spent_tokens": used,
            "remaining_tokens": max(0, budget - used) if used is not None else None,
            "utilization_pct": pct,
            "budget_usd": None,
            "spent_usd": None,
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
