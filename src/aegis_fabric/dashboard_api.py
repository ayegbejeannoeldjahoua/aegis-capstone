"""Dashboard / Runs / FinOps / Policy aggregation endpoints.

Mounted under /admin. Backed by aggregations over `audit_events` and the
existing `usage` Redis counters. All endpoints require admin_principal.
"""
from __future__ import annotations
import calendar
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import json
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .auth import AdminPrincipal, admin_principal
from .db import get_conn, run_db
from .audit import verify_chain
from .operational_metrics import active_requests
from .monthly_activity import load_monthly_activity
from .token_budgets import build_user_budget_hierarchy

try:
    import resource
except ImportError:  # Windows test/dev environments do not provide resource.
    resource = None  # type: ignore[assignment]

router = APIRouter(prefix="/admin", tags=["dashboard"])


# ============================================================
# Dashboard
# ============================================================
@router.get("/dashboard/metrics")
async def dashboard_metrics(month: str | None = None, principal: AdminPrincipal = Depends(admin_principal)):
    """Operational and governance dashboard metrics.

    Platform admins and the shared admin token see all tenants. Tenant admins see
    the same shape scoped to their tenant. Non-admin roles are rejected by
    `admin_principal` before this handler runs.
    """
    period_start, period_end, month_key, _ = _month_bounds(month)

    def _q():
        with get_conn() as conn:
            scoped = principal.scope != "platform" and principal.tenant_id
            tenant_clause = " AND tenant_id=%s" if scoped else ""
            period_params = [period_start, period_end, principal.tenant_id] if scoped else [period_start, period_end]

            chat_table = bool(conn.execute("SELECT to_regclass('public.dashboard_chat_metrics') AS t").fetchone()["t"])
            stage_table = bool(conn.execute("SELECT to_regclass('public.dashboard_stage_metrics') AS t").fetchone()["t"])

            audit_rows = conn.execute(
                f"""
                SELECT trace_id, tenant_id, subject, action, resource, decision, reason, created_at
                FROM audit_events
                WHERE created_at >= %s AND created_at < %s {tenant_clause}
                ORDER BY created_at DESC, sequence_id DESC
                """,
                period_params,
            ).fetchall()
            chat_rows = []
            if chat_table:
                chat_rows = conn.execute(
                    f"""
                    SELECT *
                    FROM dashboard_chat_metrics
                    WHERE started_at >= %s AND started_at < %s {tenant_clause}
                    ORDER BY started_at DESC
                    """,
                    period_params,
                ).fetchall()
            stage_rows = []
            if stage_table:
                stage_rows = conn.execute(
                    f"""
                    SELECT trace_id, tenant_id, stage, duration_ms, metadata, created_at
                    FROM dashboard_stage_metrics
                    WHERE created_at >= %s AND created_at < %s {tenant_clause}
                    ORDER BY created_at DESC
                    """,
                    period_params,
                ).fetchall()
            isas = conn.execute(
                f"""
                SELECT trace_id, tenant_id, total, met, verified, created_at
                FROM isas
                WHERE created_at >= %s AND created_at < %s {tenant_clause}
                """,
                period_params,
            ).fetchall()
            roles = conn.execute(
                f"""
                SELECT tenant_id, role_id, capabilities
                FROM roles
                WHERE 1=1 {tenant_clause}
                """,
                [principal.tenant_id] if scoped else [],
            ).fetchall()
            pg_connections = None
            try:
                pg_connections = conn.execute("SELECT count(*) AS c FROM pg_stat_activity").fetchone()["c"]
            except Exception:
                pg_connections = None
            return {
                "period": {
                    "month": month_key,
                    "start": period_start,
                    "end": period_end,
                },
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
    canonical = await run_db(load_monthly_activity, principal, month_key=month)
    raw["canonical"] = canonical
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


def _month_bounds(month: str | None = None) -> tuple[datetime, datetime, str, int]:
    now = datetime.now(timezone.utc)
    if month:
        try:
            start = datetime.strptime(month, "%Y-%m").replace(tzinfo=timezone.utc)
        except ValueError:
            raise HTTPException(status_code=400, detail="month must use YYYY-MM format")
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if start.month == 12:
        end = start.replace(year=start.year + 1, month=1)
    else:
        end = start.replace(month=start.month + 1)
    return start, end, start.strftime("%Y-%m"), calendar.monthrange(start.year, start.month)[1]


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
    if resource is None:
        return None
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
    canonical_payload = raw.get("canonical") if isinstance(raw.get("canonical"), dict) else None
    canonical_events = canonical_payload.get("events") if canonical_payload is not None else []
    chat_table_available = bool(raw["chat_table"])
    stage_table_available = bool(raw["stage_table"])
    gaps: list[dict[str, str]] = []

    audit_trace_ids = {r["trace_id"] for r in audit_rows if r.get("trace_id")}
    response_traces = {
        r["trace_id"] for r in audit_rows
        if r.get("action") == "response.return" and r.get("decision") == "allow"
    }
    fallback_request_count = len(response_traces) or len(audit_trace_ids)
    canonical_request_count = len(canonical_events)
    canonical_successful_turns = sum(
        1 for r in canonical_events
        if str(r.get("request_status") or "").lower() in {"success", "unmetered"}
    )
    request_count = (
        canonical_request_count
        if canonical_payload is not None else (len(chat_rows) if chat_table_available else fallback_request_count)
    )
    successful_turns = canonical_successful_turns if canonical_payload is not None else (
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

    canonical_active_tenants = len({r.get("tenant_id") for r in canonical_events if r.get("tenant_id")})
    active_tenants = canonical_active_tenants if canonical_payload is not None else len(
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
        "requests_month_to_date": request_count,
        "successful_chat_turns": successful_turns,
        "successful_chat_turns_month_to_date": successful_turns,
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
        "period": {
            "month": raw.get("period", {}).get("month"),
            "start": _iso(raw.get("period", {}).get("start")),
            "end": _iso(raw.get("period", {}).get("end")),
        },
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
async def finops_summary(month: str | None = None,
                          hours: int | None = Query(None, le=168),
                          tenant_id: str | None = None,
                          tenant: str | None = None,
                          team: str | None = None,
                          role: str | None = None,
                          user_email: str | None = None,
                          user: str | None = None,
                          principal: AdminPrincipal = Depends(admin_principal)):
    """Token, model-routing, and budget governance for the selected month.

    ``hours`` is accepted for older clients but the product default is current
    month-to-date. Cost fields remain nullable and are never synthesized.
    """
    _ = hours
    period_start, period_end, month_key, days_in_month = _month_bounds(month)
    selected_tenant = tenant_id or tenant or ""
    selected_team = team or ""
    selected_role = role or ""
    selected_user = user_email or user or ""

    def _q():
        with get_conn() as conn:
            scoped = principal.scope != "platform" and principal.tenant_id
            tenant_clause = " AND tenant_id=%s" if scoped else ""
            period_params = [period_start, period_end, principal.tenant_id] if scoped else [period_start, period_end]
            tenant_params = [principal.tenant_id] if scoped else []
            chat_table = bool(conn.execute("SELECT to_regclass('public.dashboard_chat_metrics') AS t").fetchone()["t"])
            stage_table = bool(conn.execute("SELECT to_regclass('public.dashboard_stage_metrics') AS t").fetchone()["t"])
            finops_table = bool(conn.execute("SELECT to_regclass('public.finops_events') AS t").fetchone()["t"])
            finops_has_team = False
            finops_has_token_source = False
            if finops_table:
                finops_columns = {
                    row["column_name"]
                    for row in conn.execute(
                        """
                        SELECT column_name
                        FROM information_schema.columns
                        WHERE table_schema='public' AND table_name='finops_events'
                        """
                    ).fetchall()
                }
                finops_has_team = "team_id" in finops_columns
                finops_has_token_source = "token_source" in finops_columns
            chat_rows = []
            if chat_table:
                chat_rows = conn.execute(
                    f"""
                    SELECT *
                    FROM dashboard_chat_metrics
                    WHERE started_at >= %s AND started_at < %s {tenant_clause}
                    ORDER BY started_at DESC
                    """,
                    period_params,
                ).fetchall()
            stage_rows = []
            if stage_table:
                stage_rows = conn.execute(
                    f"""
                    SELECT trace_id, tenant_id, stage, duration_ms, metadata, created_at
                    FROM dashboard_stage_metrics
                    WHERE created_at >= %s AND created_at < %s {tenant_clause}
                    ORDER BY created_at DESC
                    """,
                    period_params,
                ).fetchall()
            event_rows = []
            if finops_table:
                def _finops_col(name: str, fallback: str) -> str:
                    return name if name in finops_columns else f"{fallback} AS {name}"

                team_expr = "team_id" if finops_has_team else "NULL::text AS team_id"
                token_source_expr = (
                    "token_source"
                    if finops_has_token_source
                    else """
                    CASE
                      WHEN COALESCE(input_tokens, 0) > 0 OR COALESCE(output_tokens, 0) > 0 THEN 'provider'
                      WHEN COALESCE(total_tokens, 0) > 0 THEN 'estimated'
                      ELSE 'unmetered'
                    END AS token_source
                    """
                )
                estimated_cost_expr = _finops_col("estimated_cost_usd", "NULL::numeric")
                budget_limit_usd_expr = _finops_col("budget_limit_usd", "NULL::numeric")
                budget_remaining_usd_expr = _finops_col("budget_remaining_usd", "NULL::numeric")
                budget_limit_tokens_expr = _finops_col("budget_limit_tokens", "NULL::integer")
                budget_remaining_tokens_expr = _finops_col("budget_remaining_tokens", "NULL::integer")
                budget_profile_expr = _finops_col("budget_profile", "'{}'::jsonb")
                reached_model_expr = _finops_col("reached_model", "FALSE")
                blocked_before_model_expr = _finops_col("blocked_before_model", "FALSE")
                status_expr = _finops_col("status", "'unknown'::text")
                metadata_expr = _finops_col("metadata", "'{}'::jsonb")
                event_rows = conn.execute(
                    f"""
                    SELECT id, created_at, trace_id, request_id, tenant_id, user_email,
                           {team_expr}, role, action, decision, provider, model, input_tokens,
                           output_tokens, total_tokens, {token_source_expr}, {estimated_cost_expr}, {budget_limit_usd_expr},
                           {budget_remaining_usd_expr}, {budget_limit_tokens_expr}, {budget_remaining_tokens_expr},
                           {budget_profile_expr}, reason, {reached_model_expr}, {blocked_before_model_expr},
                           {status_expr}, {metadata_expr}
                    FROM finops_events
                    WHERE created_at >= %s AND created_at < %s {tenant_clause}
                    ORDER BY created_at DESC, id DESC
                    """,
                    period_params,
                ).fetchall()
            action_rows = conn.execute(f"""
                SELECT action, count(*) AS n,
                       count(*) FILTER (WHERE decision='deny') AS deny
                FROM audit_events
                WHERE created_at >= %s AND created_at < %s {tenant_clause}
                GROUP BY 1 ORDER BY 2 DESC
            """, period_params).fetchall()
            tenant_rows = conn.execute(f"""
                SELECT tenant_id, count(*) AS n
                FROM audit_events
                WHERE created_at >= %s AND created_at < %s {tenant_clause}
                GROUP BY 1 ORDER BY 2 DESC
            """, period_params).fetchall()
            budget_denies = conn.execute(f"""
                SELECT count(*) AS n
                FROM audit_events
                WHERE created_at >= %s AND created_at < %s {tenant_clause}
                  AND decision='deny'
                  AND (reason ILIKE '%%budget%%' OR reason ILIKE '%%quota%%')
            """, period_params).fetchone()["n"]
            roles = conn.execute(
                f"""
                SELECT tenant_id, role_id, capabilities
                FROM roles
                WHERE 1=1 {tenant_clause}
                ORDER BY tenant_id, role_id
                """,
                tenant_params,
            ).fetchall()
            assignments = conn.execute(
                f"""
                SELECT tenant_id, lower(user_email) AS user_email, team_id, role_id
                FROM user_assignments
                WHERE 1=1 {tenant_clause}
                ORDER BY tenant_id, team_id, role_id, user_email
                """,
                tenant_params,
            ).fetchall()
            return {
                "period": {"month": month_key, "start": period_start, "end": period_end, "days_in_month": days_in_month},
                "chat_table": chat_table,
                "stage_table": stage_table,
                "finops_table": finops_table,
                "chat_rows": [dict(r) for r in chat_rows],
                "stage_rows": [dict(r) for r in stage_rows],
                "event_rows": [dict(r) for r in event_rows],
                "action_rows": [dict(r) for r in action_rows],
                "tenant_rows": [dict(r) for r in tenant_rows],
                "budget_denies": int(budget_denies or 0),
                "roles": [dict(r) for r in roles],
                "assignments": [dict(r) for r in assignments],
            }

    raw = await run_db(_q)
    canonical = await run_db(
        load_monthly_activity,
        principal,
        month_key=month,
        tenant_id=selected_tenant or None,
        team=selected_team or None,
        role=selected_role or None,
        user_email=selected_user or None,
    )
    raw["canonical"] = canonical
    raw["source_counts"] = canonical.get("source_counts", {})
    chat_rows = raw["chat_rows"]
    stage_rows = raw["stage_rows"]
    event_rows = raw.get("event_rows") or []
    chat_table_available = bool(raw["chat_table"])
    stage_table_available = bool(raw["stage_table"])
    finops_table_available = bool(raw.get("finops_table"))
    gaps: list[dict[str, str]] = []

    role_budgets: dict[tuple[str, str], int] = {}
    for role in raw["roles"]:
        caps = _json_dict(role.get("capabilities"))
        budget = int(caps.get("token_budget_per_day") or 0)
        role_budgets[(role["tenant_id"], role["role_id"])] = budget
    assignment_by_user = {
        (row.get("tenant_id"), str(row.get("user_email") or "").lower()): row
        for row in raw.get("assignments") or []
    }

    model_by_trace: dict[str, dict[str, Any]] = {}
    for row in stage_rows:
        if row.get("stage") not in {"model", "model_error"}:
            continue
        meta = _metadata(row.get("metadata"))
        model = str(meta.get("model") or "unknown")
        provider = str(meta.get("provider") or "unknown")
        trace_id = row.get("trace_id")
        if trace_id and trace_id not in model_by_trace:
            model_by_trace[trace_id] = {"model": model, "provider": provider, "latency_ms": row.get("duration_ms")}

    def _row_time(row: dict[str, Any]) -> Any:
        return row.get("created_at") or row.get("started_at")

    def _hour_key(value: Any) -> str:
        return value.replace(minute=0, second=0, microsecond=0).isoformat() if hasattr(value, "replace") else "unknown"

    def _row_tokens(row: dict[str, Any]) -> int:
        return int(row.get("total_tokens") if row.get("total_tokens") is not None else row.get("tokens_total") or 0)

    def _row_status(row: dict[str, Any]) -> str:
        return str(row.get("request_status") or row.get("status") or "unknown")

    def _row_decision(row: dict[str, Any]) -> str:
        return str(row.get("budget_decision") or row.get("decision") or "unknown")

    def _row_reached_model(row: dict[str, Any]) -> bool:
        return bool(row.get("reached_model") or row.get("model") or row.get("provider"))

    def _eventish_from_chat(row: dict[str, Any]) -> dict[str, Any]:
        model_info = model_by_trace.get(row.get("trace_id")) or {}
        status = row.get("status") or "unknown"
        budget_refused = bool(row.get("budget_refusal"))
        email = str(row.get("subject") or "").lower()
        assignment = assignment_by_user.get((row.get("tenant_id"), email)) or {}
        prompt_tokens = int(row.get("prompt_tokens") or 0)
        completion_tokens = int(row.get("completion_tokens") or 0)
        total_tokens = int(row.get("tokens_total") or 0)
        return {
            "created_at": row.get("started_at"),
            "trace_id": row.get("trace_id"),
            "tenant_id": row.get("tenant_id"),
            "user_email": row.get("subject"),
            "team_id": assignment.get("team_id"),
            "role": row.get("role_id"),
            "decision": "deny" if budget_refused else "allow",
            "provider": model_info.get("provider"),
            "model": model_info.get("model"),
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": total_tokens,
            "token_source": "provider" if prompt_tokens or completion_tokens else ("estimated" if total_tokens else "unmetered"),
            "estimated_cost_usd": row.get("estimated_cost_usd") if row.get("cost_instrumented") else None,
            "budget_limit_tokens": role_budgets.get((row.get("tenant_id"), row.get("role_id"))) or None,
            "budget_remaining_tokens": None,
            "reason": row.get("refusal_reason") or row.get("error_type"),
            "reached_model": bool(model_info) or int(row.get("tokens_total") or 0) > 0,
            "blocked_before_model": status != "success" and not model_info,
            "status": "refused_budget" if budget_refused else ("success" if status == "success" else "unknown"),
            "metadata": {},
        }

    canonical_payload = raw.get("canonical") if isinstance(raw.get("canonical"), dict) else None
    canonical_events = canonical_payload.get("events") if canonical_payload is not None else None
    activity_rows = (
        canonical_events
        if canonical_events is not None else (event_rows if finops_table_available else [_eventish_from_chat(r) for r in chat_rows])
    )
    activity_available = bool(activity_rows)

    tokens_by_tenant: Counter[str] = Counter()
    tokens_by_team: Counter[str] = Counter()
    tokens_by_tenant_team: Counter[tuple[str, str]] = Counter()
    tokens_by_tenant_team_role: Counter[tuple[str, str, str]] = Counter()
    tokens_by_role: Counter[str] = Counter()
    tokens_by_user: Counter[str] = Counter()
    tokens_by_user_key: Counter[tuple[str, str, str, str]] = Counter()
    tokens_by_role_key: Counter[tuple[str, str]] = Counter()
    tokens_by_hour: Counter[str] = Counter()
    token_source_counts: Counter[str] = Counter()
    spend_by_tenant: Counter[str] = Counter()
    spend_by_role: Counter[str] = Counter()
    spend_by_hour: Counter[str] = Counter()
    tokens_by_model: Counter[str] = Counter()
    tokens_by_provider: Counter[str] = Counter()
    spend_by_model: Counter[str] = Counter()
    spend_by_provider: Counter[str] = Counter()
    requests_by_tenant: Counter[str] = Counter()
    requests_by_team: Counter[str] = Counter()
    requests_by_tenant_team: Counter[tuple[str, str]] = Counter()
    requests_by_tenant_team_role: Counter[tuple[str, str, str]] = Counter()
    requests_by_role: Counter[str] = Counter()
    requests_by_user: Counter[str] = Counter()
    requests_by_user_key: Counter[tuple[str, str, str, str]] = Counter()
    requests_by_model: Counter[str] = Counter()
    requests_by_provider: Counter[str] = Counter()
    decision_counts: Counter[str] = Counter()
    status_counts: Counter[str] = Counter()

    for row in activity_rows:
        tenant = row.get("tenant_id") or "unknown"
        user = row.get("user_email") or "unknown"
        assignment = assignment_by_user.get((tenant, str(user).lower())) or {}
        team = row.get("team_id") or assignment.get("team_id") or "unknown"
        role = row.get("role") or row.get("role_id") or "unknown"
        model = row.get("model") or "unknown"
        provider = row.get("provider") or "unknown"
        tokens = _row_tokens(row)
        token_source = row.get("token_source") or ("estimated" if tokens else "unmetered")
        cost_value = row.get("estimated_cost_usd")
        cost = float(cost_value) if cost_value is not None else None
        hour = _hour_key(_row_time(row))
        decision = _row_decision(row)
        status = _row_status(row)

        requests_by_tenant[tenant] += 1
        requests_by_team[team] += 1
        requests_by_tenant_team[(tenant, team)] += 1
        requests_by_tenant_team_role[(tenant, team, role)] += 1
        requests_by_role[role] += 1
        requests_by_user[user] += 1
        requests_by_user_key[(tenant, team, role, user)] += 1
        if row.get("model"):
            requests_by_model[model] += 1
        if row.get("provider"):
            requests_by_provider[provider] += 1
        decision_counts[decision] += 1
        status_counts[status] += 1

        tokens_by_tenant[tenant] += tokens
        tokens_by_team[team] += tokens
        tokens_by_tenant_team[(tenant, team)] += tokens
        tokens_by_tenant_team_role[(tenant, team, role)] += tokens
        tokens_by_role[role] += tokens
        tokens_by_user[user] += tokens
        tokens_by_user_key[(tenant, team, role, user)] += tokens
        tokens_by_role_key[(tenant, role)] += tokens
        tokens_by_hour[hour] += tokens
        token_source_counts[str(token_source)] += 1
        if row.get("model"):
            tokens_by_model[model] += tokens
        if row.get("provider"):
            tokens_by_provider[provider] += tokens
        if cost is not None:
            spend_by_tenant[tenant] += cost
            spend_by_role[role] += cost
            spend_by_hour[hour] += cost
            if row.get("model"):
                spend_by_model[model] += cost
            if row.get("provider"):
                spend_by_provider[provider] += cost

    total_tokens = sum(_row_tokens(r) for r in activity_rows) if activity_available else None
    input_tokens = sum(int(r.get("input_tokens") or r.get("prompt_tokens") or 0) for r in activity_rows) if activity_available else None
    output_tokens = sum(int(r.get("output_tokens") or r.get("completion_tokens") or 0) for r in activity_rows) if activity_available else None
    request_count = len(activity_rows) if activity_available else 0
    successful_turns = int(status_counts.get("success", 0)) if activity_available else 0
    cost_rows = [
        float(r.get("estimated_cost_usd") or 0)
        for r in activity_rows
        if r.get("estimated_cost_usd") is not None
    ]
    total_cost = round(sum(cost_rows), 6) if cost_rows else None
    cost_available = bool(cost_rows)
    budget_refusals = (
        sum(1 for r in activity_rows if _row_status(r) == "refused_budget" or _row_decision(r) in {"deny", "refused_budget"})
        if activity_available else raw["budget_denies"]
    )
    now = datetime.now(timezone.utc)
    elapsed_month_fraction = max(
        1 / max(days_in_month, 1),
        ((now - period_start).total_seconds() / max((period_end - period_start).total_seconds(), 1.0))
        if period_start <= now < period_end else 1.0,
    )
    projected_monthly_spend = round((total_cost or 0) / elapsed_month_fraction, 6) if cost_available else None
    avg_cost_per_turn = round(total_cost / successful_turns, 6) if cost_available and successful_turns else None
    model_routed_requests = sum(1 for r in activity_rows if _row_reached_model(r))
    unmetered_requests = sum(
        1 for r in activity_rows
        if _row_reached_model(r)
        and r.get("estimated_cost_usd") is None
        and _row_tokens(r) == 0
    )
    metering_notice = None
    if request_count and not cost_available:
        metering_notice = (
            "Requests recorded, token/cost metering unavailable for this provider."
            if not total_tokens
            else "Requests recorded, cost metering unavailable for this provider."
        )

    assignments = raw.get("assignments") or []
    budget_hierarchy = build_user_budget_hierarchy(
        assignments,
        raw["roles"],
        days_in_month=days_in_month,
    )
    user_budget_monthly: dict[str, int] = budget_hierarchy["user_budget_monthly"]
    user_budget_monthly_by_key: Counter[tuple[str, str, str, str]] = budget_hierarchy["user_budget_monthly_by_key"]
    team_budget_monthly: Counter[str] = budget_hierarchy["team_budget_monthly"]
    tenant_team_budget_monthly: Counter[tuple[str, str]] = budget_hierarchy["tenant_team_budget_monthly"]
    tenant_budget_monthly: Counter[str] = budget_hierarchy["tenant_budget_monthly"]
    role_budget_monthly: Counter[str] = budget_hierarchy["role_budget_monthly"]
    tenant_team_role_budget_monthly: Counter[tuple[str, str, str]] = budget_hierarchy["tenant_team_role_budget_monthly"]

    budget_rows = []
    for (tenant, team, role), budget in sorted(tenant_team_role_budget_monthly.items()):
        if budget <= 0:
            continue
        used = int(tokens_by_tenant_team_role.get((tenant, team, role), 0))
        utilization = _pct(used, budget) or 0.0
        budget_rows.append({
            "tenant_id": tenant,
            "team_id": team,
            "role_id": role,
            "token_budget_per_day": max(1, round(budget / max(days_in_month, 1))),
            "monthly_token_budget": budget,
            "tokens_used": used,
            "remaining_tokens": max(0, budget - used),
            "utilization_pct": utilization,
            "budget_source": "sum_of_user_monthly_budgets",
        })
    total_budget = sum(r["monthly_token_budget"] for r in budget_rows)
    used_budget_tokens = sum(r["tokens_used"] for r in budget_rows)
    budget_utilization = _pct(used_budget_tokens, total_budget) if total_budget else None
    budget_risks = sorted(
        [r for r in budget_rows if r["utilization_pct"] >= 75],
        key=lambda r: r["utilization_pct"],
        reverse=True,
    )[:8]

    if not chat_table_available:
        _gap(gaps, "tokens_month_to_date", "dashboard_chat_metrics is not available")
        _gap(gaps, "budget_refusals", "budget refusals are only available from audit fallback")
    if not finops_table_available:
        _gap(gaps, "finops_events", "finops_events is not available")
    if not cost_available:
        _gap(gaps, "estimated_cost", "model-call cost attribution is not recorded for this provider")
        _gap(gaps, "spend_breakdowns", "cost breakdowns require provider cost metering")
    if not stage_table_available:
        _gap(gaps, "model_provider_breakdowns", "dashboard_stage_metrics is not available")
    elif not requests_by_model:
        _gap(gaps, "model_provider_breakdowns", "no model routing telemetry recorded in this window")
    if not activity_available:
        _gap(gaps, "budget_utilization", "chat or FinOps event metrics are required for real token-budget burn")
    elif not budget_rows:
        _gap(gaps, "budget_utilization", "no assigned users are available for user-level token budgets")

    def _cost_rows(counter: Counter[str], key: str) -> list[dict[str, Any]]:
        return [{key: k, "cost_usd": round(v, 6)} for k, v in counter.most_common() if v or cost_available]

    def _token_rows(counter: Counter[str], key: str) -> list[dict[str, Any]]:
        return [{key: k, "tokens": int(v)} for k, v in counter.most_common()]

    def _token_request_rows(counter: Counter[str], request_counter: Counter[str], key: str) -> list[dict[str, Any]]:
        labels = set(counter) | set(request_counter)
        return [
            {key: k, "tokens": int(counter.get(k, 0)), "requests": int(request_counter.get(k, 0))}
            for k in sorted(labels, key=lambda item: (request_counter.get(item, 0), counter.get(item, 0), item), reverse=True)
        ]

    def _request_rows(counter: Counter[str], key: str) -> list[dict[str, Any]]:
        return [{key: k, "requests": int(v)} for k, v in counter.most_common()]

    def _token_budget_rows(
        counter: Counter[str],
        requests: Counter[str],
        budgets: dict[str, int] | Counter[str],
        key: str,
    ) -> list[dict[str, Any]]:
        labels = set(counter) | set(requests) | {k for k, v in budgets.items() if v}
        ordered = sorted(labels, key=lambda item: (counter.get(item, 0), requests.get(item, 0), item), reverse=True)
        rows = []
        for label in ordered:
            budget = int(budgets.get(label, 0) or 0)
            tokens = int(counter.get(label, 0))
            rows.append({
                key: label,
                "tokens": tokens,
                "requests": int(requests.get(label, 0)),
                "budget_tokens": budget or None,
                "utilization_pct": _pct(tokens, budget) if budget else None,
                "budget_source": "sum_of_user_monthly_budgets" if budget else "not_configured",
            })
        return rows

    def _filter_options() -> dict[str, list[dict[str, Any]]]:
        tenants = {
            str(item)
            for item in set(tokens_by_tenant) | set(tenant_budget_monthly)
            if item not in (None, "")
        }
        teams = {
            (row.get("tenant_id"), row.get("team_id") or "unknown")
            for row in assignments
            if row.get("tenant_id")
        } | set(tokens_by_tenant_team)
        roles = {
            (row.get("tenant_id"), row.get("team_id") or "unknown", row.get("role_id") or "unknown")
            for row in assignments
            if row.get("tenant_id")
        } | set(tokens_by_tenant_team_role)
        users = {
            (
                row.get("tenant_id"),
                row.get("team_id") or "unknown",
                row.get("role_id") or "unknown",
                row.get("user_email") or "unknown",
            )
            for row in assignments
            if row.get("tenant_id")
        } | set(tokens_by_user_key)
        for tenant_id, role_id in role_budgets:
            tenants.add(str(tenant_id))
            roles.add((tenant_id, "all", role_id))
        return {
            "tenants": [{"value": "", "label": "All tenants"}, *[
                {"value": value, "label": value} for value in sorted(tenants)
            ]],
            "teams": [{"value": "", "label": "All teams"}, *[
                {"value": f"{tenant_id}|{team_id}", "label": f"{tenant_id} / {team_id}", "tenant_id": tenant_id, "team_id": team_id}
                for tenant_id, team_id in sorted(teams)
            ]],
            "roles": [{"value": "", "label": "All roles"}, *[
                {
                    "value": f"{tenant_id}|{team_id}|{role_id}",
                    "label": f"{tenant_id} / {team_id} / {role_id}",
                    "tenant_id": tenant_id,
                    "team_id": team_id,
                    "role_id": role_id,
                }
                for tenant_id, team_id, role_id in sorted(roles)
            ]],
            "users": [{"value": "", "label": "All users"}, *[
                {
                    "value": f"{tenant_id}|{team_id}|{role_id}|{email}",
                    "label": email,
                    "tenant_id": tenant_id,
                    "team_id": team_id,
                    "role_id": role_id,
                    "user_email": email,
                }
                for tenant_id, team_id, role_id, email in sorted(users)
            ]],
        }

    def _dimension_row(label: str, tokens: int, requests: int, budget: int, **extra: Any) -> dict[str, Any]:
        return {
            **extra,
            "label": label,
            "tokens": int(tokens or 0),
            "used_tokens": int(tokens or 0),
            "budget_tokens": int(budget or 0),
            "requests": int(requests or 0),
            "usage_percent": _pct(int(tokens or 0), int(budget or 0)) or 0,
        }

    def _tenant_rows() -> list[dict[str, Any]]:
        labels = set(tokens_by_tenant) | set(requests_by_tenant) | set(tenant_budget_monthly)
        return sorted(
            [
                _dimension_row(
                    tenant_id,
                    tokens_by_tenant.get(tenant_id, 0),
                    requests_by_tenant.get(tenant_id, 0),
                    tenant_budget_monthly.get(tenant_id, 0),
                    tenant_id=tenant_id,
                )
                for tenant_id in labels
            ],
            key=lambda row: (row["tokens"], row["requests"], row["label"]),
            reverse=True,
        )

    def _tenant_team_rows() -> list[dict[str, Any]]:
        labels = set(tokens_by_tenant_team) | set(requests_by_tenant_team) | set(tenant_team_budget_monthly)
        return sorted(
            [
                _dimension_row(
                    f"{tenant_id} / {team_id}",
                    tokens_by_tenant_team.get((tenant_id, team_id), 0),
                    requests_by_tenant_team.get((tenant_id, team_id), 0),
                    tenant_team_budget_monthly.get((tenant_id, team_id), 0),
                    tenant_id=tenant_id,
                    team_id=team_id,
                )
                for tenant_id, team_id in labels
            ],
            key=lambda row: (row["tokens"], row["requests"], row["label"]),
            reverse=True,
        )

    def _tenant_team_role_rows() -> list[dict[str, Any]]:
        labels = set(tokens_by_tenant_team_role) | set(requests_by_tenant_team_role) | set(tenant_team_role_budget_monthly)
        return sorted(
            [
                _dimension_row(
                    f"{tenant_id} / {team_id} / {role_id}",
                    tokens_by_tenant_team_role.get((tenant_id, team_id, role_id), 0),
                    requests_by_tenant_team_role.get((tenant_id, team_id, role_id), 0),
                    tenant_team_role_budget_monthly.get((tenant_id, team_id, role_id), 0),
                    tenant_id=tenant_id,
                    team_id=team_id,
                    role_id=role_id,
                )
                for tenant_id, team_id, role_id in labels
            ],
            key=lambda row: (row["tokens"], row["requests"], row["label"]),
            reverse=True,
        )

    def _user_rows() -> list[dict[str, Any]]:
        labels = set(tokens_by_user_key) | set(requests_by_user_key) | set(user_budget_monthly_by_key)
        return sorted(
            [
                _dimension_row(
                    email,
                    tokens_by_user_key.get((tenant_id, team_id, role_id, email), 0),
                    requests_by_user_key.get((tenant_id, team_id, role_id, email), 0),
                    user_budget_monthly_by_key.get((tenant_id, team_id, role_id, email), 0),
                    tenant_id=tenant_id,
                    team_id=team_id,
                    role_id=role_id,
                    user_email=email,
                )
                for tenant_id, team_id, role_id, email in labels
            ],
            key=lambda row: (row["tokens"], row["requests"], row["label"]),
            reverse=True,
        )

    tenant_chart_rows = _tenant_rows()
    tenant_team_chart_rows = _tenant_team_rows()
    tenant_team_role_chart_rows = _tenant_team_role_rows()
    user_chart_rows = _user_rows()

    def _matches(row: dict[str, Any]) -> bool:
        if selected_tenant and row.get("tenant_id") != selected_tenant:
            return False
        if selected_team and row.get("team_id") != selected_team:
            return False
        if selected_role and row.get("role_id") != selected_role:
            return False
        if selected_user and row.get("user_email") != selected_user:
            return False
        return True

    if selected_user:
        bar_level = "user"
        bar_rows = [row for row in user_chart_rows if _matches(row)]
    elif selected_role:
        bar_level = "user"
        bar_rows = [row for row in user_chart_rows if _matches(row)]
    elif selected_team:
        bar_level = "tenant_team_role"
        bar_rows = [row for row in tenant_team_role_chart_rows if _matches(row)]
    elif selected_tenant:
        bar_level = "tenant_team"
        bar_rows = [row for row in tenant_team_chart_rows if _matches(row)]
    else:
        bar_level = "tenant"
        bar_rows = tenant_chart_rows

    notes: list[str] = []
    if not activity_rows:
        notes.append("No token usage recorded for this month yet.")
    if activity_rows and not any(_row_tokens(row) for row in activity_rows):
        notes.append("Requests recorded, token metering unavailable or unmetered for this provider.")
    if not total_budget:
        notes.append("No token budgets are configured for the selected scope.")

    analytics_summary = {
        "token_utilization": {
            "used_tokens": int(total_tokens or 0),
            "budget_tokens": int(total_budget or 0),
            "usage_percent": _pct(int(total_tokens or 0), int(total_budget or 0)) or 0,
        },
        "budget_utilization": {
            "used_tokens": int(used_budget_tokens or 0),
            "budget_tokens": int(total_budget or 0),
            "usage_percent": budget_utilization or 0,
        },
        "budget_refusals": int(budget_refusals or 0),
    }

    by_action = {
        r["action"]: {"count": int(r["n"]), "deny": int(r["deny"]), "cost_usd": None}
        for r in raw["action_rows"]
    }
    recent_events = []
    for row in activity_rows[:25]:
        recent_events.append({
            "timestamp": _iso(_row_time(row)),
            "trace_id": row.get("trace_id"),
            "tenant_id": row.get("tenant_id"),
            "user_email": row.get("user_email"),
            "team_id": row.get("team_id") or (
                assignment_by_user.get((row.get("tenant_id"), str(row.get("user_email") or "").lower())) or {}
            ).get("team_id"),
            "role": row.get("role") or row.get("role_id"),
            "model": row.get("model"),
            "provider": row.get("provider"),
            "input_tokens": int(row.get("input_tokens") or row.get("prompt_tokens") or 0),
            "output_tokens": int(row.get("output_tokens") or row.get("completion_tokens") or 0),
            "total_tokens": _row_tokens(row),
            "token_source": row.get("token_source") or "unmetered",
            "estimated_cost": float(row.get("estimated_cost_usd")) if row.get("estimated_cost_usd") is not None else None,
            "budget_status": _row_decision(row) if _row_decision(row) != "unknown" else ("refused" if row.get("budget_refusal") else "ok"),
            "status": _row_status(row),
            "reason": row.get("reason") or row.get("refusal_reason"),
            "reached_model": _row_reached_model(row),
        })

    return {
        "month": month_key,
        "period": {
            "month": month_key,
            "start": _iso(period_start),
            "end": _iso(period_end),
            "days_in_month": days_in_month,
        },
        "hours": None,
        "summary": {
            **analytics_summary,
            "requests_recorded": request_count,
            "model_routed_requests": model_routed_requests,
            "tokens_today": total_tokens,
            "tokens_month_to_date": total_tokens,
            "estimated_cost_today": total_cost,
            "estimated_cost_month_to_date": total_cost,
            "avg_cost_per_turn": avg_cost_per_turn,
            "budget_utilization_pct": budget_utilization,
            "budget_refusals": budget_refusals,
            "projected_daily_spend": projected_monthly_spend,
            "projected_monthly_spend": projected_monthly_spend,
            "metering_notice": metering_notice,
        },
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_counts": raw.get("source_counts", {}),
        "pie_charts": {
            "tenants": tenant_chart_rows,
            "tenant_teams": tenant_team_chart_rows,
            "tenant_team_roles": tenant_team_role_chart_rows,
        },
        "filters": _filter_options(),
        "bar_chart": {
            "level": bar_level,
            "rows": bar_rows,
            "selected": {
                "tenant": selected_tenant,
                "team": selected_team,
                "role": selected_role,
                "user": selected_user,
            },
        },
        "notes": notes,
        "breakdowns": {
            "by_tenant": _cost_rows(spend_by_tenant, "tenant_id") if cost_available else [],
            "by_role": _cost_rows(spend_by_role, "role_id") if cost_available else [],
            "by_model": _cost_rows(spend_by_model, "model") if cost_available else [],
            "by_provider": _cost_rows(spend_by_provider, "provider") if cost_available else [],
            "by_hour": [{"hour": k, "cost_usd": round(v, 6)} for k, v in sorted(spend_by_hour.items())] if cost_available else [],
            "requests_by_tenant": _request_rows(requests_by_tenant, "tenant_id"),
            "requests_by_team": _request_rows(requests_by_team, "team_id"),
            "requests_by_role": _request_rows(requests_by_role, "role_id"),
            "requests_by_user": _request_rows(requests_by_user, "user_email"),
            "requests_by_model": _request_rows(requests_by_model, "model"),
            "requests_by_provider": _request_rows(requests_by_provider, "provider"),
            "metering_notice": metering_notice,
        },
        "token_breakdown": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "token_source_counts": dict(token_source_counts),
            "by_tenant": _token_budget_rows(tokens_by_tenant, requests_by_tenant, tenant_budget_monthly, "tenant_id"),
            "by_team": _token_budget_rows(tokens_by_team, requests_by_team, team_budget_monthly, "team_id"),
            "by_role": _token_budget_rows(tokens_by_role, requests_by_role, role_budget_monthly, "role_id"),
            "by_user": _token_budget_rows(tokens_by_user, requests_by_user, user_budget_monthly, "user_email"),
            "by_model": _token_request_rows(tokens_by_model, requests_by_model, "model"),
            "by_provider": _token_request_rows(tokens_by_provider, requests_by_provider, "provider"),
            "by_hour": [{"hour": k, "tokens": int(v)} for k, v in sorted(tokens_by_hour.items())],
        },
        "budget_governance": {
            "daily_budgets": budget_rows,
            "current_burn_tokens": used_budget_tokens if budget_rows else None,
            "remaining_budget_tokens": max(0, total_budget - used_budget_tokens) if budget_rows else None,
            "budget_refusal_count": budget_refusals,
            "event_count": request_count,
            "model_routed_count": model_routed_requests,
            "unmetered_count": unmetered_requests,
            "decision_counts": dict(decision_counts),
            "status_counts": dict(status_counts),
            "top_budget_risks": budget_risks,
            "recent_decisions": recent_events[:8],
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
    """Tenant/team/role user-derived budget vs. today's real token usage."""
    def _q():
        with get_conn() as conn:
            scoped = principal.scope != "platform" and principal.tenant_id
            tenant_clause = " AND tenant_id=%s" if scoped else ""
            tenant_params = [principal.tenant_id] if scoped else []
            roles = conn.execute(
                f"""
                SELECT tenant_id, role_id, capabilities
                FROM roles
                WHERE 1=1 {tenant_clause}
                ORDER BY tenant_id, role_id
                """,
                tenant_params,
            ).fetchall()
            assignments = conn.execute(
                f"""
                SELECT tenant_id, lower(user_email) AS user_email, team_id, role_id
                FROM user_assignments
                WHERE 1=1 {tenant_clause}
                ORDER BY tenant_id, team_id, role_id, user_email
                """,
                tenant_params,
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
                    tenant_params,
                ).fetchall()
            return [dict(r) for r in roles], [dict(r) for r in assignments], [dict(r) for r in usage_rows], chat_table

    roles, assignments, usage_rows, chat_table = await run_db(_q)
    _, _, _, days_in_month = _month_bounds(None)
    hierarchy = build_user_budget_hierarchy(assignments, roles, days_in_month=days_in_month)
    usage_map = {(r["tenant_id"], r["role_id"]): int(r["tokens"] or 0) for r in usage_rows}
    out = []
    for (tenant, team, role), budget in sorted(hierarchy["tenant_team_role_budget_monthly"].items()):
        if budget <= 0:
            continue
        used = usage_map.get((tenant, role), 0) if chat_table else None
        pct = _pct(used or 0, budget) if used is not None else None
        out.append({
            "team": f"{tenant}/{team}/{role}",
            "tenant_id": tenant,
            "team_id": team,
            "role_id": role,
            "budget_tokens": budget,
            "spent_tokens": used,
            "remaining_tokens": max(0, budget - used) if used is not None else None,
            "utilization_pct": pct,
            "budget_usd": None,
            "spent_usd": None,
            "budget_source": "sum_of_user_monthly_budgets",
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
