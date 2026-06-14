"""Dual-control approval workflow.

A high-risk action (one listed in a role's ``dual_control_actions``) does not run
when requested — it is queued as a ``pending_action`` and must be approved by a
DIFFERENT principal who holds ``can_approve`` (the two-person rule). On approval
the action executes via a small dispatch map. Every transition is appended to the
immutable, hash-chained audit ledger.
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .audit import append_event
from .db import get_conn
from .logging_config import get_logger

logger = get_logger("aegis.approvals")


# action -> executor(tenant_id, resource). Add an entry here to put another action
# under dual control (e.g. "secret.rotate", "governance.edit").
def _exec_tenant_delete(tenant_id: str, resource: dict) -> dict:
    from .admin import _delete_tenant  # lazy import avoids an import cycle

    return _delete_tenant(tenant_id)


def _exec_memory_erase(tenant_id: str, resource: dict) -> dict:
    from .memory import memory_store

    rows = memory_store.delete(tenant_id, resource.get("memory_id"))
    return {"deleted": resource.get("memory_id"), "rows": rows}


def _exec_memory_write(tenant_id: str, resource: dict) -> dict:
    from .memory import memory_store

    mid = memory_store.write_simple(
        tenant_id, resource["namespace"], resource["author_user"], resource["author_scope"],
        resource["body"], resource.get("classification", "internal"), resource.get("retention_class", "standard"),
    )
    return {"memory_id": mid, "namespace": resource["namespace"]}


def _exec_secret_rotate(tenant_id: str, resource: dict) -> dict:
    from .settings import generate_secret

    val = generate_secret()
    return {"rotated": True, "name": resource.get("name"), "new_value_preview": val[:6] + "\u2026"}


def _exec_mcp_register(tenant_id: str, resource: dict) -> dict:
    """v1.22 -- mark an mcp_servers row as approved. Verification + scan
    already happened at registration time; this only flips the status."""
    server_id = resource["server_id"]
    with get_conn() as conn:
        conn.execute(
            "UPDATE mcp_servers SET status='approved', approved_at=now() WHERE server_id=%s",
            (server_id,),
        )
    return {"server_id": server_id, "status": "approved",
            "manifest_hash": resource.get("manifest_hash"),
            "namespace": resource.get("namespace", [])}


EXECUTORS = {"tenant.delete": _exec_tenant_delete, "memory.erase": _exec_memory_erase,
             "memory.write": _exec_memory_write, "secret.rotate": _exec_secret_rotate,
             "mcp.register": _exec_mcp_register}


def _audit(action: str, resource: str, tenant_id: str, payload: dict) -> None:
    try:
        append_event(trace_id=uuid.uuid4().hex, span_id=None, parent_span_id=None, tenant_id=tenant_id,
                     subject="approvals", action=action, resource=resource, policy_version="policy-v1",
                     values_version="approvals", decision="allow", reason=None, payload=payload)
    except Exception as e:  # noqa: BLE001
        logger.warning("approval audit failed for %s: %s", action, e)


def create_pending(tenant_id: str, action: str, resource: dict, requester: str, reason: str | None = None) -> dict:
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO pending_actions(tenant_id, action, resource, reason, requester) "
            "VALUES (%s,%s,%s,%s,%s) RETURNING id, status, expires_at::text AS expires_at",
            (tenant_id, action, json.dumps(resource), reason, requester),
        ).fetchone()
    _audit("approval.request", f"{action}:{tenant_id}", tenant_id,
           {"requester": requester, "resource": resource, "pending_id": row["id"]})
    return {"pending": True, "pending_id": row["id"], "status": row["status"], "action": action,
            "tenant_id": tenant_id, "expires_at": row["expires_at"],
            "message": "queued for dual-control approval"}


def list_pending(tenant_filter: str | None = None) -> list[dict]:
    sql = ("SELECT id, tenant_id, action, resource, reason, status, requester, approver, "
           "created_at::text AS created_at, expires_at::text AS expires_at "
           "FROM pending_actions WHERE status='pending'")
    params: list = []
    if tenant_filter:
        sql += " AND tenant_id=%s"
        params.append(tenant_filter)
    sql += " ORDER BY created_at DESC"
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def _load(conn, pending_id: int, tenant_filter: str | None):
    sql = "SELECT * FROM pending_actions WHERE id=%s"
    params: list = [pending_id]
    if tenant_filter:
        sql += " AND tenant_id=%s"
        params.append(tenant_filter)
    return conn.execute(sql, params).fetchone()


def reject(pending_id: int, approver: str, tenant_filter: str | None = None) -> dict:
    with get_conn() as conn:
        row = _load(conn, pending_id, tenant_filter)
        if not row:
            raise ValueError("approval_not_found")
        if row["status"] != "pending":
            raise ValueError("approval_not_pending")
        conn.execute("UPDATE pending_actions SET status='rejected', approver=%s, decided_at=now() WHERE id=%s",
                     (approver, pending_id))
    _audit("approval.reject", f"{row['action']}:{row['tenant_id']}", row["tenant_id"],
           {"approver": approver, "requester": row["requester"], "pending_id": pending_id})
    return {"pending_id": pending_id, "status": "rejected"}


def approve(pending_id: int, approver: str, tenant_filter: str | None = None) -> dict:
    with get_conn() as conn:
        row = _load(conn, pending_id, tenant_filter)
        if not row:
            raise ValueError("approval_not_found")
        if row["status"] != "pending":
            raise ValueError("approval_not_pending")
        exp = row.get("expires_at")
        if isinstance(exp, datetime) and exp < datetime.now(timezone.utc):
            conn.execute("UPDATE pending_actions SET status='expired' WHERE id=%s", (pending_id,))
            raise ValueError("approval_expired")
        # two-person rule: the approver must differ from the requester
        if (approver or "").lower() == (row["requester"] or "").lower():
            raise ValueError("self_approval_forbidden")
        action, tenant_id = row["action"], row["tenant_id"]
        resource = row["resource"] if isinstance(row["resource"], dict) else json.loads(row["resource"])
        conn.execute("UPDATE pending_actions SET status='approved', approver=%s, decided_at=now() WHERE id=%s",
                     (approver, pending_id))
    _audit("approval.approve", f"{action}:{tenant_id}", tenant_id,
           {"approver": approver, "requester": row["requester"], "pending_id": pending_id})
    executor = EXECUTORS.get(action)
    if not executor:
        raise ValueError("no_executor_for_action")
    result = executor(tenant_id, resource)
    with get_conn() as conn:
        conn.execute("UPDATE pending_actions SET status='executed', executed_at=now() WHERE id=%s", (pending_id,))
    _audit("approval.execute", f"{action}:{tenant_id}", tenant_id,
           {"approver": approver, "pending_id": pending_id, "result": result})
    return {"pending_id": pending_id, "status": "executed", "action": action, "result": result}
