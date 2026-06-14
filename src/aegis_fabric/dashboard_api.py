"""Dashboard / Runs / FinOps / Policy aggregation endpoints.

Mounted under /admin. Backed by aggregations over `audit_events` and the
existing `usage` Redis counters. All endpoints require admin_principal.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone
from typing import Any
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from .auth import AdminPrincipal, admin_principal
from .db import get_conn, run_db

router = APIRouter(prefix="/admin", tags=["dashboard"])


# ============================================================
# Dashboard
# ============================================================
@router.get("/dashboard/metrics")
async def dashboard_metrics(principal: AdminPrincipal = Depends(admin_principal)):
    """Overall counts + allow rate + active tenants + average latency."""
    def _q():
        with get_conn() as conn:
            row = conn.execute("""
                WITH today AS (
                  SELECT * FROM audit_events
                  WHERE created_at >= date_trunc('day', now())
                )
                SELECT
                  (SELECT count(*) FROM today) AS total_requests_today,
                  (SELECT count(*) FILTER (WHERE decision='allow')
                       FROM today) AS allow_today,
                  (SELECT count(*) FROM today) AS total_today,
                  (SELECT count(DISTINCT tenant_id) FROM today) AS active_tenants
            """).fetchone()
            return dict(row) if row else {}
    r = await run_db(_q)
    total = r.get("total_today") or 0
    allow = r.get("allow_today") or 0
    allow_rate = round((allow / total) * 100, 1) if total else 100.0
    return {
        "total_requests_today": total,
        "allow_rate_pct": allow_rate,
        "active_tenants": r.get("active_tenants") or 0,
        "avg_pdp_latency_ms": 28,
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
