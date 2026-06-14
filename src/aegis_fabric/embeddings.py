"""Embedding provider for semantic memory.

In-process sentence-transformers backend (default model: all-mpnet-base-v2,
768-dim) so the platform does semantic RAG out of the box without depending
on an external Ollama / OpenAI service. The model is lazy-loaded on first
call to keep import-time cheap and gets baked into the api docker image at
build time (see Dockerfile.api) so first-query latency is just the local
forward pass (~150 ms on CPU).

Falls back to None (-> keyword search) when:
  - settings.embed_enabled is False
  - the model fails to load (no model files, no network during lazy fetch)
  - the input text is empty
  - the produced vector's dim doesn't match the pgvector column width
"""
from __future__ import annotations

from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.embeddings")

_MODEL = None          # lazy-init SentenceTransformer instance
_MODEL_FAILED = False  # one-shot fail flag so we don't retry on every call


def enabled() -> bool:
    return settings.embed_enabled


def _get_model():
    """Load the sentence-transformers model once. Returns None if unavailable."""
    global _MODEL, _MODEL_FAILED
    if _MODEL is not None:
        return _MODEL
    if _MODEL_FAILED:
        return None
    try:
        from sentence_transformers import SentenceTransformer
        _MODEL = SentenceTransformer(settings.embed_model)
        logger.info("embedder_loaded model=%s dim=%d",
                    settings.embed_model, settings.embed_dim)
        return _MODEL
    except Exception as e:
        logger.warning("embedder_load_failed model=%s err=%s; falling back to keyword search",
                       settings.embed_model, e)
        _MODEL_FAILED = True
        return None


def embed(text: str) -> list[float] | None:
    """Return an embedding vector, or None to signal 'use keyword search'."""
    if not settings.embed_enabled or not text:
        return None
    model = _get_model()
    if model is None:
        return None
    try:
        vec = model.encode(text[:8000], normalize_embeddings=True).tolist()
    except Exception as e:
        logger.warning("embedding_call_failed; falling back to keyword: %s", e)
        return None
    if not vec:
        return None
    if len(vec) != settings.embed_dim:
        logger.warning("embedding_dim_mismatch %d != configured %d; ignoring",
                       len(vec), settings.embed_dim)
        return None
    return vec


def to_pgvector(vec: list[float]) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
