from __future__ import annotations

import json
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from .auth import Subject
from .db import get_conn


def current_month_key(now: datetime | None = None) -> str:
    value = now or datetime.now(timezone.utc)
    return value.strftime("%Y-%m")


def _month_key(value: Any = None) -> str:
    if isinstance(value, datetime):
        return current_month_key(value)
    return current_month_key()


def _iso(value: Any) -> str | None:
    return value.isoformat() if hasattr(value, "isoformat") else (str(value) if value else None)


def _title_from_prompt(prompt: str) -> str:
    text = re.sub(r"\s+", " ", (prompt or "").strip())
    if not text:
        return "New conversation"
    return text[:72].rstrip() + ("..." if len(text) > 72 else "")


def _token_source(snapshot: dict[str, Any] | None) -> str:
    data = snapshot or {}
    if int(data.get("prompt_tokens") or 0) or int(data.get("completion_tokens") or 0):
        return "provider"
    if int(data.get("tokens_total") or 0):
        return "estimated"
    return "unmetered"


def _message(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": str(row["id"]),
        "conversation_id": str(row["conversation_id"]),
        "tenant_id": row["tenant_id"],
        "user_email": row["user_email"],
        "role": row["role"],
        "content": row["content"],
        "trace_id": row.get("trace_id"),
        "provider": row.get("provider"),
        "model": row.get("model"),
        "input_tokens": row.get("input_tokens"),
        "output_tokens": row.get("output_tokens"),
        "total_tokens": row.get("total_tokens"),
        "token_source": row.get("token_source") or "unmetered",
        "created_at": _iso(row.get("created_at")),
        "month_key": row.get("month_key"),
        "metadata": row.get("metadata") or {},
    }


def _conversation(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "conversation_id": str(row["id"]),
        "tenant_id": row["tenant_id"],
        "user_email": row["user_email"],
        "title": row["title"],
        "created_at": _iso(row.get("created_at")),
        "updated_at": _iso(row.get("updated_at")),
        "last_message_at": _iso(row.get("last_message_at")),
        "month_key": row.get("month_key"),
        "archived": bool(row.get("archived")),
        "metadata": row.get("metadata") or {},
        "message_count": int(row.get("message_count") or 0),
    }


def list_conversations(
    subject: Subject,
    *,
    month_key: str | None = None,
    query: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    month = month_key or current_month_key()
    limit = max(1, min(int(limit or 50), 100))
    search = (query or "").strip()
    params: list[Any] = [subject.tenant_id, subject.email, month]
    search_clause = ""
    if search:
        params.extend([f"%{search}%", f"%{search}%"])
        search_clause = """
          AND (
            c.title ILIKE %s
            OR EXISTS (
              SELECT 1 FROM chat_messages m
              WHERE m.conversation_id=c.id AND m.content ILIKE %s
            )
          )
        """
    params.append(limit)
    with get_conn() as conn:
        rows = conn.execute(
            f"""
            SELECT c.*, count(m.id)::int AS message_count
            FROM chat_conversations c
            LEFT JOIN chat_messages m ON m.conversation_id=c.id
            WHERE c.tenant_id=%s
              AND c.user_email=%s
              AND c.month_key=%s
              AND c.archived=FALSE
              {search_clause}
            GROUP BY c.id
            ORDER BY COALESCE(c.last_message_at, c.created_at) DESC, c.updated_at DESC
            LIMIT %s
            """,
            params,
        ).fetchall()
    return [_conversation(dict(row)) for row in rows]


def get_messages(subject: Subject, conversation_id: str, *, month_key: str | None = None) -> list[dict[str, Any]] | None:
    try:
        conv_id = uuid.UUID(str(conversation_id))
    except ValueError:
        return None
    clauses = [
        "c.id=%s",
        "c.tenant_id=%s",
        "c.user_email=%s",
        "c.archived=FALSE",
    ]
    params: list[Any] = [conv_id, subject.tenant_id, subject.email]
    if month_key:
        clauses.append("m.month_key=%s")
        params.append(month_key)
    with get_conn() as conn:
        owner = conn.execute(
            "SELECT id FROM chat_conversations c WHERE c.id=%s AND c.tenant_id=%s AND c.user_email=%s AND c.archived=FALSE",
            (conv_id, subject.tenant_id, subject.email),
        ).fetchone()
        if not owner:
            return None
        rows = conn.execute(
            f"""
            SELECT m.*
            FROM chat_messages m
            JOIN chat_conversations c ON c.id=m.conversation_id
            WHERE {' AND '.join(clauses)}
            ORDER BY m.created_at ASC, m.id ASC
            """,
            params,
        ).fetchall()
    return [_message(dict(row)) for row in rows]


def create_conversation(subject: Subject, *, title: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    conv_id = uuid.uuid4()
    with get_conn() as conn:
        row = conn.execute(
            """
            INSERT INTO chat_conversations(id, tenant_id, user_email, title, created_at, updated_at, month_key, metadata)
            VALUES (%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            RETURNING *, 0::int AS message_count
            """,
            (
                conv_id,
                subject.tenant_id,
                subject.email,
                title or "New conversation",
                now,
                now,
                _month_key(now),
                json.dumps(metadata or {}, sort_keys=True),
            ),
        ).fetchone()
    return _conversation(dict(row))


def archive_conversation(subject: Subject, conversation_id: str) -> bool:
    try:
        conv_id = uuid.UUID(str(conversation_id))
    except ValueError:
        return False
    with get_conn() as conn:
        row = conn.execute(
            """
            UPDATE chat_conversations
            SET archived=TRUE, updated_at=now()
            WHERE id=%s AND tenant_id=%s AND user_email=%s AND archived=FALSE
            RETURNING id
            """,
            (conv_id, subject.tenant_id, subject.email),
        ).fetchone()
    return bool(row)


def append_turn(
    subject: Subject,
    conversation_id: str | None,
    prompt: str,
    result: dict[str, Any],
    snapshot: dict[str, Any] | None,
    requested_model: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc)
    month = _month_key(now)
    conv_id: uuid.UUID | None = None
    if conversation_id:
        try:
            conv_id = uuid.UUID(str(conversation_id))
        except ValueError:
            conv_id = None

    answer = str((result or {}).get("answer") or "")
    trace_id = (result or {}).get("trace_id") or (snapshot or {}).get("trace_id")
    token_source = _token_source(snapshot)
    provider = (result or {}).get("provider")
    model = (result or {}).get("model")
    input_tokens = int((snapshot or {}).get("prompt_tokens") or 0)
    output_tokens = int((snapshot or {}).get("completion_tokens") or 0)
    total_tokens = int((snapshot or {}).get("tokens_total") or 0)
    conv_meta = {
        "skill_id": (result or {}).get("skill_id"),
        "last_trace_id": trace_id,
        "last_provider": provider,
        "last_model": model,
        "requested_model": requested_model,
        "team_id": subject.team_id,
        "role": subject.role,
    }

    with get_conn() as conn:
        conv = None
        if conv_id:
            conv = conn.execute(
                """
                SELECT *
                FROM chat_conversations
                WHERE id=%s AND tenant_id=%s AND user_email=%s AND archived=FALSE
                """,
                (conv_id, subject.tenant_id, subject.email),
            ).fetchone()
        if not conv:
            conv_id = uuid.uuid4()
            conn.execute(
                """
                INSERT INTO chat_conversations(id, tenant_id, user_email, title, created_at, updated_at,
                                               last_message_at, month_key, metadata)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
                """,
                (
                    conv_id,
                    subject.tenant_id,
                    subject.email,
                    _title_from_prompt(prompt),
                    now,
                    now,
                    now,
                    month,
                    json.dumps(conv_meta, sort_keys=True),
                ),
            )
        user_id = uuid.uuid4()
        assistant_id = uuid.uuid4()
        conn.execute(
            """
            INSERT INTO chat_messages(id, conversation_id, tenant_id, user_email, role, content,
                                      created_at, month_key, metadata)
            VALUES (%s,%s,%s,%s,'user',%s,%s,%s,%s::jsonb)
            """,
            (
                user_id,
                conv_id,
                subject.tenant_id,
                subject.email,
                prompt,
                now,
                month,
                json.dumps({"team_id": subject.team_id, "role": subject.role}, sort_keys=True),
            ),
        )
        conn.execute(
            """
            INSERT INTO chat_messages(id, conversation_id, tenant_id, user_email, role, content,
                                      trace_id, provider, model, input_tokens, output_tokens,
                                      total_tokens, token_source, created_at, month_key, metadata)
            VALUES (%s,%s,%s,%s,'assistant',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb)
            """,
            (
                assistant_id,
                conv_id,
                subject.tenant_id,
                subject.email,
                answer,
                trace_id,
                provider,
                model,
                input_tokens,
                output_tokens,
                total_tokens,
                token_source,
                now,
                month,
                json.dumps(
                    {
                        "skill_id": (result or {}).get("skill_id"),
                        "requested_model": requested_model,
                        "team_id": subject.team_id,
                        "role": subject.role,
                    },
                    sort_keys=True,
                ),
            ),
        )
        row = conn.execute(
            """
            UPDATE chat_conversations
            SET updated_at=%s,
                last_message_at=%s,
                metadata=metadata || %s::jsonb
            WHERE id=%s
            RETURNING *, (
              SELECT count(*)::int FROM chat_messages WHERE conversation_id=chat_conversations.id
            ) AS message_count
            """,
            (now, now, json.dumps(conv_meta, sort_keys=True), conv_id),
        ).fetchone()
        messages = conn.execute(
            """
            SELECT *
            FROM chat_messages
            WHERE conversation_id=%s
            ORDER BY created_at ASC, id ASC
            """,
            (conv_id,),
        ).fetchall()

    return {
        "conversation": _conversation(dict(row)),
        "conversation_id": str(conv_id),
        "messages": [_message(dict(message)) for message in messages],
    }
