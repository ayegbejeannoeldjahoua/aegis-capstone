from __future__ import annotations

import asyncio
from contextlib import contextmanager
from typing import Any, Callable, Iterator, TypeVar

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

from .settings import settings

T = TypeVar("T")

_pool: ConnectionPool | None = None


def init_pool() -> ConnectionPool:
    """Create the process-wide connection pool. Idempotent."""
    global _pool
    if _pool is None:
        _pool = ConnectionPool(
            conninfo=settings.database_url,
            min_size=settings.db_pool_min,
            max_size=settings.db_pool_max,
            kwargs={"row_factory": dict_row},
            open=True,
            name="aegis",
        )
    return _pool


def close_pool() -> None:
    global _pool
    if _pool is not None:
        _pool.close()
        _pool = None


def get_pool() -> ConnectionPool:
    if _pool is None:
        return init_pool()
    return _pool


@contextmanager
def get_conn() -> Iterator[psycopg.Connection]:
    """Borrow a pooled connection. Commits on success, rolls back on error."""
    pool = get_pool()
    with pool.connection() as conn:
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise


async def run_db(fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
    """Run a blocking DB callable in a worker thread so the event loop is never
    blocked by synchronous psycopg I/O inside async request handlers."""
    return await asyncio.to_thread(fn, *args, **kwargs)


def ping() -> bool:
    """Readiness check: confirm the database answers a trivial query."""
    with get_conn() as conn:
        conn.execute("SELECT 1")
    return True


# ---------------------------------------------------------------------------
# v1.20 BR-ISO-05 -- RLS-aware connection helper.
#
# Per-tenant queries must run inside a `with_tenant_scope(tenant_id)` block so
# Postgres RLS policies on memories/sessions/isas/audit_events can see the
# session GUC `app.tenant_id`. Admin operations that legitimately span tenants
# (export, fixture seed, cross-tenant audit) pass `*` to bypass RLS.
# ---------------------------------------------------------------------------

BYPASS_TENANT = "*"


@contextmanager
def with_tenant_scope(tenant_id: str | None) -> Iterator[psycopg.Connection]:
    """Borrow a pooled connection with `app.tenant_id` GUC set for RLS.

    Args:
        tenant_id: the tenant whose rows the caller wants to see/write. Pass
            BYPASS_TENANT ('*') for admin operations that span tenants.

    Commits on success, rolls back on exception. The GUC is set with
    is_local=true so it auto-clears on COMMIT/ROLLBACK, preventing leakage to
    the next borrower of the pooled connection.
    """
    scope = tenant_id or BYPASS_TENANT
    pool = get_pool()
    with pool.connection() as conn:
        try:
            conn.execute("SELECT set_config('app.tenant_id', %s, true)", (scope,))
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
