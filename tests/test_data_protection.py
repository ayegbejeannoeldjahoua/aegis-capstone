"""v1.9.0 data-protection cluster: PII masking, retention + memory.delete gates,
memory_store.delete, the approvals erase executor, and the DELETE /v1/memory endpoint."""
from contextlib import contextmanager

from fastapi.testclient import TestClient

import aegis_fabric.approvals as approvals
import aegis_fabric.audit as audit
import aegis_fabric.main as main
import aegis_fabric.memory as mem
import aegis_fabric.rbac as rbac
from aegis_fabric import tools
from aegis_fabric.auth import Subject, get_subject
from aegis_fabric.memory import memory_store
from aegis_fabric.policy import PolicyDecision
from aegis_fabric.values import ResolvedValues

UID = "11111111-1111-1111-1111-111111111111"


# ---- PII masking ----
def test_mask_memories():
    masked = tools.mask_memories([{"body": "reach a@b.com or 555-12-3456"}], "masked")
    assert "[EMAIL]" in masked[0]["body"] and "[SSN]" in masked[0]["body"]
    assert tools.mask_memories([{"body": "a@b.com"}], "full")[0]["body"] == "a@b.com"


# ---- retention + memory.delete gate logic (mirrors sentinel.rego vs template caps) ----
def _caps(role):
    return rbac.derived_caps(rbac.template_capabilities(role))


def _write_ok(role, retention):
    c = _caps(role)
    ns_ok = "analyst-notes" in c["writable_namespaces"]
    return ns_ok and (retention in c["allowed_retention_classes"])


def test_retention_gate():
    assert _write_ok("analyst", "standard") is True
    assert _write_ok("analyst", "legal-hold") is False
    assert _write_ok("lead", "long") is True
    assert _write_ok("lead", "legal-hold") is False
    assert _write_ok("platform-admin", "legal-hold") is True


def test_memory_delete_gate():
    assert _caps("analyst")["can_erase"] is False
    assert _caps("lead")["can_erase"] is False
    assert _caps("tenant-admin")["can_erase"] is True
    assert _caps("platform-admin")["can_erase"] is True


# ---- memory_store.delete ----
class _Res:
    def __init__(self, row):
        self._row = row

    def fetchone(self):
        return self._row


class _Conn:
    def __init__(self, found):
        self.found = found

    def execute(self, sql, params=None):
        return _Res({"id": "x"} if self.found else None)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_memory_store_delete(monkeypatch):
    @contextmanager
    def found():
        yield _Conn(True)
    monkeypatch.setattr(mem, "get_conn", found)
    assert memory_store.delete("acme-corp", UID) == 1

    @contextmanager
    def missing():
        yield _Conn(False)
    monkeypatch.setattr(mem, "get_conn", missing)
    assert memory_store.delete("acme-corp", UID) == 0


# ---- approvals erase executor ----
def test_memory_erase_executor(monkeypatch):
    assert "memory.erase" in approvals.EXECUTORS
    monkeypatch.setattr(mem.memory_store, "delete", lambda t, i: 1)
    out = approvals.EXECUTORS["memory.erase"]("acme-corp", {"memory_id": UID})
    assert out["rows"] == 1 and out["deleted"] == UID


# ---- DELETE /v1/memory/{id} endpoint ----
def _client(monkeypatch, allow=True, requires_approval=False):
    subj = Subject(sub="s", email="pat@it.example", tenant_id="it", team_id="platform",
                   role="platform-admin", token_claims={})
    main.app.dependency_overrides[get_subject] = lambda: subj
    monkeypatch.setattr(main.limiter, "allow", lambda *a, **k: True)

    async def fake_run_db(fn, *a, **k):
        return fn(*a, **k)
    monkeypatch.setattr(main, "run_db", fake_run_db)

    async def fake_decide(subject, action, resource, values):
        return PolicyDecision(allow=allow, reasons=[] if allow else ["action_not_permitted:memory.delete"],
                              decision="allow" if allow else "deny")
    monkeypatch.setattr(main, "decide", fake_decide)

    vals = ResolvedValues(tenant_id="it", team_id="platform", role="platform-admin", user="pat",
                          can_erase=True, erase_requires_approval=requires_approval)
    monkeypatch.setattr(main, "resolve_values", lambda *a, **k: vals)
    monkeypatch.setattr(audit, "append_event", lambda **k: "h")
    monkeypatch.setattr(mem.memory_store, "delete", lambda t, i: 1)
    monkeypatch.setattr(approvals, "create_pending", lambda *a, **k: {"pending": True, "pending_id": 9})
    return TestClient(main.app)


def test_erase_direct(monkeypatch):
    c = _client(monkeypatch, allow=True, requires_approval=False)
    try:
        r = c.delete(f"/v1/memory/{UID}")
        assert r.status_code == 200 and r.json()["ok"] is True
    finally:
        main.app.dependency_overrides.clear()


def test_erase_requires_approval(monkeypatch):
    c = _client(monkeypatch, allow=True, requires_approval=True)
    try:
        r = c.delete(f"/v1/memory/{UID}")
        assert r.status_code == 200 and r.json().get("pending") is True
    finally:
        main.app.dependency_overrides.clear()


def test_erase_denied(monkeypatch):
    c = _client(monkeypatch, allow=False)
    try:
        assert c.delete(f"/v1/memory/{UID}").status_code == 403
    finally:
        main.app.dependency_overrides.clear()


def test_erase_bad_uuid(monkeypatch):
    c = _client(monkeypatch, allow=True)
    try:
        assert c.delete("/v1/memory/not-a-uuid").status_code == 400
    finally:
        main.app.dependency_overrides.clear()
