"""Presidio-based PII detection + anonymization.

The runtime call sites (tools.redact_text, tools.mask_memories) prefer this
module's `redact()` when Presidio is installed and importable; otherwise they
fall back to the legacy regex redactor in tools.py.

Why Presidio: regex catches emails / phones / SSN well enough, but loses
person names, addresses, organisations, dates of birth, locations, and credit
cards. Presidio's NER (en_core_web_sm) plus its built-in recognisers cover
those without hand-rolling regex for every shape.

Gated by access level: the caller (skill_runner / workflow) decides whether to
invoke this based on the role's `pii_scope`:
  - "none"   : PDP already denied PII reads; never invoked
  - "masked" : redact() called; replacements written into the memory bodies
  - "full"   : redact() not called; memories pass through verbatim
"""
from __future__ import annotations
from typing import Any
from .logging_config import get_logger

logger = get_logger("aegis.pii_presidio")

_ANALYZER = None
_ANONYMIZER = None
_INIT_FAILED = False

# Entities Presidio will look for. Drop or extend as your demo evolves.
# Drop ORGANIZATION — spaCy en_core_web_sm has no Presidio recognizer for it
# (emits noisy "Entity ORGANIZATION doesn't have the corresponding recognizer"
# warnings on every call). PERSON / LOCATION cover the demo PII surface.
# NOTE: URL is deliberately excluded — Presidio's URL recognizer eagerly
# matches the local-part of email addresses (e.g. marcus.lee.synthetic)
# BEFORE the EMAIL_ADDRESS recognizer can fire, leaving "[URL]@example.com"
# instead of "[EMAIL]". A regex sweep after analyze() picks up genuine URLs.
DEFAULT_ENTITIES = [
    "PERSON", "EMAIL_ADDRESS", "PHONE_NUMBER", "US_SSN",
    "CREDIT_CARD", "IBAN_CODE", "IP_ADDRESS", "LOCATION",
    "DATE_TIME", "NRP",
    "US_BANK_NUMBER", "US_DRIVER_LICENSE", "US_PASSPORT",
]

# Belt-and-suspenders regex sweep run AFTER Presidio anonymize. Catches:
# - emails Presidio dropped (e.g. when URL ate the local part)
# - the +1-555-XXXX-XXXX phone format with 4-digit middle group
# - any remaining SSN / card / IP / URL the NER missed
_FALLBACK_REGEX = [
    (r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", "[EMAIL]"),
    (r"\+?\d{1,3}[-\s.]?\d{3}[-\s.]?\d{3,4}[-\s.]?\d{3,4}", "[PHONE]"),
    (r"\b\d{3}-\d{2}-\d{4}\b", "[SSN]"),
    (r"\b(?:\d[ -]?){13,16}\b", "[CARD]"),
    (r"\b\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\b", "[IP]"),
    (r"https?://[^\s]+", "[URL]"),
]

# Replacement template per entity — bracketed token tells the model what
# was masked without leaking the value.
REPLACEMENT = {
    "PERSON":         "[PERSON]",
    "EMAIL_ADDRESS":  "[EMAIL]",
    "PHONE_NUMBER":   "[PHONE]",
    "US_SSN":         "[SSN]",
    "CREDIT_CARD":    "[CARD]",
    "IBAN_CODE":      "[IBAN]",
    "IP_ADDRESS":     "[IP]",
    "LOCATION":       "[LOCATION]",
    "DATE_TIME":      "[DATE]",
    "URL":            "[URL]",
    "ORGANIZATION":   "[ORG]",
    "NRP":            "[NRP]",
}


def _init() -> bool:
    """Initialise the analyzer + anonymizer once. Returns False if Presidio
    isn't available, so callers can fall back to the regex redactor."""
    global _ANALYZER, _ANONYMIZER, _INIT_FAILED
    if _ANALYZER is not None and _ANONYMIZER is not None:
        return True
    if _INIT_FAILED:
        return False
    try:
        from presidio_analyzer import AnalyzerEngine
        from presidio_anonymizer import AnonymizerEngine
        _ANALYZER = AnalyzerEngine()
        _ANONYMIZER = AnonymizerEngine()
        logger.info("presidio_initialised", extra={"entities": len(DEFAULT_ENTITIES)})
        return True
    except Exception as e:  # noqa: BLE001
        logger.warning("presidio_unavailable_falling_back_to_regex: %s", e)
        _INIT_FAILED = True
        return False


def is_available() -> bool:
    return _init()


def redact(text: str, entities: list[str] | None = None) -> str:
    """Replace PII spans in `text` with bracketed tokens. Falls back to the
    legacy regex redactor if Presidio cannot be initialised."""
    if not isinstance(text, str) or not text.strip():
        return text
    if not _init():
        from .tools import _redact as regex_redact
        return regex_redact({"text": text})["redacted"]
    try:
        ents = entities or DEFAULT_ENTITIES
        results = _ANALYZER.analyze(text=text, entities=ents, language="en")
        if not results:
            return text
        from presidio_anonymizer.entities import OperatorConfig
        operators = {
            ent: OperatorConfig("replace", {"new_value": REPLACEMENT.get(ent, f"[{ent}]")})
            for ent in {r.entity_type for r in results}
        }
        anonymized = _ANONYMIZER.anonymize(text=text, analyzer_results=results, operators=operators)
        out = anonymized.text
        # Safety net: regex sweep for entity types Presidio's NER missed or
        # mangled (e.g. URL fragment ate email's local part).
        import re as _re
        for _pat, _repl in _FALLBACK_REGEX:
            out = _re.sub(_pat, _repl, out)
        return out
    except Exception as e:
        logger.warning("presidio_redact_failed_falling_back: %s", e)
        from .tools import _redact as regex_redact
        return regex_redact({"text": text})["redacted"]


def redact_memories(memories: list[dict], pii_scope: str) -> list[dict]:
    """Same contract as tools.mask_memories but uses Presidio when present.
    Callers should still use tools.mask_memories - that function delegates to
    this one when Presidio is available."""
    if pii_scope != "masked":
        return memories
    out = []
    for m in memories:
        mm = dict(m)
        if isinstance(mm.get("body"), str):
            mm["body"] = redact(mm["body"])
        out.append(mm)
    return out
