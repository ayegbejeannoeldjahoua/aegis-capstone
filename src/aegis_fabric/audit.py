from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from .db import get_conn
from .settings import settings

_key: bytes | None = None


def _audit_key() -> bytes:
    global _key
    if _key is None:
        seed = (settings.audit_key or settings.local_master_key).encode()
        _key = hashlib.sha256(seed).digest()
    return _key


def append_event(
    *,
    trace_id: str,
    span_id: str | None,
    parent_span_id: str | None,
    tenant_id: str,
    subject: str,
    action: str,
    resource: str,
    policy_version: str,
    values_version: str,
    decision: str,
    reason: str | None,
    payload: dict,
) -> str:
    aad = f"{trace_id}:{tenant_id}:{subject}:{action}:{resource}"
    plaintext = json.dumps({"ts": datetime.now(timezone.utc).isoformat(), **payload}, sort_keys=True).encode()
    nonce = os.urandom(12)
    ciphertext = AESGCM(_audit_key()).encrypt(nonce, plaintext, aad.encode())
    with get_conn() as conn:
        last_row = conn.execute(
            "SELECT event_hash FROM audit_events ORDER BY sequence_id DESC LIMIT 1"
        ).fetchone()
        prev_hash = last_row["event_hash"] if last_row else None
        h = hashlib.sha256((prev_hash or "GENESIS").encode() + aad.encode() + ciphertext + nonce).hexdigest()
        conn.execute(
            """
            INSERT INTO audit_events(trace_id, span_id, parent_span_id, tenant_id, subject, action, resource,
             policy_version, values_version, decision, reason, ciphertext, nonce, aad, event_hash, prev_hash)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
            """,
            (
                trace_id, span_id, parent_span_id, tenant_id, subject, action, resource,
                policy_version, values_version, decision, reason, ciphertext, nonce, aad, h, prev_hash,
            ),
        )
        return h


def verify_chain(max_rows: int | None = None) -> dict:
    """Re-derive the hash chain. The ledger is global (cross-tenant) by design,
    so this is an operator/admin function. Bounded to avoid loading an
    unbounded table into memory."""
    limit = max_rows or settings.audit_verify_max_rows
    with get_conn() as conn:
        total = conn.execute("SELECT count(*) AS c FROM audit_events").fetchone()["c"]
        rows = conn.execute(
            "SELECT sequence_id, aad, ciphertext, nonce, event_hash, prev_hash "
            "FROM audit_events ORDER BY sequence_id LIMIT %s",
            (limit,),
        ).fetchall()
    prev = None
    for r in rows:
        expected = hashlib.sha256(
            (prev or "GENESIS").encode() + r["aad"].encode() + bytes(r["ciphertext"]) + bytes(r["nonce"])
        ).hexdigest()
        if expected != r["event_hash"] or r["prev_hash"] != prev:
            return {"ok": False, "failed_sequence_id": r["sequence_id"]}
        prev = r["event_hash"]
    return {"ok": True, "verified": len(rows), "total": total, "truncated": total > len(rows), "last_hash": prev}


def _scope_clauses(tenant_id: str, scope: str, subject_email: str | None) -> tuple[list[str], list]:
    """Translate an audit_scope into SQL filters. 'all' = cross-tenant (platform);
    'own' = the caller's own events within their tenant; everything else = tenant-scoped.
    ('team' falls back to tenant — audit_events carries no team column.)"""
    clauses: list[str] = []
    params: list = []
    if scope != "all":
        clauses.append("tenant_id=%s")
        params.append(tenant_id)
    if scope == "own" and subject_email:
        clauses.append("subject=%s")
        params.append(subject_email)
    return clauses, params


def trace(trace_id: str, tenant_id: str, scope: str = "tenant", subject_email: str | None = None) -> list[dict]:
    """Return events for a trace, filtered by the caller's audit_scope."""
    clauses, params = _scope_clauses(tenant_id, scope, subject_email)
    where = " AND ".join(["trace_id=%s", *clauses])
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT sequence_id, trace_id, tenant_id, subject, action, resource, decision, reason, "
            "event_hash, prev_hash, created_at::text FROM audit_events "
            f"WHERE {where} ORDER BY sequence_id",
            (trace_id, *params),
        ).fetchall()
    return list(rows)


def recent_traces(tenant_id: str, scope: str = "tenant", limit: int = 20) -> list[dict]:
    """Recent trace summaries derived from the audit ledger (id, event count, last
    timestamp, whether any action was denied)."""
    limit = max(1, min(limit, 200))
    clauses, params = _scope_clauses(tenant_id, scope, None)
    where = " AND ".join(clauses) if clauses else "TRUE"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT trace_id, count(*) AS events, max(created_at)::text AS last_at, "
            "max(tenant_id) AS tenant_id, bool_or(decision='deny') AS has_deny "
            f"FROM audit_events WHERE {where} GROUP BY trace_id ORDER BY max(created_at) DESC LIMIT %s",
            (*params, limit),
        ).fetchall()
    return list(rows)


def last(tenant_id: str, scope: str = "tenant", subject_email: str | None = None, limit: int = 20) -> list[dict]:
    """Return recent events, filtered by the caller's audit_scope."""
    limit = max(1, min(limit, 200))
    clauses, params = _scope_clauses(tenant_id, scope, subject_email)
    where = " AND ".join(clauses) if clauses else "TRUE"
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT sequence_id, trace_id, tenant_id, subject, action, resource, decision, reason, "
            "event_hash, created_at::text FROM audit_events "
            f"WHERE {where} ORDER BY sequence_id DESC LIMIT %s",
            (*params, limit),
        ).fetchall()
    return list(rows)
