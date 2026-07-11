from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .db import get_conn


def month_bounds(month_key: str | None = None) -> tuple[datetime, datetime, str, int]:
    import calendar

    now = datetime.now(timezone.utc)
    if month_key:
        start = datetime.strptime(month_key, "%Y-%m").replace(tzinfo=timezone.utc)
    else:
        start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(year=start.year + 1, month=1) if start.month == 12 else start.replace(month=start.month + 1)
    return start, end, start.strftime("%Y-%m"), calendar.monthrange(start.year, start.month)[1]


def _table_exists(conn, table: str) -> bool:
    return bool(conn.execute("SELECT to_regclass(%s) AS t", (f"public.{table}",)).fetchone()["t"])


def _columns(conn, table: str) -> set[str]:
    return {
        row["column_name"]
        for row in conn.execute(
            """
            SELECT column_name
            FROM information_schema.columns
            WHERE table_schema='public' AND table_name=%s
            """,
            (table,),
        ).fetchall()
    }


def _scope(principal, tenant_id: str | None) -> tuple[str, list[Any]]:
    if getattr(principal, "scope", None) != "platform" and getattr(principal, "tenant_id", None):
        return " AND tenant_id=%s", [principal.tenant_id]
    if tenant_id:
        return " AND tenant_id=%s", [tenant_id]
    return "", []


def _assignment_map(assignments: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    return {
        (row.get("tenant_id"), str(row.get("user_email") or "").lower()): row
        for row in assignments
    }


def _source_key(row: dict[str, Any], fallback: str) -> str:
    for key in ("trace_id", "request_id", "message_id", "conversation_id"):
        value = row.get(key)
        if value:
            return f"{key}:{value}"
    return fallback


def _token_source(row: dict[str, Any]) -> str:
    source = row.get("token_source")
    if source:
        return str(source)
    if int(row.get("input_tokens") or 0) or int(row.get("output_tokens") or 0):
        return "provider"
    if int(row.get("total_tokens") or 0):
        return "estimated"
    return "unmetered" if row.get("reached_model") or row.get("provider") or row.get("model") else "missing"


def _merge_event(events: dict[str, dict[str, Any]], event: dict[str, Any], priority: int) -> None:
    key = _source_key(event, f"{event.get('source_table')}:{event.get('id') or len(events)}")
    current = events.get(key)
    if current is None:
        events[key] = {**event, "_priority": priority}
        return
    if priority < int(current.get("_priority", 99)):
        current["source_table"] = event.get("source_table")
        current["source_confidence"] = event.get("source_confidence")
        current["_priority"] = priority
    for field in (
        "trace_id", "request_id", "conversation_id", "message_id", "created_at", "tenant_id",
        "team_id", "role", "user_email", "provider", "model", "request_status", "budget_decision",
        "decision", "status", "reason", "estimated_cost_usd", "budget_limit_usd", "budget_remaining_usd",
        "budget_limit_tokens", "budget_remaining_tokens", "budget_profile", "reached_model",
        "blocked_before_model",
    ):
        if not current.get(field) and event.get(field):
            current[field] = event[field]
    for field in ("input_tokens", "output_tokens", "total_tokens"):
        current_value = int(current.get(field) or 0)
        event_value = int(event.get(field) or 0)
        if event_value > current_value:
            current[field] = event_value
    current_source = current.get("token_source")
    event_source = event.get("token_source")
    if current_source in (None, "", "missing", "unmetered") and event_source:
        current["token_source"] = event_source


def load_monthly_activity(
    principal,
    *,
    month_key: str | None = None,
    tenant_id: str | None = None,
    team: str | None = None,
    role: str | None = None,
    user_email: str | None = None,
) -> dict[str, Any]:
    start, end, month, days_in_month = month_bounds(month_key)
    with get_conn() as conn:
        tenant_clause, tenant_params = _scope(principal, tenant_id)
        period_params = [start, end, *tenant_params]
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
        assignments = [dict(row) for row in assignments]
        assignment_by_user = _assignment_map(assignments)

        stage_rows: list[dict[str, Any]] = []
        if _table_exists(conn, "dashboard_stage_metrics"):
            stage_rows = [
                dict(row)
                for row in conn.execute(
                    f"""
                    SELECT trace_id, tenant_id, stage, duration_ms, metadata, created_at
                    FROM dashboard_stage_metrics
                    WHERE created_at >= %s AND created_at < %s {tenant_clause}
                    ORDER BY created_at DESC
                    """,
                    period_params,
                ).fetchall()
            ]
        model_by_trace: dict[str, dict[str, Any]] = {}
        for row in stage_rows:
            if row.get("stage") not in {"model", "model_error"}:
                continue
            metadata = row.get("metadata") or {}
            if isinstance(metadata, str):
                import json

                try:
                    metadata = json.loads(metadata)
                except Exception:
                    metadata = {}
            trace_id = row.get("trace_id")
            if trace_id and trace_id not in model_by_trace:
                model_by_trace[trace_id] = {
                    "provider": metadata.get("provider"),
                    "model": metadata.get("model"),
                }

        events: dict[str, dict[str, Any]] = {}
        source_counts: dict[str, int] = {}

        if _table_exists(conn, "finops_events"):
            cols = _columns(conn, "finops_events")
            def _col(name: str, fallback: str) -> str:
                return name if name in cols else f"{fallback} AS {name}"

            team_expr = _col("team_id", "NULL::text")
            token_source_expr = (
                "token_source"
                if "token_source" in cols
                else """
                CASE
                  WHEN COALESCE(input_tokens, 0) > 0 OR COALESCE(output_tokens, 0) > 0 THEN 'provider'
                  WHEN COALESCE(total_tokens, 0) > 0 THEN 'estimated'
                  ELSE 'unmetered'
                END AS token_source
                """
            )
            estimated_cost_expr = _col("estimated_cost_usd", "NULL::numeric")
            budget_limit_usd_expr = _col("budget_limit_usd", "NULL::numeric")
            budget_remaining_usd_expr = _col("budget_remaining_usd", "NULL::numeric")
            budget_limit_tokens_expr = _col("budget_limit_tokens", "NULL::integer")
            budget_remaining_tokens_expr = _col("budget_remaining_tokens", "NULL::integer")
            budget_profile_expr = _col("budget_profile", "'{}'::jsonb")
            reached_model_expr = _col("reached_model", "FALSE")
            blocked_before_model_expr = _col("blocked_before_model", "FALSE")
            status_expr = _col("status", "'unknown'::text")
            rows = conn.execute(
                f"""
                SELECT id, created_at, trace_id, request_id, tenant_id, user_email, {team_expr},
                       role, decision, provider, model, input_tokens, output_tokens, total_tokens,
                       {token_source_expr}, {estimated_cost_expr}, {budget_limit_usd_expr},
                       {budget_remaining_usd_expr}, {budget_limit_tokens_expr}, {budget_remaining_tokens_expr},
                       {budget_profile_expr}, reason, {reached_model_expr}, {blocked_before_model_expr}, {status_expr}
                FROM finops_events
                WHERE created_at >= %s AND created_at < %s {tenant_clause}
                ORDER BY created_at DESC, id DESC
                """,
                period_params,
            ).fetchall()
            for row in rows:
                row = dict(row)
                assignment = assignment_by_user.get((row.get("tenant_id"), str(row.get("user_email") or "").lower())) or {}
                event = {
                    "id": row.get("id"),
                    "trace_id": row.get("trace_id"),
                    "request_id": row.get("request_id"),
                    "created_at": row.get("created_at"),
                    "month_key": month,
                    "tenant_id": row.get("tenant_id"),
                    "team_id": row.get("team_id") or assignment.get("team_id"),
                    "role": row.get("role") or assignment.get("role_id"),
                    "user_email": row.get("user_email"),
                    "provider": row.get("provider"),
                    "model": row.get("model"),
                    "request_status": row.get("status") or "unknown",
                    "budget_decision": row.get("decision") or "unknown",
                    "status": row.get("status") or "unknown",
                    "decision": row.get("decision") or "unknown",
                    "input_tokens": int(row.get("input_tokens") or 0),
                    "output_tokens": int(row.get("output_tokens") or 0),
                    "total_tokens": int(row.get("total_tokens") or 0),
                    "token_source": _token_source(row),
                    "estimated_cost_usd": row.get("estimated_cost_usd"),
                    "budget_limit_usd": row.get("budget_limit_usd"),
                    "budget_remaining_usd": row.get("budget_remaining_usd"),
                    "budget_limit_tokens": row.get("budget_limit_tokens"),
                    "budget_remaining_tokens": row.get("budget_remaining_tokens"),
                    "budget_profile": row.get("budget_profile") or {},
                    "reached_model": bool(row.get("reached_model")),
                    "blocked_before_model": bool(row.get("blocked_before_model")),
                    "reason": row.get("reason"),
                    "source_table": "finops_events",
                    "source_confidence": "high",
                }
                _merge_event(events, event, 10)
                source_counts["finops_events"] = source_counts.get("finops_events", 0) + 1

        if _table_exists(conn, "dashboard_chat_metrics"):
            rows = conn.execute(
                f"""
                SELECT *
                FROM dashboard_chat_metrics
                WHERE started_at >= %s AND started_at < %s {tenant_clause}
                ORDER BY started_at DESC
                """,
                period_params,
            ).fetchall()
            for row in rows:
                row = dict(row)
                email = str(row.get("subject") or "").lower()
                assignment = assignment_by_user.get((row.get("tenant_id"), email)) or {}
                model_info = model_by_trace.get(row.get("trace_id")) or {}
                budget_refused = bool(row.get("budget_refusal"))
                reached_model = bool(model_info) or int(row.get("tokens_total") or 0) > 0
                token_probe = {
                    "input_tokens": int(row.get("prompt_tokens") or 0),
                    "output_tokens": int(row.get("completion_tokens") or 0),
                    "total_tokens": int(row.get("tokens_total") or 0),
                    "reached_model": reached_model,
                    **model_info,
                }
                event = {
                    "trace_id": row.get("trace_id"),
                    "created_at": row.get("started_at"),
                    "month_key": month,
                    "tenant_id": row.get("tenant_id"),
                    "team_id": assignment.get("team_id"),
                    "role": row.get("role_id") or assignment.get("role_id"),
                    "user_email": row.get("subject"),
                    "provider": model_info.get("provider"),
                    "model": model_info.get("model"),
                    "request_status": "refused_budget" if budget_refused else (row.get("status") or "unknown"),
                    "budget_decision": "deny" if budget_refused else "allow",
                    "status": "refused_budget" if budget_refused else (row.get("status") or "unknown"),
                    "decision": "deny" if budget_refused else "allow",
                    "input_tokens": int(row.get("prompt_tokens") or 0),
                    "output_tokens": int(row.get("completion_tokens") or 0),
                    "total_tokens": int(row.get("tokens_total") or 0),
                    "token_source": _token_source(token_probe),
                    "estimated_cost_usd": row.get("estimated_cost_usd") if row.get("cost_instrumented") else None,
                    "reached_model": reached_model,
                    "blocked_before_model": bool(row.get("status") != "success" and not reached_model),
                    "reason": row.get("refusal_reason") or row.get("error_type"),
                    "source_table": "dashboard_chat_metrics",
                    "source_confidence": "high",
                }
                _merge_event(events, event, 20)
                source_counts["dashboard_chat_metrics"] = source_counts.get("dashboard_chat_metrics", 0) + 1

        if _table_exists(conn, "chat_messages"):
            rows = conn.execute(
                f"""
                SELECT id AS message_id, conversation_id, tenant_id, user_email, trace_id,
                       provider, model, input_tokens, output_tokens, total_tokens, token_source,
                       created_at
                FROM chat_messages
                WHERE role='assistant' AND created_at >= %s AND created_at < %s {tenant_clause}
                ORDER BY created_at DESC
                """,
                period_params,
            ).fetchall()
            for row in rows:
                row = dict(row)
                assignment = assignment_by_user.get((row.get("tenant_id"), str(row.get("user_email") or "").lower())) or {}
                event = {
                    **row,
                    "month_key": month,
                    "team_id": assignment.get("team_id"),
                    "role": assignment.get("role_id"),
                    "request_status": "success",
                    "budget_decision": "unknown",
                    "status": "success",
                    "decision": "unknown",
                    "input_tokens": int(row.get("input_tokens") or 0),
                    "output_tokens": int(row.get("output_tokens") or 0),
                    "total_tokens": int(row.get("total_tokens") or 0),
                    "token_source": _token_source(row),
                    "reached_model": bool(row.get("provider") or row.get("model") or int(row.get("total_tokens") or 0)),
                    "blocked_before_model": False,
                    "source_table": "chat_messages",
                    "source_confidence": "medium",
                }
                _merge_event(events, event, 30)
                source_counts["chat_messages"] = source_counts.get("chat_messages", 0) + 1

        rows = conn.execute(
            f"""
            SELECT trace_id, tenant_id, subject, action, decision, reason, created_at
            FROM audit_events
            WHERE created_at >= %s AND created_at < %s {tenant_clause}
              AND action IN ('response.return', 'model.call')
            ORDER BY created_at DESC, sequence_id DESC
            """,
            period_params,
        ).fetchall()
        seen_audit_traces: set[str] = set()
        for row in rows:
            row = dict(row)
            trace_id = row.get("trace_id")
            if not trace_id or trace_id in seen_audit_traces:
                continue
            seen_audit_traces.add(trace_id)
            assignment = assignment_by_user.get((row.get("tenant_id"), str(row.get("subject") or "").lower())) or {}
            model_info = model_by_trace.get(trace_id) or {}
            event = {
                "trace_id": trace_id,
                "created_at": row.get("created_at"),
                "month_key": month,
                "tenant_id": row.get("tenant_id"),
                "team_id": assignment.get("team_id"),
                "role": assignment.get("role_id"),
                "user_email": row.get("subject"),
                "provider": model_info.get("provider"),
                "model": model_info.get("model"),
                "request_status": "success" if row.get("decision") == "allow" else "refused",
                "budget_decision": "unknown",
                "status": "success" if row.get("decision") == "allow" else "refused",
                "decision": "unknown",
                "input_tokens": 0,
                "output_tokens": 0,
                "total_tokens": 0,
                "token_source": "missing",
                "reached_model": bool(model_info),
                "blocked_before_model": False,
                "reason": row.get("reason"),
                "source_table": "audit_events",
                "source_confidence": "fallback",
            }
            _merge_event(events, event, 40)
            source_counts["audit_events"] = source_counts.get("audit_events", 0) + 1

    out = []
    for event in events.values():
        if tenant_id and event.get("tenant_id") != tenant_id:
            continue
        if team and event.get("team_id") != team:
            continue
        if role and event.get("role") != role:
            continue
        if user_email and event.get("user_email") != user_email:
            continue
        event.pop("_priority", None)
        out.append(event)
    out.sort(key=lambda item: item.get("created_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return {
        "period": {"month": month, "start": start, "end": end, "days_in_month": days_in_month},
        "events": out,
        "roles": [dict(row) for row in roles],
        "assignments": assignments,
        "source_counts": source_counts,
    }
