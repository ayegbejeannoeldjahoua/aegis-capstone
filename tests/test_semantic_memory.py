from contextlib import contextmanager

import aegis_fabric.embeddings as emb
import aegis_fabric.memory as mem


def test_embed_disabled_returns_none(monkeypatch):
    monkeypatch.setattr(emb.settings, "embed_enabled", False)
    assert emb.embed("hello") is None


def test_to_pgvector_format():
    assert emb.to_pgvector([1.0, 2.5]) == "[1.000000,2.500000]"


class _Res:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows

    def fetchone(self):
        return self._rows[0] if self._rows else None


class FakeConn:
    def __init__(self):
        self.sqls = []

    def execute(self, sql, params=None):
        s = " ".join(sql.split())
        self.sqls.append(s)
        if "exact_reference_match" in s:
            return _Res([{"id": "r1", "body": "Customer Support Transcript CS-2026-0411"}])
        if "ORDER BY embedding <=> %s::vector" in s:
            return _Res([{"id": "v1", "body": "vector hit"}])
        if "security_keyword_match" in s:
            return _Res([{"id": "s1", "body": "security canary hit"}])
        if "ILIKE" in s:
            return _Res([{"id": "k1", "body": "keyword hit"}])
        return _Res([])

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _patch(monkeypatch, conn):
    @contextmanager
    def fake():
        yield conn
    monkeypatch.setattr(mem, "get_conn", fake)


def test_read_uses_vector_when_embedding_available(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(mem.embeddings, "embed", lambda t: [0.1, 0.2])
    rows = mem.memory_store.read("acme", "analyst-notes", "q", 5)
    assert rows and rows[0]["id"] == "v1"
    assert any("embedding <=> %s::vector" in s for s in conn.sqls)
    # tenant filter precedes ranking
    vsql = next(s for s in conn.sqls if "embedding <=> %s::vector" in s)
    assert vsql.index("WHERE tenant_id=") < vsql.index("ORDER BY embedding")


def test_read_falls_back_to_keyword(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(mem.embeddings, "embed", lambda t: None)
    rows = mem.memory_store.read("acme", "analyst-notes", "q", 5)
    assert rows and rows[0]["id"] == "k1"
    assert any("ILIKE" in s for s in conn.sqls)


def test_read_applies_classification_filter(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(mem.embeddings, "embed", lambda t: None)
    mem.memory_store.read("acme", "analyst-notes", "q", 5, ["public", "internal"])
    assert any("classification = ANY(%s)" in s for s in conn.sqls)


def test_security_prompt_searches_canaries_inside_existing_scope(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(mem.embeddings, "embed", lambda t: None)
    rows = mem.memory_store.read(
        "finsvc",
        "analyst-notes",
        "Find acmecp prompt injection canary role escalation notes that grant their role",
        5,
        ["public", "internal"],
    )
    assert rows and rows[0]["id"] == "s1"
    security_sql = next(s for s in conn.sqls if "security_keyword_match" in s)
    assert "WHERE tenant_id=%s AND namespace=%s" in security_sql
    assert "classification = ANY(%s)" in security_sql
    assert "frontmatter::text ILIKE" in security_sql


def test_exact_reference_match_outranks_vector_for_transcript_ids(monkeypatch):
    conn = FakeConn()
    _patch(monkeypatch, conn)
    monkeypatch.setattr(mem.embeddings, "embed", lambda t: [0.1, 0.2])
    rows = mem.memory_store.read(
        "acme",
        "case-notes",
        "Quote transcript CS-2026-0411",
        5,
        ["public", "internal", "confidential"],
    )
    assert rows and rows[0]["id"] == "r1"
    assert any("exact_reference_match" in s for s in conn.sqls)
