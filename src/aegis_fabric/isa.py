"""ISA (Ideal State Artifact) — the per-task "definition of done" record.

Each non-trivial chat task scaffolds an ISA at OBSERVE: a Goal (one heuristic sentence derived from
the prompt) plus a small list of atomic, binary Ideal State Criteria (ISCs). After the model
answers, VERIFY runs a deterministic probe for each ISC and stamps satisfied + evidence. The result
is persisted, returned in the chat response, and audited as isa.verify + per-criterion isc.verify
events so the agent's claim of "done" is *measurable*, not just generated."""
from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field

from .inspectors import inspect as inspector_inspect
from .logging_config import get_logger

logger = get_logger("aegis.isa")


@dataclass
class ISC:
    id: str
    description: str
    probe: str
    satisfied: bool = False
    evidence: str = ""


@dataclass
class ISA:
    trace_id: str
    tenant_id: str
    subject: str
    goal: str
    iscs: list[ISC] = field(default_factory=list)
    verified: bool = False

    @property
    def total(self) -> int:
        return len(self.iscs)

    @property
    def met(self) -> int:
        return sum(1 for c in self.iscs if c.satisfied)

    def to_dict(self) -> dict:
        return {
            "trace_id": self.trace_id, "tenant_id": self.tenant_id, "subject": self.subject,
            "goal": self.goal, "verified": self.verified, "total": self.total, "met": self.met,
            "iscs": [asdict(c) for c in self.iscs],
        }


# --- scaffold --------------------------------------------------------------
def _trim(s: str, n: int = 180) -> str:
    s = (s or "").strip()
    return s if len(s) <= n else s[: n - 1] + "..."


def scaffold_isa(trace_id: str, tenant_id: str, subject: str, prompt: str,
                 *, doc_q: bool, max_output_tokens: int) -> ISA:
    """Generate the default chat-task ISA: a heuristic Goal and a deterministic core of ISCs.
    Custom ISCs per skill can be appended in later slices without changing the verify contract."""
    goal = f"Answer the user's question: {_trim(prompt)}"
    iscs = [
        ISC(id="ISC-1", description="Answer is non-empty.", probe="non_empty_answer"),
        ISC(id="ISC-2",
            description=f"Answer fits within the role's output token budget ({max_output_tokens}).",
            probe="within_output_token_budget"),
        ISC(id="ISC-3",
            description="Answer does not echo prompt-injection patterns back to the user.",
            probe="no_injection_in_answer"),
        ISC(id="ISC-4",
            description="Answer does not leak credential-like strings.",
            probe="no_credential_in_answer"),
    ]
    if doc_q:
        iscs.append(ISC(
            id="ISC-5",
            description="When the question is document-related, the answer cites an authorized document.",
            probe="cites_doc_when_doc_q",
        ))
    return ISA(trace_id=trace_id, tenant_id=tenant_id, subject=subject, goal=goal, iscs=iscs)


# --- probes ----------------------------------------------------------------
def _est_tokens(s: str) -> int:
    return max(1, len(s or "") // 4)


_CRED_RX = re.compile(
    r"sk-ant-|sk-proj-|nvapi-|sk_live_|sk_test_|whsec_|-----BEGIN [A-Z ]*PRIVATE KEY-----"
)


def _probe(name: str, answer: str, ctx: dict) -> tuple[bool, str]:
    if name == "non_empty_answer":
        ok = bool(answer and answer.strip())
        return ok, ("non-empty" if ok else "answer is empty")
    if name == "within_output_token_budget":
        budget = int(ctx.get("max_output_tokens") or 0) or 999_999
        est = _est_tokens(answer)
        return est <= budget, f"estimated {est} tokens vs budget {budget}"
    if name == "no_injection_in_answer":
        r, _ = inspector_inspect("external_content", answer or "", tenant_id=ctx.get("tenant_id"))
        if r.action == "deny":
            return False, f"inspector flagged: {r.reason}"
        return True, "no injection patterns detected"
    if name == "no_credential_in_answer":
        m = _CRED_RX.search(answer or "")
        if m:
            return False, f"credential-like pattern: {m.group(0)[:12]}..."
        return True, "no credential patterns"
    if name == "cites_doc_when_doc_q":
        retrieved = ctx.get("retrieved_docs") or []
        if not retrieved:
            return True, "no documents retrieved; criterion vacuous"
        titles = [d.get("title") for d in retrieved if d.get("title")]
        a = (answer or "").lower()
        for t in titles:
            if t and t.lower() in a:
                return True, f"cites: {t}"
        return False, f"none of the {len(titles)} retrieved documents are cited in the answer"
    return True, f"unknown probe '{name}' (passing by default)"


def verify_isa(isa: ISA, answer: str, ctx: dict) -> ISA:
    """Run each ISC's probe; stamp satisfied + evidence. Never raises -- a probe error counts as
    not satisfied with the error as evidence."""
    for isc in isa.iscs:
        try:
            ok, evidence = _probe(isc.probe, answer, ctx)
            isc.satisfied, isc.evidence = ok, evidence
        except Exception as e:  # noqa: BLE001
            isc.satisfied, isc.evidence = False, f"probe error: {e}"
            logger.warning("ISC %s probe %s error: %s", isc.id, isc.probe, e)
    isa.verified = True
    return isa


# --- persistence -----------------------------------------------------------
def save_isa(isa: ISA) -> None:
    from .db import get_conn
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO isas(trace_id, tenant_id, subject, goal, iscs, verified, total, met) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (trace_id) DO UPDATE SET "
            "iscs=EXCLUDED.iscs, verified=EXCLUDED.verified, total=EXCLUDED.total, met=EXCLUDED.met",
            (isa.trace_id, isa.tenant_id, isa.subject, isa.goal,
             json.dumps([asdict(c) for c in isa.iscs]),
             isa.verified, isa.total, isa.met),
        )
