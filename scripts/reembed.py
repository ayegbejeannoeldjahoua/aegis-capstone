"""Re-embed every memory row whose embedding column is NULL.

Run once after switching from keyword-only retrieval to semantic retrieval, or
after seeding a fresh fixture. Reads each row's body, embeds it via the
configured sentence-transformers model, and writes the vector back.

Usage (inside the api container):
    docker compose -p aegis exec -T api python -m scripts.reembed

Or from the host with the same DATABASE_URL the api uses.
"""
from __future__ import annotations

import sys
import time
from typing import Any

from aegis_fabric import embeddings
from aegis_fabric.db import get_conn
from aegis_fabric.logging_config import get_logger
from aegis_fabric.settings import settings

logger = get_logger("aegis.reembed")


def main() -> int:
    if not settings.embed_enabled:
        print("AEGIS_EMBED_ENABLED=false; nothing to do.")
        return 0

    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id::text, length(body) AS n FROM memories "
            "WHERE embedding IS NULL ORDER BY created_at"
        ).fetchall()
    total = len(rows)
    if total == 0:
        print("All memory rows already have embeddings. Nothing to do.")
        return 0
    print(f"Re-embedding {total} memory rows with {settings.embed_model} "
          f"(dim={settings.embed_dim}) ...")

    start = time.time()
    done = 0
    skipped = 0
    for r in rows:
        rid = r["id"]
        with get_conn() as conn:
            body_row = conn.execute(
                "SELECT body FROM memories WHERE id=%s::uuid", (rid,)
            ).fetchone()
        if not body_row or not body_row["body"]:
            skipped += 1
            continue
        vec = embeddings.embed(body_row["body"])
        if vec is None:
            skipped += 1
            continue
        vstr = embeddings.to_pgvector(vec)
        with get_conn() as conn:
            conn.execute(
                "UPDATE memories SET embedding=%s::vector WHERE id=%s::uuid",
                (vstr, rid),
            )
        done += 1
        if done % 25 == 0:
            elapsed = time.time() - start
            rate = done / max(elapsed, 0.001)
            print(f"  {done}/{total}  ({rate:.1f} rows/s)")
    elapsed = time.time() - start
    print(f"Done. Embedded {done} rows, skipped {skipped}, "
          f"in {elapsed:.1f}s ({done/max(elapsed,0.001):.1f} rows/s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
