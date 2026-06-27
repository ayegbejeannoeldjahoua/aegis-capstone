"""Security inspector pipeline (ported from PAI's Goose-inspired ToolInspector pattern, v1.18.0).

A composable chain of inspectors evaluates content at three stages -- the user prompt, each tool
call, and any external/tool/RAG content before it enters the model prompt. Each inspector returns
allow / deny / require_approval / alert. The pipeline runs inspectors in priority order, SHORT-
CIRCUITS on the first deny, otherwise surfaces the strongest finding. This is defense-in-depth on
top of the OPA PDP: OPA governs *whether a role may* call a tool/read data; inspectors govern
*whether the actual content/command is safe* (prompt injection, secret exfiltration, dangerous
commands). Findings are emitted to the audit log by the caller (see skill_runner)."""
from __future__ import annotations

import re
import time
from dataclasses import dataclass
from typing import Literal

from .logging_config import get_logger
from .settings import settings

logger = get_logger("aegis.inspectors")

InspectionAction = Literal["allow", "deny", "require_approval", "alert"]


@dataclass
class InspectionResult:
    action: InspectionAction = "allow"
    reason: str = ""
    finding_id: str = ""
    inspector: str = ""


ALLOW = InspectionResult(action="allow")


def deny(reason: str, finding_id: str = "") -> InspectionResult:
    return InspectionResult(action="deny", reason=reason, finding_id=finding_id)


def require_approval(reason: str, finding_id: str = "") -> InspectionResult:
    return InspectionResult(action="require_approval", reason=reason, finding_id=finding_id)


def alert(reason: str, finding_id: str = "") -> InspectionResult:
    return InspectionResult(action="alert", reason=reason, finding_id=finding_id)


@dataclass
class InspectionContext:
    stage: str  # "user_prompt" | "tool_call" | "external_content"
    text: str = ""
    tool_id: str | None = None
    args: dict | None = None
    egress_domain: str | None = None
    tenant_id: str | None = None


class Inspector:
    name = "base"
    priority = 0

    def inspect(self, ctx: InspectionContext) -> InspectionResult:  # noqa: ARG002
        return ALLOW


# --- PatternInspector: dangerous command patterns (priority 100) -----------------
_DANGEROUS = [
    (re.compile(r"\brm\s+-rf\s+[~/]"), "rm-rf-root", "recursive delete of a root/home path"),
    (re.compile(r"\bmkfs\.\w+\b"), "mkfs", "filesystem format"),
    (re.compile(r"\bdd\s+.*of=/dev/"), "dd-to-device", "raw write to a block device"),
    (re.compile(r":\(\)\s*\{\s*:\|:&\s*\};:"), "fork-bomb", "shell fork bomb"),
    (re.compile(r"\bchmod\s+-R\s+0?777\s+/"), "chmod-777-root", "world-writable root"),
    (re.compile(r"\b(curl|wget)\b[^|]*\|\s*(sudo\s+)?(bash|sh)\b"), "pipe-to-shell", "download piped to a shell"),
]


class PatternInspector(Inspector):
    name = "PatternInspector"
    priority = 100

    def inspect(self, ctx: InspectionContext) -> InspectionResult:
        for rx, fid, desc in _DANGEROUS:
            if rx.search(ctx.text):
                return deny(f"dangerous command: {desc}", f"SEC-pattern-{fid}")
        return ALLOW


# --- EgressInspector: secret exfiltration + outbound data (priority 90) ----------
_OUTBOUND_TOOLS = re.compile(r"\b(curl|wget|nc|ncat|socat|fetch|sendmail)\b", re.I)
_CREDENTIALS = [
    (re.compile(r"sk-ant-"), "Anthropic API key"),
    (re.compile(r"sk-proj-"), "OpenAI project key"),
    (re.compile(r"nvapi-"), "NVIDIA API key"),
    (re.compile(r"sk_live_|sk_test_"), "Stripe key"),
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"), "private key material"),
    (re.compile(r"\bwhsec_"), "webhook secret"),
    (re.compile(r"\b[A-Za-z0-9_-]*(password|secret|token)\s*[:=]\s*\S{6,}", re.I), "inline credential"),
]
_EGRESS_ALERTS = [
    (re.compile(r"curl.*(-X\s*POST|--data|\s-d\s)", re.I), "HTTP POST via curl"),
    (re.compile(r"wget.*(--post-data|--post-file)", re.I), "HTTP POST via wget"),
    (re.compile(r"\b(python3?|node|ruby)\s+-(c|e)\s", re.I), "inline interpreter execution"),
    (re.compile(r"^\s*(printenv|env|set)\s*$", re.I), "environment variable dump"),
]


class EgressInspector(Inspector):
    name = "EgressInspector"
    priority = 90

    def inspect(self, ctx: InspectionContext) -> InspectionResult:
        text = ctx.text
        # Credentials heading outbound are a hard block (exfiltration).
        if _OUTBOUND_TOOLS.search(text) or ctx.egress_domain:
            for rx, label in _CREDENTIALS:
                if rx.search(text):
                    return deny(f"possible credential exfiltration: {label}", "SEC-egress-credential")
        # Any credential pattern at all is at least worth flagging.
        for rx, label in _CREDENTIALS:
            if rx.search(text):
                return alert(f"credential-like string present: {label}", "SEC-egress-credential-present")
        for rx, label in _EGRESS_ALERTS:
            if rx.search(text):
                return alert(f"outbound/exec pattern: {label}", "SEC-egress-pattern")
        return ALLOW


# --- InjectionInspector: prompt-injection patterns (priority 80) -----------------
_INJECTION = [
    (re.compile(r"ignore\s+(all\s+)?previous\s+instructions", re.I), "instruction_override"),
    (re.compile(r"disregard\s+(all\s+)?(prior|previous|above)", re.I), "instruction_override"),
    (re.compile(r"forget\s+(everything|what|all|your)\s+(you\s+)?(were|know|previous)", re.I), "instruction_override"),
    (re.compile(r"your\s+new\s+instructions\s+are", re.I), "instruction_override"),
    (re.compile(r"you\s+are\s+now\s+in\s+\w+\s+mode", re.I), "instruction_override"),
    (re.compile(r"system\s+override\s*[:\s]", re.I), "system_impersonation"),
    (re.compile(r"\[(SYSTEM|ADMIN)\]\s*:", re.I), "system_impersonation"),
    (re.compile(r"admin\s+command\s*[:\s]", re.I), "system_impersonation"),
    (re.compile(r"maintenance\s+mode\s*[:\s]", re.I), "system_impersonation"),
    (re.compile(r"send\s+(your|the|all)\s+(config|credentials|secrets|keys|tokens)\s+to", re.I), "exfiltration"),
    (re.compile(r"exfiltrate|upload\s+(your|the)\s+(data|config|secrets)", re.I), "exfiltration"),
    (re.compile(r"disable\s+(all\s+)?(security|logging|monitoring|protection)", re.I), "dangerous_action"),
    (re.compile(r"<!--\s*(ignore|forget|system|admin|override|execute|delete|you\s+must)", re.I), "hidden_instruction"),
    (re.compile(r"display\s*:\s*none", re.I), "hidden_instruction"),
]
# These categories are treated as hard blocks when they appear in EXTERNAL content.
_HARD_CATEGORIES = {"exfiltration", "dangerous_action", "system_impersonation"}


class InjectionInspector(Inspector):
    name = "InjectionInspector"
    priority = 80

    def inspect(self, ctx: InspectionContext) -> InspectionResult:
        for rx, category in _INJECTION:
            if rx.search(ctx.text):
                # External content carrying an attack pattern is dropped (deny); a softer category
                # is an alert. The user-prompt stage downgrades everything to advisory in the caller.
                # Hard-deny stages: any content that is concatenated into a
                # higher-trust position than the user message itself
                # (system-prompt fragments, retrieved memories, tool outputs).
                # Injection there directly overrides governance, so any
                # category triggers a deny rather than just an alert.
                if category in _HARD_CATEGORIES or ctx.stage in ("external_content", "values_cascade"):
                    return deny(f"prompt injection ({category})", f"SEC-injection-{category}")
                return alert(f"prompt injection ({category})", f"SEC-injection-{category}")
        return ALLOW


class InspectorPipeline:
    def __init__(self, inspectors: list[Inspector]):
        self.inspectors = sorted(inspectors, key=lambda i: i.priority, reverse=True)

    def run(self, ctx: InspectionContext) -> tuple[InspectionResult, list[InspectionResult]]:
        findings: list[InspectionResult] = []
        pending: InspectionResult | None = None
        for ins in self.inspectors:
            try:
                r = ins.inspect(ctx)
            except Exception as e:  # noqa: BLE001 -- an inspector error must not break the request
                logger.warning("inspector %s error: %s", ins.name, e)
                continue
            if r.action == "allow":
                continue
            r.inspector = ins.name
            findings.append(r)
            if r.action == "deny":
                return r, findings  # short-circuit
            if r.action == "require_approval" and pending is None:
                pending = r
        if pending is not None:
            return pending, findings
        if findings:
            return findings[-1], findings  # strongest remaining (alert)
        return ALLOW, findings


_PIPELINE: InspectorPipeline | None = None


def default_pipeline() -> InspectorPipeline:
    return InspectorPipeline([PatternInspector(), EgressInspector(), InjectionInspector()])


def get_pipeline() -> InspectorPipeline:
    global _PIPELINE
    if _PIPELINE is None:
        _PIPELINE = default_pipeline()
    return _PIPELINE


def inspect(stage, text, *, tool_id=None, args=None, egress_domain=None, tenant_id=None):
    start = time.perf_counter()
    ctx = InspectionContext(stage=stage, text=text or "", tool_id=tool_id, args=args or {}, egress_domain=egress_domain, tenant_id=tenant_id)
    result, findings = get_pipeline().run(ctx)
    try:
        from . import operational_metrics

        operational_metrics.record_security_findings((time.perf_counter() - start) * 1000.0, findings)
    except Exception:
        pass
    return result, findings
