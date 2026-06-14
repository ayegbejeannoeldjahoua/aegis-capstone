from __future__ import annotations

import hashlib
import json
from pathlib import Path

import yaml

from . import keycloak_admin, rbac
from .db import get_conn
from .logging_config import get_logger

logger = get_logger("aegis.provisioning")

_FIXTURE_CANDIDATES = [
    Path("/app/configs/fixtures/tenant_fixture.yaml"),
    Path("configs/fixtures/tenant_fixture.yaml"),
]


def _fixture_path(path: str | None) -> Path:
    if path:
        return Path(path)
    for p in _FIXTURE_CANDIDATES:
        if p.exists():
            return p
    return _FIXTURE_CANDIDATES[-1]


def _seed_templates(conn) -> None:
    for tid, t in rbac.DEFAULT_TEMPLATES.items():
        conn.execute(
            "INSERT INTO role_templates(template_id, display_name, capabilities) VALUES (%s,%s,%s) "
            "ON CONFLICT (template_id) DO UPDATE SET display_name=EXCLUDED.display_name, capabilities=EXCLUDED.capabilities",
            (tid, t["display_name"], json.dumps(rbac.normalize_caps(t["capabilities"]))),
        )


def _load_values(conn, tenant_id: str, values: dict) -> None:
    scope_keys = {
        "org": lambda v: "org",
        "team": lambda v: v.get("team_id", "team"),
        "role": lambda v: v.get("role_id", "role"),
        "individual": lambda v: v.get("user", "user"),
    }
    for scope_type, id_fn in scope_keys.items():
        block = values.get(scope_type)
        if not block:
            continue
        conn.execute(
            "INSERT INTO values_rules(tenant_id, scope_type, scope_id, version, rules) VALUES (%s,%s,%s,%s,%s) "
            "ON CONFLICT (tenant_id, scope_type, scope_id, version) DO UPDATE SET rules=EXCLUDED.rules",
            (tenant_id, scope_type, id_fn(block), block.get("version", f"{scope_type}-v1"), json.dumps(block)),
        )


def bootstrap(path: str | None = None) -> dict:
    p = _fixture_path(path)
    data = yaml.safe_load(p.read_text())
    with get_conn() as conn:
        _seed_templates(conn)
        for t in data["tenants"]:
            conn.execute(
                "INSERT INTO tenants(tenant_id, display_name, region) VALUES (%s,%s,%s) "
                "ON CONFLICT (tenant_id) DO UPDATE SET display_name=EXCLUDED.display_name, region=EXCLUDED.region",
                (t["tenant_id"], t["display_name"], t.get("region", "AC1")),
            )
            for team in t.get("teams", []):
                conn.execute(
                    "INSERT INTO teams(tenant_id, team_id, display_name) VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                    (t["tenant_id"], team["team_id"], team["display_name"]),
                )
            for role in t.get("roles", []):
                # Instantiate each role from its same-named template's capabilities.
                template_id = role.get("template_id", role["role_id"])
                caps = rbac.template_capabilities(template_id)
                conn.execute(
                    "INSERT INTO roles(tenant_id, role_id, team_id, template_id, capabilities) VALUES (%s,%s,%s,%s,%s) "
                    "ON CONFLICT (tenant_id, role_id) DO UPDATE SET team_id=EXCLUDED.team_id, "
                    "template_id=EXCLUDED.template_id, capabilities=EXCLUDED.capabilities",
                    (t["tenant_id"], role["role_id"], role["team_id"], template_id, json.dumps(caps)),
                )
            if t.get("values"):
                _load_values(conn, t["tenant_id"], t["values"])
            for mem in t.get("memories", []):
                body_hash = hashlib.sha256(mem["body"].encode()).hexdigest()
                exists = conn.execute(
                    "SELECT id FROM memories WHERE tenant_id=%s AND body_hash=%s", (t["tenant_id"], body_hash)
                ).fetchone()
                if not exists:
                    conn.execute(
                        "INSERT INTO memories(tenant_id, namespace, author_user, author_scope, classification, "
                        "retention_class, policy_version, values_version, frontmatter, body, body_hash) "
                        "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                        (t["tenant_id"], mem["namespace"], mem["author_user"], mem["author_scope"],
                         mem.get("classification", "internal"), mem.get("retention_class", "standard"),
                         "policy-v1", "values-v1", json.dumps(mem.get("frontmatter", {})), mem["body"], body_hash),
                    )
        # Seed identity -> tenancy/role assignments (sub bound on first authenticated use).
        for u in data.get("users", []):
            existing = conn.execute(
                "SELECT assignment_id FROM user_assignments WHERE lower(user_email)=lower(%s) AND tenant_id=%s",
                (u["email"], u["tenant_id"]),
            ).fetchone()
            if not existing:
                conn.execute(
                    "INSERT INTO user_assignments(user_email, tenant_id, team_id, role_id) VALUES (%s,%s,%s,%s)",
                    (u["email"], u["tenant_id"], u["team_id"], u["role_id"]),
                )

    # Provision Keycloak logins so the seeded users can actually sign in. Idempotent (409 -> exists)
    # and best-effort: a Keycloak hiccup must never roll back the DB seed above.
    logins: list[dict] = []
    for u in data.get("users", []):
        pw = u.get("password")
        if not pw:
            continue
        try:
            res = keycloak_admin.create_login(
                u["email"], pw,
                first_name=u.get("first_name", ""),
                last_name=u.get("last_name", ""),
            )
            logins.append({"email": u["email"], **{k: res[k] for k in res if k in ("created", "note", "skipped")}})
        except Exception as e:  # noqa: BLE001
            logger.warning("login provisioning failed for %s: %s", u["email"], e)
            logins.append({"email": u["email"], "error": str(e)})

    # Push the freshly-seeded capability map to OPA.
    rbac.sync_opa()

    # Seed default values documents (organization + per-tenant department / team / role).
    # Personal documents are NOT seeded; each user authors their own.
    _seed_values_documents(data)

    logger.info("bootstrap complete for tenants: %s", [t["tenant_id"] for t in data["tenants"]])
    return {"ok": True, "tenants": [t["tenant_id"] for t in data["tenants"]],
            "users": [u["email"] for u in data.get("users", [])], "logins": logins}


def _seed_values_documents(data: dict) -> None:
    """Populate values_documents with one doc per scope as a starting point."""
    ORG_BODY = (
        "# Organization Values\n\n"
        "These are the foundational values that apply across every department, team and role on the\n"
        "Aegis platform. They are written by the platform admin and govern everyone, all the time.\n\n"
        "1. **Human agency.** People remain accountable for decisions; the platform records context, "
        "not the decision itself.\n"
        "2. **Tenant isolation by default.** Data and capabilities are scoped to the originating "
        "department unless an explicit cross-tenant grant covers the action.\n"
        "3. **Auditability without exception.** Every governed action is recorded with the policy and "
        "values versions in effect; the chain is tamper-evident.\n"
        "4. **Fail-closed.** When a gate cannot evaluate, the answer is *deny*.\n"
        "5. **Plain-language values.** Each department, team, role and individual restates the values "
        "they layer on top so the cascade is human-readable end to end.\n"
    )
    DEPT_BODY_FMT = (
        "# {display_name} — Department Values\n\n"
        "These values are authored by the tenant admins of **{tenant_id}** and apply to every team "
        "and role inside this department, refining (always more restrictively) the organization "
        "values.\n\n"
        "- **Region of operation:** {region}.\n"
        "- **Default classification ceiling:** internal — anything higher requires explicit approval.\n"
        "- **Cross-tenant access:** never granted without dual control and a documented purpose.\n"
        "- **Token budget posture:** moderate; high-traffic teams declare a tighter budget.\n\n"
        "Edit this page to spell out the principles, regulatory frame, and tolerances specific to "
        "{display_name}.\n"
    )
    TEAM_BODY_FMT = (
        "# Team {team_id} — Values\n\n"
        "Refinements that apply to everyone on the **{team_id}** team in {tenant_id}, on top of the "
        "department values.\n\n"
        "- **Default chat tone:** professional and precise.\n"
        "- **Document retention:** standard unless the document is labelled confidential or higher.\n"
        "- **External tools:** opt-in per task, never default-allowed.\n"
    )
    ROLE_BODY_FMT = (
        "# Role {role_id} — Values\n\n"
        "Behavioural defaults for everyone holding the **{role_id}** role in {tenant_id}. Narrows "
        "the team values further.\n\n"
        "- **Decision authority:** as documented in the role's capability sheet.\n"
        "- **Reading scope:** as the role's `readable_namespaces` and classification ceiling allow.\n"
        "- **Writing scope:** as the role's `writable_namespaces` allow.\n"
    )
    with get_conn() as conn:
        # 1) one organization-level document
        conn.execute(
            "INSERT INTO values_documents(scope_type, tenant_id, scope_id, title, body_md, author_user) "
            "VALUES (%s, NULL, NULL, %s, %s, %s) "
            "ON CONFLICT (COALESCE(tenant_id,''), scope_type, COALESCE(scope_id,'')) "
            "DO UPDATE SET body_md=EXCLUDED.body_md, updated_at=now()",
            ("organization", "Aegis Organization Values", ORG_BODY, "platform-admin@aegis"),
        )
        # 2) one department doc per tenant
        for t in data["tenants"]:
            conn.execute(
                "INSERT INTO values_documents(scope_type, tenant_id, scope_id, title, body_md, author_user) "
                "VALUES (%s, %s, NULL, %s, %s, %s) "
                "ON CONFLICT (COALESCE(tenant_id,''), scope_type, COALESCE(scope_id,'')) "
                "DO UPDATE SET body_md=EXCLUDED.body_md, updated_at=now()",
                ("department", t["tenant_id"],
                 f"{t['display_name']} — Values",
                 DEPT_BODY_FMT.format(display_name=t["display_name"],
                                      tenant_id=t["tenant_id"],
                                      region=t.get("region", "AC1")),
                 "tenant-admin@" + t["tenant_id"]),
            )
            # 3) one doc per team in the tenant
            for team in t.get("teams", []):
                conn.execute(
                    "INSERT INTO values_documents(scope_type, tenant_id, scope_id, title, body_md, author_user) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (COALESCE(tenant_id,''), scope_type, COALESCE(scope_id,'')) "
                    "DO UPDATE SET body_md=EXCLUDED.body_md, updated_at=now()",
                    ("team", t["tenant_id"], team["team_id"],
                     f"Team {team['display_name']} — Values",
                     TEAM_BODY_FMT.format(team_id=team["team_id"], tenant_id=t["tenant_id"]),
                     "tenant-admin@" + t["tenant_id"]),
                )
            # 4) one doc per role in the tenant
            for role in t.get("roles", []):
                conn.execute(
                    "INSERT INTO values_documents(scope_type, tenant_id, scope_id, title, body_md, author_user) "
                    "VALUES (%s, %s, %s, %s, %s, %s) "
                    "ON CONFLICT (COALESCE(tenant_id,''), scope_type, COALESCE(scope_id,'')) "
                    "DO UPDATE SET body_md=EXCLUDED.body_md, updated_at=now()",
                    ("role", t["tenant_id"], role["role_id"],
                     f"Role {role['role_id']} — Values",
                     ROLE_BODY_FMT.format(role_id=role["role_id"], tenant_id=t["tenant_id"]),
                     "tenant-admin@" + t["tenant_id"]),
                )
