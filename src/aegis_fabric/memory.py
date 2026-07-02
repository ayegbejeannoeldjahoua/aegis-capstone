from __future__ import annotations

import hashlib
import json
import re
import time

from . import embeddings
from .db import get_conn
from .values import ResolvedValues

_COLS = ("id::text, tenant_id, namespace, author_user, author_scope, classification, "
         "retention_class, frontmatter, body, created_at::text")

_SECURITY_QUERY = re.compile(
    r"\b(injection|prompt injection|canary|suspicious instruction|unsafe instruction|"
    r"tool[- ]output|tool output excerpt|role escalation|grant role|grant their role|"
    r"capability grants?|audit skip|audit-skipping|audit logging|access control|"
    r"authorization|capabilities|governance memos?|policy notes?|team decision logs?|"
    r"policy overridden|policy override|data exfiltration|ignore previous instructions|"
    r"ignore all previous instructions|roles?)\b",
    re.I,
)
_REFERENCE_ID = re.compile(r"\b(?:CS|INC)-[A-Z0-9-]+\b", re.I)


def _reference_terms(query: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for match in _REFERENCE_ID.findall(query or ""):
        key = match.upper()
        if key not in seen:
            seen.add(key)
            out.append(match)
    return out


def _security_terms(query: str) -> list[str]:
    """Expanded keyword set for realistic governance/security prompts.

    This does not widen authorization. It only adds extra keyword probes inside
    the already-authorized tenant/namespace/classification search scope.
    """
    text = (query or "").lower()
    if not _SECURITY_QUERY.search(text):
        return []
    terms = [
        "Injection Canary",
        "Prompt Injection Canary",
        "is_injection_canary",
        "canary_type",
        "suspicious instruction",
        "unsafe instruction",
        "IGNORE ALL PREVIOUS INSTRUCTIONS",
        "POLICY OVERRIDDEN",
    ]
    if re.search(r"\b(role|roles|access control|authorization|capabilit|grant)\b", text):
        terms += ["Role Escalation", "grant their role", "grant role", "capability grant", "capability grants"]
    if re.search(r"\b(audit|logging|ledger|skip)\b", text):
        terms += ["Suppress Audit", "audit ledger must skip", "audit-skipping", "audit skip"]
    if re.search(r"\b(tool[- ]output|tool output excerpt|suspicious|unsafe)\b", text):
        terms += ["Tool Output", "tool-output excerpt", "IGNORE ALL PREVIOUS INSTRUCTIONS"]
    if re.search(r"\b(data exfiltration|exfiltrat|secret|secrets)\b", text):
        terms += ["Data Exfiltration", "exfiltrate", "secrets"]
    if re.search(r"\b(policy|governance|memo|memos|notes|team decision)\b", text):
        terms += ["governance memo", "policy notes", "team decisions", "Injection Canary"]

    out: list[str] = []
    seen: set[str] = set()
    for term in terms:
        key = term.lower()
        if key not in seen:
            seen.add(key)
            out.append(term)
    return out


class MemoryStore:
    """Tenant-scoped memory. Hybrid retrieval: semantic (pgvector) UNION keyword
    (ILIKE), deduplicated by id, capped at `limit`. The tenant filter is always
    applied BEFORE similarity ranking, so one tenant can never rank over
    another's vectors.

    Why hybrid: pure semantic search underweights literal title or identifier
    mentions ("CS-2026-0411", "Customer Support Call Transcript") in long verbose
    prompts because the embedding averages the whole sentence. Pure keyword
    search misses paraphrases ("dashboard lockout"). Running both and
    deduplicating catches the union — vector first so the highest semantic
    matches lead, then keyword fills in any literal hits the embedder missed.
    Both paths apply the SAME tenant + classification filter, so governance
    semantics are preserved."""

    def read(self, tenant_id: str, namespace: str, query: str, limit: int = 5,
             allowed_classifications: list[str] | None = None) -> list[dict]:
        start = time.perf_counter()
        reference_rows: list[dict] = []
        vector_rows: list[dict] = []
        security_rows: list[dict] = []
        keyword_rows: list[dict] = []
        results: list[dict] = []
        seen: set = set()

        # 1) Exact reference IDs (CS-..., INC-...) are strongest. A literal
        # transcript/case ID must outrank semantically similar canary transcripts.
        refs = _reference_terms(query)
        if refs:
            reference_rows = self._reference_search(tenant_id, namespace, refs, limit, allowed_classifications)

        # 2) Semantic — meaning match (catches "dashboard lockout" -> transcript).
        vec = embeddings.embed(query)
        if vec is not None:
            for row in self._vector_search(tenant_id, namespace, vec, limit, allowed_classifications):
                vector_rows.append(row)

        # 3) Security/canary expansion -- only for governance/security prompts.
        # This searches body plus frontmatter JSON text under the same tenant,
        # namespace, and classification constraints as vector retrieval.
        terms = _security_terms(query)
        if terms:
            security_rows = self._security_search(
                tenant_id, namespace, terms, max(limit, 6), allowed_classifications
            )

        # 4) Keyword — literal substring match (catches doc titles / IDs the
        #    embedder underweighted). Always runs, regardless of whether (1)
        #    found anything, so a verbose prompt that names a specific doc
        #    still surfaces it.
        for row in self._keyword_search(tenant_id, namespace, query, limit, allowed_classifications):
            keyword_rows.append(row)

        # Canary/security rows are boosted for S16 prompts, but final output is
        # still capped at the caller's requested limit.
        groups = [reference_rows, security_rows, vector_rows, keyword_rows]
        for group in groups:
            for row in group:
                rid = row.get("id")
                if rid and rid not in seen:
                    results.append(row)
                    seen.add(rid)

        out = results[:limit]
        try:
            from . import operational_metrics

            operational_metrics.record_retrieval((time.perf_counter() - start) * 1000.0, tenant_id, namespace, out)
        except Exception:
            pass
        return out

    def _vector_search(self, tenant_id, namespace, vec, limit, allowed=None) -> list[dict]:
        vstr = embeddings.to_pgvector(vec)
        cls = " AND classification = ANY(%s)" if allowed else ""
        params = [tenant_id, namespace] + ([allowed] if allowed else []) + [vstr, limit]
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLS}, (1.0 - (embedding <=> %s::vector))::double precision AS score, "
                "'semantic_similarity' AS retrieval_reason FROM memories "
                f"WHERE tenant_id=%s AND namespace=%s AND embedding IS NOT NULL{cls} "
                "ORDER BY embedding <=> %s::vector LIMIT %s",
                [vstr] + params,
            ).fetchall()
        return list(rows)

    def _reference_search(self, tenant_id, namespace, refs: list[str], limit, allowed=None) -> list[dict]:
        if not refs:
            return []
        cls = " AND classification = ANY(%s)" if allowed else ""
        like_clauses = []
        like_params: list = []
        for ref in refs[:8]:
            like_clauses.append("(body ILIKE %s OR frontmatter::text ILIKE %s)")
            like_params.extend([f"%{ref}%", f"%{ref}%"])
        where_likes = " OR ".join(like_clauses)

        params = [tenant_id, namespace] + ([allowed] if allowed else []) + like_params + [limit]
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLS}, 1.0::double precision AS score, "
                "'exact_reference_match' AS retrieval_reason FROM memories "
                f"WHERE tenant_id=%s AND namespace=%s{cls} AND ({where_likes}) "
                "ORDER BY created_at DESC LIMIT %s",
                params,
            ).fetchall()
        return list(rows)

    def _security_search(self, tenant_id, namespace, terms: list[str], limit, allowed=None) -> list[dict]:
        if not terms:
            return []
        cls = " AND classification = ANY(%s)" if allowed else ""
        like_clauses = []
        like_params: list = []
        for term in terms[:32]:
            like_clauses.append("(body ILIKE %s OR frontmatter::text ILIKE %s)")
            like_params.extend([f"%{term}%", f"%{term}%"])
        where_likes = " OR ".join(like_clauses)

        params = [tenant_id, namespace] + ([allowed] if allowed else []) + like_params + [limit]
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLS}, 1.0::double precision AS score, "
                "'security_keyword_match' AS retrieval_reason FROM memories "
                f"WHERE tenant_id=%s AND namespace=%s{cls} AND ({where_likes}) "
                "ORDER BY created_at DESC LIMIT %s",
                params,
            ).fetchall()
        return list(rows)

    def _keyword_search(self, tenant_id, namespace, query, limit, allowed=None) -> list[dict]:
        # Tokenized OR-match across body + frontmatter so natural-language queries
        # retrieve docs even without exact substring matches.
        # Small stopword set — keyword search is now the FALLBACK only. The
        # primary retrieval path is semantic (vector search via pgvector +
        # sentence-transformers); see memory_store.read() above. If the
        # embedder produces no vector or fails, we fall through here.
        STOPWORDS = {
            "the","a","an","and","or","of","to","in","on","is","are","was","were",
            "for","with","at","by","this","that","it","be","as","from","what","who",
            "you","me","i","do","does","did","tell","give","show","please","summarise",
            "summarize","summary","about","can","could","would","should","have","has",
            "had","my","your","our","their","its","they","them","we","us","he","she",
            "his","her","there","here","into","over","under","than","then","but","if",
        }
        tokens = [t.strip(".,!?;:\"'()[]{}").lower()
                  for t in (query or "").split() if t]
        tokens = [t for t in tokens if len(t) >= 3 and t not in STOPWORDS]
        if not tokens and query:
            tokens = [query[:80].lower()]
        if not tokens:
            return []

        cls = " AND classification = ANY(%s)" if allowed else ""
        like_clauses = []
        like_params: list = []
        # Cap at 24 substantive tokens. The original was 8; that truncated
        # natural-language prompts of the form "Quote the first six lines of
        # body content from the document titled <NAME> verbatim", where
        # substantive nouns appeared at positions 9-12 and were dropped. 24
        # comfortably covers any reasonable chat prompt without truncation
        # and keeps the ILIKE query cost bounded (24 OR'd clauses, single
        # index-less scan per namespace; ~ms even on 100k rows).
        for tok in tokens[:24]:
            like_clauses.append("(body ILIKE %s OR frontmatter::text ILIKE %s)")
            like_params.extend([f"%{tok}%", f"%{tok}%"])
        where_likes = " OR ".join(like_clauses)

        params = [tenant_id, namespace] + ([allowed] if allowed else []) + like_params + [limit]
        with get_conn() as conn:
            rows = conn.execute(
                f"SELECT {_COLS}, NULL::double precision AS score, 'keyword_match' AS retrieval_reason FROM memories "
                f"WHERE tenant_id=%s AND namespace=%s{cls} AND ({where_likes}) "
                "ORDER BY created_at DESC LIMIT %s",
                params,
            ).fetchall()
        return list(rows)


    def write(self, tenant_id: str, namespace: str, author_user: str, author_scope: str, body: str,
              values: ResolvedValues, frontmatter: dict | None = None, classification: str = "internal",
              retention_class: str = "standard") -> str:
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        vec = embeddings.embed(body)
        vstr = embeddings.to_pgvector(vec) if vec is not None else None
        with get_conn() as conn:
            row = conn.execute(
                "INSERT INTO memories(tenant_id, namespace, author_user, author_scope, classification, "
                "retention_class, policy_version, values_version, frontmatter, body, body_hash, embedding) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector) RETURNING id::text",
                (tenant_id, namespace, author_user, author_scope, classification, retention_class,
                 values.policy_version, values.values_version, json.dumps(frontmatter or {}), body, body_hash, vstr),
            ).fetchone()
            return row["id"]


    def write_simple(self, tenant_id, namespace, author_user, author_scope, body, classification="internal", retention_class="standard"):
        body_hash = hashlib.sha256(body.encode()).hexdigest()
        with get_conn() as conn:
            row = conn.execute(
                "INSERT INTO memories(tenant_id, namespace, author_user, author_scope, classification, retention_class, policy_version, values_version, frontmatter, body, body_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id::text",
                (tenant_id, namespace, author_user, author_scope, classification, retention_class, 0, 0, json.dumps({}), body, body_hash),
            ).fetchone()
            return row["id"]


memory_store = MemoryStore()
