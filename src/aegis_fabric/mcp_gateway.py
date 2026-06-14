"""MCP gateway (v1.22).

Private vetted registry of MCP servers. A server is only admitted if:

  1. The manifest carries a valid Ed25519 signature over the canonical tools
     bytes (BR-MCP-03 -- reuses the v1.6 skill-signing infra).
  2. The InjectionInspector approves every tool's description + parameters
     (BR-MCP-04 -- catches poisoned manifests before they reach the human
     approver).
  3. The dual-control queue records and a second platform admin approves
     (BR-SOD-02 -- no self-approval).

Tools are namespaced `server_id/tool_id` (BR-MCP-02), so the same tool name
across two servers cannot shadow. The PDP capability `tools.allow` references
the namespaced id.

This v1.22 slice is the GATEWAY (registry + verification + dual-control + UI).
Real subprocess invocation lands in v1.23; supervisor + circuit breaker in
v1.24; HTTP transport in v1.25.
"""
from __future__ import annotations

import base64
import hashlib
import json
from dataclasses import dataclass, field
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .inspectors import InspectionContext, InjectionInspector


# ---------------------------------------------------------------------------
# Data shapes
# ---------------------------------------------------------------------------

@dataclass
class ToolSpec:
    tool_id: str
    description: str
    parameters: dict = field(default_factory=dict)
    pii_class: str = "med"
    egress: str | None = None


@dataclass
class ServerManifest:
    server_id: str
    display_name: str
    version: str
    public_key: str          # base64 ed25519 public key
    signature: str           # base64 signature over _canonical_tools_bytes(tools)
    tools: list[ToolSpec] = field(default_factory=list)
    command: str | None = None
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    notes: str = ""


# ---------------------------------------------------------------------------
# Canonicalisation + signature verification
# ---------------------------------------------------------------------------

def _canonical_tools_bytes(tools: list[ToolSpec]) -> bytes:
    """Deterministic JSON encoding of the tools list. Both the signer and the
    verifier MUST compute identical bytes for any given set of tools, so this
    sorts and uses fixed separators."""
    arr = sorted(
        (
            {
                "tool_id": t.tool_id,
                "description": t.description,
                "parameters": t.parameters,
                "pii_class": t.pii_class,
                "egress": t.egress,
            }
            for t in tools
        ),
        key=lambda x: x["tool_id"],
    )
    return json.dumps(arr, sort_keys=True, separators=(",", ":")).encode()


def manifest_hash(m: ServerManifest) -> str:
    return hashlib.sha256(_canonical_tools_bytes(m.tools)).hexdigest()


def verify_signature(m: ServerManifest) -> bool:
    """Return True iff the manifest's signature is a valid Ed25519 signature
    over the canonical tools bytes by the supplied public key."""
    try:
        pub = Ed25519PublicKey.from_public_bytes(base64.b64decode(m.public_key))
        pub.verify(base64.b64decode(m.signature), _canonical_tools_bytes(m.tools))
        return True
    except (InvalidSignature, ValueError, TypeError):
        return False


# ---------------------------------------------------------------------------
# Inspector scan of tool descriptions + parameters
# ---------------------------------------------------------------------------

_INSPECTOR = InjectionInspector()


def _scan_tool(tool: ToolSpec) -> dict[str, Any]:
    """Run the InjectionInspector over the tool's description + parameters.
    Returns {"action": "allow|alert|deny", "findings": [...]}. The gateway
    refuses to register a server whose tools any have action=='deny'."""
    blob = f"{tool.description}\n{json.dumps(tool.parameters, sort_keys=True)}"
    ctx = InspectionContext(stage="tool_registration", text=blob, tool_id=tool.tool_id)
    res = _INSPECTOR.inspect(ctx)
    return {"action": res.action, "reason": getattr(res, "reason", "")}


def verify_manifest(m: ServerManifest) -> dict[str, Any]:
    """End-to-end gate: signature + per-tool injection scan + namespace
    expansion. Returns a verdict dict shape with `signature_ok`, `scan_ok`,
    `manifest_hash`, `namespace` (the namespaced tool ids), and `findings`
    (the per-tool inspection results)."""
    sig_ok = verify_signature(m)
    per_tool = {t.tool_id: _scan_tool(t) for t in m.tools}
    scan_ok = all(v["action"] != "deny" for v in per_tool.values())
    return {
        "signature_ok": sig_ok,
        "scan_ok": scan_ok,
        "manifest_hash": manifest_hash(m),
        "namespace": [f"{m.server_id}/{t.tool_id}" for t in m.tools],
        "per_tool": per_tool,
    }


# ---------------------------------------------------------------------------
# v1.23 -- real subprocess dispatch.
#
# Spawn-call-shutdown is the minimal pattern: one fresh process per tool
# invocation. The supervisor in v1.24 will introduce a per-server long-lived
# process + circuit breaker, but v1.23 already exercises the full client +
# stdio + handshake + tools/call path end-to-end.
# ---------------------------------------------------------------------------

from .db import get_conn  # noqa: E402
from .mcp_client import LaunchConfig, MCPStdioClient, MCPError  # noqa: E402


def _load_server_row(server_id: str) -> dict | None:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT server_id, status, command, args, env, cwd FROM mcp_servers WHERE server_id=%s",
            (server_id,),
        ).fetchone()
    return dict(row) if row else None


def call_tool(server_id: str, tool_id: str, arguments: dict | None = None,
              *, timeout_s: float | None = None) -> dict:
    """Spawn the registered server, run the MCP handshake, invoke
    tools/call(tool_id, arguments), shut down. Raises MCPError on any failure.
    The caller (skill_runner) is responsible for PDP gating + inspector scans
    of the input/output -- this function is just the transport."""
    row = _load_server_row(server_id)
    if not row:
        raise MCPError(f"server not registered: {server_id}")
    if row["status"] != "approved":
        raise MCPError(f"server '{server_id}' not approved (status={row['status']})")
    cfg = LaunchConfig(
        command=row["command"] or "python3",
        args=list(row["args"] or []),
        env=dict(row["env"] or {}),
        cwd=row.get("cwd"),
        call_timeout_s=timeout_s or 30.0,
    )
    client = MCPStdioClient(cfg)
    try:
        client.start()
        return client.call_tool(tool_id, arguments or {})
    finally:
        client.close()
