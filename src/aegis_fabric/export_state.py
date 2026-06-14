"""Export the live application-DB governance state into an idempotent SQL seed, so a
bare-scratch reinstall (fresh volumes / new machine) can be returned to the latest state.

Captures STRUCTURE + GOVERNANCE + ASSIGNMENTS: tenants, teams, role templates, roles
(with full capabilities), values rules, and user assignments. Deliberately EXCLUDES
secrets (no Keycloak credentials) and the `sub` bindings (Keycloak-instance specific —
they re-bind on first login; baking stale subs in is what strands accounts). The result
is replayed by scripts/import-state.sh after a fresh `up` + migrations.

The background exporter (main.py) writes the output of build_seed_sql() to a host-mounted
file (AEGIS_EXPORT_PATH) whenever a governance change is detected, so the on-disk setup file
stays current automatically.
"""
from __future__ import annotations

import datetime as _dt
import json

from .db import get_conn


def _s(v) -> str:
    """SQL string literal (or NULL)."""
    if v is None:
        return "NULL"
    return "'" + str(v).replace("'", "''") + "'"


def _j(v) -> str:
    """SQL jsonb literal from a Python dict/list."""
    return "'" + json.dumps(v or {}, sort_keys=True).replace("'", "''") + "'::jsonb"


def build_seed_sql() -> str:
    """Serialize the current governance state to an idempotent SQL seed string."""
    ts = _dt.datetime.now(_dt.timezone.utc).isoformat()
    out: list[str] = [
        "-- Aegis AI Governance Platform - generated state seed (idempotent; safe to re-apply).",
        f"-- Generated {ts} by export_state.build_seed_sql().",
        "-- Captures tenants/teams/role-templates/roles+capabilities/values/user-assignments.",
        "-- EXCLUDES secrets (Keycloak credentials) and sub bindings (re-bind on first login).",
        "-- Apply after a fresh `up` + migrations: bash scripts/import-state.sh",
        "BEGIN;",
    ]
    with get_conn() as conn:
        for r in conn.execute(
            "SELECT tenant_id, display_name, region FROM tenants ORDER BY tenant_id"
        ).fetchall():
            out.append(
                "INSERT INTO tenants(tenant_id, display_name, region) VALUES "
                f"({_s(r['tenant_id'])}, {_s(r['display_name'])}, {_s(r['region'])}) "
                "ON CONFLICT (tenant_id) DO UPDATE SET "
                "display_name=EXCLUDED.display_name, region=EXCLUDED.region;"
            )
        for r in conn.execute(
            "SELECT template_id, display_name, capabilities FROM role_templates ORDER BY template_id"
        ).fetchall():
            out.append(
                "INSERT INTO role_templates(template_id, display_name, capabilities) VALUES "
                f"({_s(r['template_id'])}, {_s(r['display_name'])}, {_j(r['capabilities'])}) "
                "ON CONFLICT (template_id) DO UPDATE SET "
                "display_name=EXCLUDED.display_name, capabilities=EXCLUDED.capabilities;"
            )
        for r in conn.execute(
            "SELECT tenant_id, team_id, display_name FROM teams ORDER BY tenant_id, team_id"
        ).fetchall():
            out.append(
                "INSERT INTO teams(tenant_id, team_id, display_name) VALUES "
                f"({_s(r['tenant_id'])}, {_s(r['team_id'])}, {_s(r['display_name'])}) "
                "ON CONFLICT (tenant_id, team_id) DO UPDATE SET display_name=EXCLUDED.display_name;"
            )
        for r in conn.execute(
            "SELECT tenant_id, role_id, team_id, template_id, capabilities FROM roles "
            "ORDER BY tenant_id, role_id"
        ).fetchall():
            out.append(
                "INSERT INTO roles(tenant_id, role_id, team_id, template_id, capabilities) VALUES "
                f"({_s(r['tenant_id'])}, {_s(r['role_id'])}, {_s(r['team_id'])}, "
                f"{_s(r['template_id'])}, {_j(r['capabilities'])}) "
                "ON CONFLICT (tenant_id, role_id) DO UPDATE SET team_id=EXCLUDED.team_id, "
                "template_id=EXCLUDED.template_id, capabilities=EXCLUDED.capabilities;"
            )
        for r in conn.execute(
            "SELECT tenant_id, scope_type, scope_id, version, rules FROM values_rules "
            "ORDER BY tenant_id, scope_type, scope_id, version"
        ).fetchall():
            out.append(
                "INSERT INTO values_rules(tenant_id, scope_type, scope_id, version, rules) VALUES "
                f"({_s(r['tenant_id'])}, {_s(r['scope_type'])}, {_s(r['scope_id'])}, "
                f"{_s(r['version'])}, {_j(r['rules'])}) "
                "ON CONFLICT (tenant_id, scope_type, scope_id, version) DO UPDATE SET rules=EXCLUDED.rules;"
            )
        # user assignments: email -> tenant/team/role only (NO sub). No natural unique key, so a
        # guarded insert keeps it idempotent without touching the schema.
        for r in conn.execute(
            "SELECT user_email, tenant_id, team_id, role_id FROM user_assignments "
            "ORDER BY tenant_id, user_email"
        ).fetchall():
            out.append(
                "INSERT INTO user_assignments(user_email, tenant_id, team_id, role_id) "
                f"SELECT {_s(r['user_email'])}, {_s(r['tenant_id'])}, {_s(r['team_id'])}, {_s(r['role_id'])} "
                "WHERE NOT EXISTS (SELECT 1 FROM user_assignments "
                f"WHERE lower(user_email)=lower({_s(r['user_email'])}) AND tenant_id={_s(r['tenant_id'])});"
            )
    out.append("COMMIT;")
    out.append("")
    return "\n".join(out)


def latest_admin_seq() -> int:
    """Max audit sequence_id for admin/governance mutations. A cheap change-detector so the
    background exporter re-writes the seed only when governance actually changed."""
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COALESCE(MAX(sequence_id), 0) AS seq FROM audit_events WHERE action LIKE 'admin.%'"
        ).fetchone()
    return int(row["seq"]) if row else 0
