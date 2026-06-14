"""Turn feedback storage (PAI slice 3, v1.21).

A binary thumbs-up/down + optional free-text note per assistant turn, anchored
on the audit trace_id. Backs the Chat thumbs widget and the Audit "low-rated
turns" panel; aggregates per-skill for the per-skill VERIFY trend line.

All access goes through db.with_tenant_scope() so RLS (v1.20 BR-ISO-05) keeps
feedback strictly tenant-isolated even if upper layers slip.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .db import with_tenant_scope


@dataclass
class Feedback:
    trace_id: str
    rating: int                # -1 or +1
    note: str | None = None
    skill_id: str | None = None


def record(tenant_id: str, principal: str, fb: Feedback) -> int:
    """Insert one feedback row. Returns the new row id."""
    if fb.rating not in (-1, 1):
        raise ValueError("rating must be -1 or 1")
    with with_tenant_scope(tenant_id) as conn:
        row = conn.execute(
            "INSERT INTO turn_feedback(trace_id, tenant_id, principal, skill_id, rating, note) "
            "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
            (fb.trace_id, tenant_id, principal, fb.skill_id, fb.rating, fb.note),
        ).fetchone()
    return int(row["id"])


def list_low_rated(tenant_id: str, limit: int = 50) -> list[dict[str, Any]]:
    """Return the most recent thumbs-down turns for the tenant, ordered newest first."""
    with with_tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            "SELECT id, trace_id, principal, skill_id, rating, note, created_at "
            "FROM turn_feedback WHERE tenant_id = %s AND rating = -1 "
            "ORDER BY created_at DESC LIMIT %s",
            (tenant_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def skill_summary(tenant_id: str) -> list[dict[str, Any]]:
    """Per-skill rolling counts of ups/downs, used by the per-skill VERIFY trend."""
    with with_tenant_scope(tenant_id) as conn:
        rows = conn.execute(
            "SELECT skill_id, "
            "       SUM(CASE WHEN rating = 1 THEN 1 ELSE 0 END) AS ups, "
            "       SUM(CASE WHEN rating = -1 THEN 1 ELSE 0 END) AS downs, "
            "       COUNT(*) AS total "
            "FROM turn_feedback WHERE tenant_id = %s AND skill_id IS NOT NULL "
            "GROUP BY skill_id ORDER BY downs DESC, total DESC",
            (tenant_id,),
        ).fetchall()
    return [dict(r) for r in rows]
