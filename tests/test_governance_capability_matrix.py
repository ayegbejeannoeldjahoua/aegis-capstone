from fastapi import FastAPI
from fastapi.testclient import TestClient

import aegis_fabric.admin as admin
from aegis_fabric.auth import AdminPrincipal


def _app(principal: AdminPrincipal | None = None):
    app = FastAPI()
    app.include_router(admin.router)
    if principal is not None:
        app.dependency_overrides[admin.admin_principal] = lambda: principal
    return app


def _cell(matrix: dict, role_id: str, action: str) -> dict:
    row = next(r for r in matrix["matrix"] if r["role_id"] == role_id)
    return next(c for c in row["cells"] if c["action"] == action)


def _role(matrix: dict, role_id: str) -> dict:
    return next(r for r in matrix["roles"] if r["role_id"] == role_id)


def test_capability_matrix_builds_structured_decisions_and_data_scopes():
    principal = AdminPrincipal(scope="platform", tenant_id=None, email="priya@it.example")
    template_rows = [
        {
            "template_id": "test-auditor",
            "display_name": "Test Auditor",
            "capabilities": admin.rbac.template_capabilities("viewer"),
        }
    ]
    role_rows = [
        {
            "tenant_id": "acmecp",
            "team_id": "research",
            "role_id": "analyst",
            "template_id": "analyst",
            "capabilities": admin.rbac.template_capabilities("analyst"),
        },
        {
            "tenant_id": "acmecp",
            "team_id": "research",
            "role_id": "lead",
            "template_id": "lead",
            "capabilities": admin.rbac.template_capabilities("lead"),
        },
        {
            "tenant_id": "acmecp",
            "team_id": "research",
            "role_id": "tenant-admin",
            "template_id": "tenant-admin",
            "capabilities": admin.rbac.template_capabilities("tenant-admin"),
        },
        {
            "tenant_id": "it",
            "team_id": "platform",
            "role_id": "platform-admin",
            "template_id": "platform-admin",
            "capabilities": admin.rbac.template_capabilities("platform-admin"),
        },
    ]
    assignment_rows = [
        {"user_email": "kim@acmecp.example", "tenant_id": "acmecp", "team_id": "research", "role_id": "lead"}
    ]

    matrix = admin._build_capability_matrix(principal, template_rows, role_rows, assignment_rows)

    assert "test-auditor" in {r["role_id"] for r in matrix["roles"]}
    assert _role(matrix, "lead")["pii_scope"] == "full"
    assert _role(matrix, "analyst")["pii_scope"] == "masked"
    assert _role(matrix, "tenant-admin")["admin_scope"] == "tenant"
    assert _cell(matrix, "lead", "cross_tenant.read")["decision"] == "deny"
    assert _cell(matrix, "platform-admin", "cross_tenant.read")["decision"] == "deny"
    assert _cell(matrix, "tenant-admin", "values.write.organization")["decision"] == "deny"
    assert _cell(matrix, "platform-admin", "values.write.organization")["decision"] == "conditional"
    assert _cell(matrix, "tenant-admin", "user.admin")["scope"] == "own_tenant"
    assert any("downstream" in note for note in matrix["notes"])
    assert any(p["email"] == "kim@acmecp.example" for p in _role(matrix, "lead")["persona_examples"])


def test_capability_matrix_endpoint_requires_admin():
    with TestClient(_app()) as client:
        response = client.get("/admin/governance/capability-matrix")
    assert response.status_code == 401


def test_capability_matrix_endpoint_uses_tenant_admin_scope(monkeypatch):
    def fake_matrix(principal: AdminPrincipal):
        return {
            "scope": {"admin_scope": principal.scope, "tenant_id": principal.tenant_id},
            "roles": [],
            "actions": [],
            "matrix": [],
            "persona_examples": [],
            "scenario_map": [],
            "notes": [],
        }

    monkeypatch.setattr(admin, "_capability_matrix", fake_matrix)
    principal = AdminPrincipal(scope="tenant", tenant_id="acmecp", email="pat@acmecp.example")
    with TestClient(_app(principal)) as client:
        response = client.get("/admin/governance/capability-matrix")
    assert response.status_code == 200
    assert response.json()["scope"] == {"admin_scope": "tenant", "tenant_id": "acmecp"}
