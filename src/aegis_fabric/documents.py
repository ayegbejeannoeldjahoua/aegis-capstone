"""Per-tenant document store (MongoDB), governed by the same capability model as
everything else: a document is visible to a role only if its `team` is in the
role's readable_namespaces AND its `classification` is within the role's read
ceiling. Physical isolation: one Mongo database per tenant (``aegis_<tenant_id>``).
Fails OPEN/empty if Mongo is unavailable so the chat never breaks.
"""
from __future__ import annotations

from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.documents")

CLASSES = ["public", "internal", "confidential", "restricted"]


def _filter(namespaces, classifications, query: str | None) -> dict:
    """Mongo filter encoding the governance rule: team in the role's namespaces and
    classification within the role's read ceiling (+ optional keyword match)."""
    f: dict = {"team": {"$in": list(namespaces)}, "classification": {"$in": list(classifications)}}
    if query:
        f["$or"] = [{"title": {"$regex": query, "$options": "i"}},
                    {"body": {"$regex": query, "$options": "i"}}]
    return f


def default_corpus(tenant_id: str, teams: list[str]) -> list[dict]:
    """A synthetic corpus: one document per (team x classification) so every access
    boundary is exercisable."""
    docs = []
    for team in teams:
        for cls in CLASSES:
            docs.append({
                "doc_id": f"{tenant_id}:{team}:{cls}",
                "title": f"{team.title()} {cls} brief",
                "team": team, "classification": cls,
                "body": (f"{cls.upper()} document for the {team} team of {tenant_id}. "
                         f"Marker {team.upper()}_{cls.upper()}. Synthetic test content used to verify "
                         f"that governance only surfaces documents a role is permitted to read."),
            })
    return docs


class DocumentStore:
    def __init__(self) -> None:
        self._client = None

    @property
    def enabled(self) -> bool:
        return settings.docs_enabled

    def _coll(self, tenant_id: str):
        import pymongo  # imported lazily so the package imports without pymongo

        if self._client is None:
            self._client = pymongo.MongoClient(settings.mongo_url, serverSelectionTimeoutMS=1500)
        return self._client[f"aegis_{tenant_id}"]["documents"]

    def provision(self, tenant_id: str) -> bool:
        if not self.enabled:
            return False
        try:
            self._coll(tenant_id).create_index([("team", 1), ("classification", 1)])
            return True
        except Exception as e:  # noqa: BLE001
            logger.warning("doc provision failed for %s: %s", tenant_id, e)
            return False

    def seed(self, tenant_id: str, docs: list[dict]) -> int:
        if not self.enabled:
            return 0
        try:
            coll = self._coll(tenant_id)
            for d in docs:
                coll.update_one({"doc_id": d["doc_id"]}, {"$set": d}, upsert=True)
            return len(docs)
        except Exception as e:  # noqa: BLE001
            logger.warning("doc seed failed for %s: %s", tenant_id, e)
            return 0

    def count(self, tenant_id: str) -> int:
        try:
            return int(self._coll(tenant_id).count_documents({}))
        except Exception:  # noqa: BLE001
            return 0

    def search(self, tenant_id: str, query: str | None, namespaces, classifications, limit: int = 5) -> list[dict]:
        """Governed retrieval: only docs whose team is in `namespaces` and whose
        classification is in `classifications` (the caller's readable set)."""
        if not self.enabled or not namespaces or not classifications:
            return []
        try:
            cur = self._coll(tenant_id).find(_filter(namespaces, classifications, query), {"_id": 0}).limit(int(limit))
            return list(cur)
        except Exception as e:  # noqa: BLE001
            logger.warning("doc search failed for %s: %s", tenant_id, e)
            return []


document_store = DocumentStore()
