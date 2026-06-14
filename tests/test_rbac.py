from contextlib import contextmanager

import aegis_fabric.rbac as rbac


def test_normalize_caps_fills_defaults():
    c = rbac.normalize_caps({"skills": ["x"]})
    assert c["skills"] == ["x"]
    assert c["writable_namespaces"] == [] and c["runtime_exec"] is False
    # unknown keys are dropped
    assert "junk" not in rbac.normalize_caps({"junk": 1})


def test_template_capabilities():
    a = rbac.template_capabilities("analyst")
    assert "summarise-with-memory" in a["skills"]
    assert rbac.template_capabilities("does-not-exist") == rbac.EMPTY_CAPS


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    def __init__(self, handlers):
        self.handlers = handlers
        self.updates = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        for needle, rows in self.handlers.items():
            if needle in s:
                if s.startswith("UPDATE"):
                    self.updates.append(params)
                    return _Result([])
                return _Result(rows)
        if s.startswith("UPDATE"):
            self.updates.append(params)
            return _Result([])
        raise AssertionError(f"unexpected SQL: {s}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch_conn(monkeypatch, conn):
    @contextmanager
    def fake():
        yield conn
    monkeypatch.setattr(rbac, "get_conn", fake)


def test_all_rbac_shape(monkeypatch):
    conn = FakeConn({"FROM roles": [
        {"tenant_id": "acme-corp", "role_id": "analyst", "capabilities": {"skills": ["s1"]}},
        {"tenant_id": "acme-corp", "role_id": "lead", "capabilities": {"runtime_exec": True}},
        {"tenant_id": "beta-corp", "role_id": "analyst", "capabilities": {}},
    ]})
    _patch_conn(monkeypatch, conn)
    out = rbac.all_rbac()
    assert set(out) == {"acme-corp", "beta-corp"}
    assert out["acme-corp"]["analyst"]["skills"] == ["s1"]
    assert out["acme-corp"]["lead"]["runtime_exec"] is True
    assert out["beta-corp"]["analyst"]["skills"] == []  # normalized empty


def test_resolve_assignment_by_sub(monkeypatch):
    conn = FakeConn({"WHERE sub=%s": [{"tenant_id": "acme-corp", "team_id": "research", "role_id": "analyst"}]})
    _patch_conn(monkeypatch, conn)
    a = rbac.resolve_assignment("sub-123", "jane@acme-corp.example", True)
    assert a == {"tenant_id": "acme-corp", "team_id": "research", "role_id": "analyst"}


def test_resolve_assignment_email_binding(monkeypatch):
    # No sub row; an unbound email row exists -> bound and returned.
    conn = FakeConn({
        "WHERE sub=%s": [],
        "WHERE sub IS NULL": [{"assignment_id": 7, "tenant_id": "acme-corp", "team_id": "research", "role_id": "lead"}],
    })
    _patch_conn(monkeypatch, conn)
    a = rbac.resolve_assignment("sub-new", "lee@acme-corp.example", True)
    assert a["role_id"] == "lead"
    assert conn.updates and conn.updates[0][0] == "sub-new"  # sub got bound


def test_resolve_assignment_unverified_email_not_bound(monkeypatch):
    conn = FakeConn({"WHERE sub=%s": []})
    _patch_conn(monkeypatch, conn)
    assert rbac.resolve_assignment("sub-x", "x@y.example", False) is None


def test_sync_opa_puts_payload(monkeypatch):
    captured = {}

    class FakeResp:
        def raise_for_status(self):
            return None

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def put(self, url, json=None):
            captured["url"] = url
            captured["json"] = json
            return FakeResp()

    monkeypatch.setattr(rbac.httpx, "Client", FakeClient)
    data = {"acme-corp": {"analyst": rbac.template_capabilities("analyst")}}
    assert rbac.sync_opa(data) is True
    assert captured["url"].endswith("/v1/data/aegis/rbac")
    assert captured["json"] == data


def test_sync_opa_policy_pushes_rego(monkeypatch, tmp_path):
    rego = tmp_path / "sentinel.rego"
    rego.write_text("package sentinel.authz\n")
    monkeypatch.setattr(rbac, "_rego_path", lambda: rego)
    captured = {}

    class _Resp:
        def raise_for_status(self):
            return None

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def put(self, url, content=None, headers=None):
            captured["url"] = url
            captured["body"] = content
            return _Resp()

    monkeypatch.setattr(rbac.httpx, "Client", _Client)
    assert rbac.sync_opa_policy() is True
    assert captured["url"].endswith("/v1/policies/aegis_authz")
    assert b"package sentinel.authz" in captured["body"]
