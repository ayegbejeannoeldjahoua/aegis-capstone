import aegis_fabric.audit as audit_mod


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def fetchall(self):
        return list(self._rows)


class FakeConn:
    """Tiny in-memory stand-in that recognizes the specific SQL audit.py issues."""

    def __init__(self, store):
        self.store = store

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        if s.startswith("SELECT event_hash FROM audit_events ORDER BY sequence_id DESC"):
            rows = sorted(self.store, key=lambda r: r["sequence_id"], reverse=True)
            return _Result([{"event_hash": rows[0]["event_hash"]}] if rows else [])
        if s.startswith("INSERT INTO audit_events"):
            cols = ["trace_id", "span_id", "parent_span_id", "tenant_id", "subject", "action",
                    "resource", "policy_version", "values_version", "decision", "reason",
                    "ciphertext", "nonce", "aad", "event_hash", "prev_hash"]
            row = dict(zip(cols, params))
            row["sequence_id"] = len(self.store) + 1
            self.store.append(row)
            return _Result([])
        if s.startswith("SELECT count(*) AS c FROM audit_events"):
            return _Result([{"c": len(self.store)}])
        if "FROM audit_events ORDER BY sequence_id LIMIT" in s:
            rows = sorted(self.store, key=lambda r: r["sequence_id"])
            return _Result([
                {"sequence_id": r["sequence_id"], "aad": r["aad"], "ciphertext": r["ciphertext"],
                 "nonce": r["nonce"], "event_hash": r["event_hash"], "prev_hash": r["prev_hash"]}
                for r in rows
            ])
        raise AssertionError(f"unexpected SQL: {s}")

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, store):
    from contextlib import contextmanager

    @contextmanager
    def fake_get_conn():
        yield FakeConn(store)

    monkeypatch.setattr(audit_mod, "get_conn", fake_get_conn)


def test_chain_links_and_verifies(monkeypatch):
    store: list = []
    _patch(monkeypatch, store)
    for i in range(3):
        audit_mod.append_event(
            trace_id="t1", span_id=None, parent_span_id=None, tenant_id="acme", subject="j@acme",
            action="model.call", resource=f"m{i}", policy_version="p", values_version="v",
            decision="allow", reason=None, payload={"i": i},
        )
    assert len(store) == 3
    assert store[0]["prev_hash"] is None
    assert store[1]["prev_hash"] == store[0]["event_hash"]
    out = audit_mod.verify_chain()
    assert out["ok"] is True and out["verified"] == 3


def test_tamper_is_detected(monkeypatch):
    store: list = []
    _patch(monkeypatch, store)
    for i in range(3):
        audit_mod.append_event(
            trace_id="t1", span_id=None, parent_span_id=None, tenant_id="acme", subject="j@acme",
            action="model.call", resource=f"m{i}", policy_version="p", values_version="v",
            decision="allow", reason=None, payload={"i": i},
        )
    # Tamper with the ciphertext of the middle row.
    store[1]["ciphertext"] = bytes(store[1]["ciphertext"]) + b"x"
    out = audit_mod.verify_chain()
    assert out["ok"] is False and out["failed_sequence_id"] == 2
