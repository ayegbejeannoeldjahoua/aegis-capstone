"""Best-effort operational metrics for the governance dashboard.

The audit ledger keeps encrypted evidence. This module captures only narrow,
non-sensitive counters and timings needed for the dashboard: no prompts,
answers, document bodies, credentials, or decrypted audit payloads.
"""
from __future__ import annotations

import json
import threading
import time
import uuid
from contextvars import ContextVar
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from .auth import Subject
from .db import get_conn
from .logging_config import get_logger

logger = get_logger("aegis.operational_metrics")

_current: ContextVar["ChatMetrics | None"] = ContextVar("aegis_chat_metrics", default=None)
_active_lock = threading.Lock()
_active_requests = 0


@dataclass
class StageMetric:
    stage: str
    duration_ms: float
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class ChatMetrics:
    tenant_id: str
    subject: str
    role_id: str
    skill_id: str
    started_monotonic: float
    started_at: datetime
    trace_id: str = field(default_factory=lambda: f"pending-{uuid.uuid4().hex}")
    policy_decision_count: int = 0
    policy_allow_count: int = 0
    policy_deny_count: int = 0
    retrieval_calls: int = 0
    retrieved_docs: int = 0
    zero_result_retrievals: int = 0
    pii_redactions_applied: int = 0
    prompt_injection_findings: int = 0
    cross_tenant_leakage_alerts: int = 0
    budget_refusal: bool = False
    model_provider_errors: int = 0
    tokens_total: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    estimated_cost_usd: float | None = None
    cost_instrumented: bool = False
    stages: list[StageMetric] = field(default_factory=list)


def _inc_active(delta: int) -> None:
    global _active_requests
    with _active_lock:
        _active_requests = max(0, _active_requests + delta)


def active_requests() -> int:
    with _active_lock:
        return _active_requests


def begin_chat_turn(subject: Subject, skill_id: str):
    metrics = ChatMetrics(
        tenant_id=subject.tenant_id,
        subject=subject.email,
        role_id=subject.role,
        skill_id=skill_id,
        started_monotonic=time.perf_counter(),
        started_at=datetime.now(timezone.utc),
    )
    token = _current.set(metrics)
    _inc_active(1)
    return token


def reset_chat_turn(token) -> None:
    _current.reset(token)
    _inc_active(-1)


def set_trace_id(trace_id: str | None) -> None:
    metrics = _current.get()
    if metrics and trace_id:
        metrics.trace_id = trace_id


def current_trace_id() -> str | None:
    metrics = _current.get()
    return metrics.trace_id if metrics else None


def _clean_metadata(metadata: dict[str, Any] | None) -> dict[str, Any]:
    if not metadata:
        return {}
    out: dict[str, Any] = {}
    for key, value in metadata.items():
        if value is None:
            continue
        if isinstance(value, (str, int, float, bool)):
            out[key] = value
        elif isinstance(value, (list, tuple)):
            out[key] = [x for x in value if isinstance(x, (str, int, float, bool))]
        elif isinstance(value, dict):
            out[key] = {str(k): v for k, v in value.items() if isinstance(v, (str, int, float, bool))}
        else:
            out[key] = str(value)
    return out


def record_stage(stage: str, duration_ms: float, metadata: dict[str, Any] | None = None) -> None:
    metrics = _current.get()
    if not metrics:
        return
    metrics.stages.append(StageMetric(stage=stage, duration_ms=max(0.0, duration_ms), metadata=_clean_metadata(metadata)))


def record_policy_decision(duration_ms: float, decision: str, action: str, reasons: list[str] | None = None) -> None:
    metrics = _current.get()
    if not metrics:
        return
    metrics.policy_decision_count += 1
    if decision == "allow":
        metrics.policy_allow_count += 1
    else:
        metrics.policy_deny_count += 1
    record_stage("pdp", duration_ms, {"decision": decision, "action": action, "reason": ";".join(reasons or [])})


def record_retrieval(duration_ms: float, tenant_id: str, namespace: str, rows: list[dict]) -> None:
    metrics = _current.get()
    if not metrics:
        return
    count = len(rows or [])
    class_counts: dict[str, int] = {}
    leakage = 0
    for row in rows or []:
        cls = str(row.get("classification") or "unknown")
        class_counts[cls] = class_counts.get(cls, 0) + 1
        if row.get("tenant_id") and row.get("tenant_id") != tenant_id:
            leakage += 1
    metrics.retrieval_calls += 1
    metrics.retrieved_docs += count
    metrics.zero_result_retrievals += 1 if count == 0 else 0
    metrics.cross_tenant_leakage_alerts += leakage
    record_stage(
        "retrieval",
        duration_ms,
        {
            "namespace": namespace,
            "docs": count,
            "zero_result": count == 0,
            "classification_counts": class_counts,
            "cross_tenant_leakage_alerts": leakage,
        },
    )


def record_pii_inspection(duration_ms: float, redactions: int) -> None:
    metrics = _current.get()
    if not metrics:
        return
    metrics.pii_redactions_applied += max(0, int(redactions or 0))
    record_stage("pii_inspection", duration_ms, {"redactions": max(0, int(redactions or 0))})


def record_security_findings(duration_ms: float, findings: list[Any]) -> None:
    metrics = _current.get()
    if not metrics:
        return
    injection_count = 0
    for finding in findings or []:
        finding_id = getattr(finding, "finding_id", "") or ""
        reason = getattr(finding, "reason", "") or ""
        if "SEC-injection" in finding_id or "prompt injection" in reason:
            injection_count += 1
    metrics.prompt_injection_findings += injection_count
    record_stage("security_inspection", duration_ms, {"findings": len(findings or []), "prompt_injection": injection_count})


def record_model_call(duration_ms: float, provider: str, model: str, usage: dict[str, Any] | None) -> None:
    metrics = _current.get()
    if not metrics:
        return
    usage = usage or {}
    prompt_tokens = int(usage.get("prompt_tokens") or usage.get("input_tokens") or 0)
    completion_tokens = int(usage.get("completion_tokens") or usage.get("output_tokens") or 0)
    total_tokens = int(usage.get("total_tokens") or (prompt_tokens + completion_tokens) or 0)
    metrics.prompt_tokens += prompt_tokens
    metrics.completion_tokens += completion_tokens
    metrics.tokens_total += total_tokens
    record_stage(
        "model",
        duration_ms,
        {"provider": provider, "model": model, "tokens_total": total_tokens},
    )


def record_token_usage(tokens: int) -> None:
    metrics = _current.get()
    if not metrics or not tokens:
        return
    # Provider-reported usage is recorded at model-call completion. This
    # fallback is only for providers that return no usage payload.
    if metrics.tokens_total:
        return
    metrics.tokens_total += int(tokens)


def record_model_provider_error(provider: str, model: str, error: str) -> None:
    metrics = _current.get()
    if not metrics:
        return
    metrics.model_provider_errors += 1
    record_stage("model_error", 0.0, {"provider": provider, "model": model, "error": error[:160]})


def record_audit_write(duration_ms: float, action: str, decision: str) -> None:
    record_stage("audit_write", duration_ms, {"action": action, "decision": decision})


def record_isa_verification(duration_ms: float, total: int, met: int) -> None:
    record_stage("isa_verification", duration_ms, {"total": total, "met": met})


def record_finops_write(duration_ms: float, tokens: int) -> None:
    record_stage("finops_write", duration_ms, {"tokens": int(tokens or 0)})


def mark_budget_refusal(reason: str | None = None) -> None:
    metrics = _current.get()
    if metrics:
        metrics.budget_refusal = True
        record_stage("finops_budget_refusal", 0.0, {"reason": reason or "token_budget_exceeded"})


def _status_from_error(status_code: int | None, detail: Any) -> tuple[str, str | None, str | None, bool]:
    text = json.dumps(detail) if isinstance(detail, (dict, list)) else str(detail or "")
    budget = "token_budget_exceeded" in text or "daily_quota_exceeded" in text
    if status_code in (403, 429):
        return "refused", f"http_{status_code}", text[:240], budget
    if status_code and status_code >= 400:
        return "error", f"http_{status_code}", text[:240], budget
    return "error", "exception", text[:240], budget


def snapshot(status: str = "success", error_type: str | None = None, refusal_reason: str | None = None) -> dict[str, Any] | None:
    metrics = _current.get()
    if not metrics:
        return None
    ended_at = datetime.now(timezone.utc)
    if metrics.trace_id.startswith("pending-"):
        metrics.trace_id = f"missing-{uuid.uuid4().hex}"
    return {
        "trace_id": metrics.trace_id,
        "tenant_id": metrics.tenant_id,
        "subject": metrics.subject,
        "role_id": metrics.role_id,
        "skill_id": metrics.skill_id,
        "status": status,
        "error_type": error_type,
        "refusal_reason": refusal_reason,
        "started_at": metrics.started_at,
        "ended_at": ended_at,
        "e2e_latency_ms": (time.perf_counter() - metrics.started_monotonic) * 1000.0,
        "tokens_total": metrics.tokens_total,
        "prompt_tokens": metrics.prompt_tokens,
        "completion_tokens": metrics.completion_tokens,
        "estimated_cost_usd": metrics.estimated_cost_usd,
        "cost_instrumented": metrics.cost_instrumented,
        "policy_decision_count": metrics.policy_decision_count,
        "policy_allow_count": metrics.policy_allow_count,
        "policy_deny_count": metrics.policy_deny_count,
        "retrieval_calls": metrics.retrieval_calls,
        "retrieved_docs": metrics.retrieved_docs,
        "zero_result_retrievals": metrics.zero_result_retrievals,
        "pii_redactions_applied": metrics.pii_redactions_applied,
        "prompt_injection_findings": metrics.prompt_injection_findings,
        "cross_tenant_leakage_alerts": metrics.cross_tenant_leakage_alerts,
        "budget_refusal": metrics.budget_refusal,
        "model_provider_errors": metrics.model_provider_errors,
        "stages": [stage.__dict__ for stage in metrics.stages],
    }


def error_snapshot(status_code: int | None, detail: Any) -> dict[str, Any] | None:
    status, error_type, reason, budget = _status_from_error(status_code, detail)
    if budget:
        mark_budget_refusal(reason)
    return snapshot(status=status, error_type=error_type, refusal_reason=reason)


def exception_snapshot(exc: Exception) -> dict[str, Any] | None:
    return snapshot(status="error", error_type=exc.__class__.__name__, refusal_reason=str(exc)[:240])


def _json_dict(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except Exception:
            return {}
    return {}


def _model_stage(data: dict[str, Any]) -> dict[str, Any]:
    for stage in data.get("stages") or []:
        if stage.get("stage") == "model":
            return _json_dict(stage.get("metadata"))
    for stage in data.get("stages") or []:
        if stage.get("stage") == "model_error":
            return _json_dict(stage.get("metadata"))
    return {}


def _budget_profile(capabilities: dict[str, Any] | None) -> dict[str, Any]:
    caps = _json_dict(capabilities)
    return {
        key: caps.get(key)
        for key in (
            "token_budget_per_day",
            "daily_request_quota",
            "rate_limit_per_minute",
            "max_concurrent_requests",
        )
        if caps.get(key) not in (None, "")
    }


def finops_event_payload(
    data: dict[str, Any],
    capabilities: dict[str, Any] | str | None = None,
    used_tokens_today: int | None = None,
) -> dict[str, Any]:
    """Build the non-sensitive FinOps event row for a persisted chat snapshot."""
    model_meta = _model_stage(data)
    provider = model_meta.get("provider")
    model = model_meta.get("model")
    reached_model = bool(model_meta and data.get("status") != "refused")
    budget_profile = _budget_profile(_json_dict(capabilities))
    token_budget = budget_profile.get("token_budget_per_day")
    try:
        token_budget = int(token_budget) if token_budget not in (None, "") else None
    except (TypeError, ValueError):
        token_budget = None

    budget_refusal = bool(data.get("budget_refusal"))
    status = str(data.get("status") or "unknown")
    model_failed = bool(data.get("model_provider_errors")) and status != "success"

    if budget_refusal:
        event_status = "refused_budget"
        decision = "deny"
    elif model_failed:
        event_status = "failed_provider"
        decision = "allow" if token_budget else "skipped"
    elif status == "success" and reached_model and not data.get("tokens_total") and data.get("estimated_cost_usd") is None:
        event_status = "unmetered"
        decision = "allow" if token_budget else "unmetered"
    elif status == "success":
        event_status = "success"
        decision = "allow" if token_budget else "skipped"
    else:
        event_status = "unknown"
        decision = "allow" if token_budget else "skipped"

    remaining_tokens = None
    if token_budget is not None and used_tokens_today is not None:
        remaining_tokens = max(0, token_budget - int(used_tokens_today or 0))

    return {
        "created_at": data.get("ended_at") or data.get("started_at"),
        "trace_id": data.get("trace_id"),
        "request_id": None,
        "tenant_id": data.get("tenant_id"),
        "user_email": data.get("subject"),
        "role": data.get("role_id"),
        "action": "chat.turn",
        "decision": decision,
        "provider": provider,
        "model": model,
        "input_tokens": int(data.get("prompt_tokens") or 0) if data.get("prompt_tokens") is not None else None,
        "output_tokens": int(data.get("completion_tokens") or 0) if data.get("completion_tokens") is not None else None,
        "total_tokens": int(data.get("tokens_total") or 0) if data.get("tokens_total") is not None else None,
        "estimated_cost_usd": data.get("estimated_cost_usd"),
        "budget_limit_usd": None,
        "budget_remaining_usd": None,
        "budget_limit_tokens": token_budget,
        "budget_remaining_tokens": remaining_tokens,
        "budget_profile": budget_profile,
        "reason": data.get("refusal_reason") or data.get("error_type"),
        "reached_model": reached_model,
        "blocked_before_model": not reached_model and status != "success",
        "status": event_status,
        "metadata": {
            "skill_id": data.get("skill_id"),
            "chat_status": status,
            "error_type": data.get("error_type"),
            "cost_instrumented": bool(data.get("cost_instrumented")),
            "model_provider_errors": int(data.get("model_provider_errors") or 0),
            "policy_decision_count": int(data.get("policy_decision_count") or 0),
            "policy_allow_count": int(data.get("policy_allow_count") or 0),
            "policy_deny_count": int(data.get("policy_deny_count") or 0),
        },
    }


def persist_snapshot(data: dict[str, Any] | None) -> None:
    if not data:
        return
    try:
        with get_conn() as conn:
            conn.execute(
                """
                INSERT INTO dashboard_chat_metrics(
                  trace_id, tenant_id, subject, role_id, skill_id, status, error_type, refusal_reason,
                  started_at, ended_at, e2e_latency_ms, tokens_total, prompt_tokens, completion_tokens,
                  estimated_cost_usd, cost_instrumented, policy_decision_count, policy_allow_count,
                  policy_deny_count, retrieval_calls, retrieved_docs, zero_result_retrievals,
                  pii_redactions_applied, prompt_injection_findings, cross_tenant_leakage_alerts,
                  budget_refusal, model_provider_errors
                )
                VALUES (
                  %(trace_id)s, %(tenant_id)s, %(subject)s, %(role_id)s, %(skill_id)s, %(status)s,
                  %(error_type)s, %(refusal_reason)s, %(started_at)s, %(ended_at)s, %(e2e_latency_ms)s,
                  %(tokens_total)s, %(prompt_tokens)s, %(completion_tokens)s, %(estimated_cost_usd)s,
                  %(cost_instrumented)s, %(policy_decision_count)s, %(policy_allow_count)s,
                  %(policy_deny_count)s, %(retrieval_calls)s, %(retrieved_docs)s,
                  %(zero_result_retrievals)s, %(pii_redactions_applied)s,
                  %(prompt_injection_findings)s, %(cross_tenant_leakage_alerts)s,
                  %(budget_refusal)s, %(model_provider_errors)s
                )
                ON CONFLICT (trace_id) DO UPDATE SET
                  tenant_id=EXCLUDED.tenant_id,
                  subject=EXCLUDED.subject,
                  role_id=EXCLUDED.role_id,
                  skill_id=EXCLUDED.skill_id,
                  status=EXCLUDED.status,
                  error_type=EXCLUDED.error_type,
                  refusal_reason=EXCLUDED.refusal_reason,
                  started_at=EXCLUDED.started_at,
                  ended_at=EXCLUDED.ended_at,
                  e2e_latency_ms=EXCLUDED.e2e_latency_ms,
                  tokens_total=EXCLUDED.tokens_total,
                  prompt_tokens=EXCLUDED.prompt_tokens,
                  completion_tokens=EXCLUDED.completion_tokens,
                  estimated_cost_usd=EXCLUDED.estimated_cost_usd,
                  cost_instrumented=EXCLUDED.cost_instrumented,
                  policy_decision_count=EXCLUDED.policy_decision_count,
                  policy_allow_count=EXCLUDED.policy_allow_count,
                  policy_deny_count=EXCLUDED.policy_deny_count,
                  retrieval_calls=EXCLUDED.retrieval_calls,
                  retrieved_docs=EXCLUDED.retrieved_docs,
                  zero_result_retrievals=EXCLUDED.zero_result_retrievals,
                  pii_redactions_applied=EXCLUDED.pii_redactions_applied,
                  prompt_injection_findings=EXCLUDED.prompt_injection_findings,
                  cross_tenant_leakage_alerts=EXCLUDED.cross_tenant_leakage_alerts,
                  budget_refusal=EXCLUDED.budget_refusal,
                  model_provider_errors=EXCLUDED.model_provider_errors
                """,
                data,
            )
            conn.execute("DELETE FROM dashboard_stage_metrics WHERE trace_id=%s", (data["trace_id"],))
            for stage in data.get("stages", []):
                conn.execute(
                    "INSERT INTO dashboard_stage_metrics(trace_id, tenant_id, stage, duration_ms, metadata) "
                    "VALUES (%s,%s,%s,%s,%s::jsonb)",
                    (
                        data["trace_id"],
                        data["tenant_id"],
                        stage["stage"],
                        stage["duration_ms"],
                        json.dumps(stage.get("metadata") or {}, sort_keys=True),
                    ),
                )
            has_finops_events = bool(conn.execute("SELECT to_regclass('public.finops_events') AS t").fetchone()["t"])
            if has_finops_events:
                role = conn.execute(
                    "SELECT capabilities FROM roles WHERE tenant_id=%s AND role_id=%s",
                    (data.get("tenant_id"), data.get("role_id")),
                ).fetchone()
                capabilities = role["capabilities"] if role else {}
                used_tokens_today = conn.execute(
                    """
                    SELECT COALESCE(sum(tokens_total), 0)::bigint AS tokens
                    FROM dashboard_chat_metrics
                    WHERE tenant_id=%s AND role_id=%s AND started_at >= date_trunc('day', now())
                    """,
                    (data.get("tenant_id"), data.get("role_id")),
                ).fetchone()["tokens"]
                event = finops_event_payload(data, capabilities, int(used_tokens_today or 0))
                conn.execute(
                    """
                    INSERT INTO finops_events(
                      created_at, trace_id, request_id, tenant_id, user_email, role, action,
                      decision, provider, model, input_tokens, output_tokens, total_tokens,
                      estimated_cost_usd, budget_limit_usd, budget_remaining_usd,
                      budget_limit_tokens, budget_remaining_tokens, budget_profile, reason,
                      reached_model, blocked_before_model, status, metadata
                    )
                    VALUES (
                      %(created_at)s, %(trace_id)s, %(request_id)s, %(tenant_id)s, %(user_email)s,
                      %(role)s, %(action)s, %(decision)s, %(provider)s, %(model)s,
                      %(input_tokens)s, %(output_tokens)s, %(total_tokens)s,
                      %(estimated_cost_usd)s, %(budget_limit_usd)s, %(budget_remaining_usd)s,
                      %(budget_limit_tokens)s, %(budget_remaining_tokens)s,
                      %(budget_profile)s::jsonb, %(reason)s, %(reached_model)s,
                      %(blocked_before_model)s, %(status)s, %(metadata)s::jsonb
                    )
                    ON CONFLICT (trace_id, action) DO UPDATE SET
                      created_at=EXCLUDED.created_at,
                      request_id=EXCLUDED.request_id,
                      tenant_id=EXCLUDED.tenant_id,
                      user_email=EXCLUDED.user_email,
                      role=EXCLUDED.role,
                      decision=EXCLUDED.decision,
                      provider=EXCLUDED.provider,
                      model=EXCLUDED.model,
                      input_tokens=EXCLUDED.input_tokens,
                      output_tokens=EXCLUDED.output_tokens,
                      total_tokens=EXCLUDED.total_tokens,
                      estimated_cost_usd=EXCLUDED.estimated_cost_usd,
                      budget_limit_usd=EXCLUDED.budget_limit_usd,
                      budget_remaining_usd=EXCLUDED.budget_remaining_usd,
                      budget_limit_tokens=EXCLUDED.budget_limit_tokens,
                      budget_remaining_tokens=EXCLUDED.budget_remaining_tokens,
                      budget_profile=EXCLUDED.budget_profile,
                      reason=EXCLUDED.reason,
                      reached_model=EXCLUDED.reached_model,
                      blocked_before_model=EXCLUDED.blocked_before_model,
                      status=EXCLUDED.status,
                      metadata=EXCLUDED.metadata
                    """,
                    {
                        **event,
                        "budget_profile": json.dumps(event["budget_profile"], sort_keys=True),
                        "metadata": json.dumps(event["metadata"], sort_keys=True),
                    },
                )
    except Exception as exc:  # noqa: BLE001 - metrics must never break chat.
        logger.warning("dashboard metrics persist failed: %s", exc)
