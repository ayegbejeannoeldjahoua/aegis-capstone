"""Minimal, dependency-free forward-only SQL migration runner.

Applies ordered ``NNNN_*.sql`` files from ``deploy/postgres/migrations`` and
records each applied version in a ``schema_migrations`` table so re-runs are
idempotent. This gives schema *evolution* beyond the docker first-boot
``init.sql`` without pulling in a heavier framework. For complex needs
(branching, autogeneration) swap in Alembic - the runner is intentionally tiny.
"""
from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from .db import get_conn
from .logging_config import get_logger

logger = get_logger("aegis.migrate")

_CANDIDATES = [
    Path("/app/deploy/postgres/migrations"),
    Path("deploy/postgres/migrations"),
]


def _migrations_dir(path: str | None = None) -> Path:
    if path:
        return Path(path)
    for p in _CANDIDATES:
        if p.exists():
            return p
    return _CANDIDATES[-1]


def _ensure_table(conn) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version TEXT PRIMARY KEY,
            checksum TEXT NOT NULL,
            applied_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def applied_versions(conn) -> set[str]:
    rows = conn.execute("SELECT version FROM schema_migrations").fetchall()
    return {r["version"] for r in rows}


def migrate(path: str | None = None) -> dict:
    directory = _migrations_dir(path)
    files = sorted(directory.glob("*.sql"))
    applied: list[str] = []
    with get_conn() as conn:
        _ensure_table(conn)
        done = applied_versions(conn)
        for f in files:
            version = f.stem
            if version in done:
                continue
            sql = f.read_text()
            checksum = hashlib.sha256(sql.encode()).hexdigest()
            logger.info("applying migration %s", version)
            conn.execute(sql)
            conn.execute(
                "INSERT INTO schema_migrations(version, checksum) VALUES (%s, %s)",
                (version, checksum),
            )
            applied.append(version)
    return {"ok": True, "applied": applied, "dir": str(directory)}


if __name__ == "__main__":
    result = migrate(sys.argv[1] if len(sys.argv) > 1 else None)
    print(result)
