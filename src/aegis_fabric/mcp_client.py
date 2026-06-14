"""MCP stdio client (v1.23.0).

Production JSON-RPC 2.0 client that speaks to an MCP server over the
subprocess's stdin/stdout. Handles the MCP handshake (initialize +
notifications/initialized), tools/list, tools/call, ping, and per-call
timeouts. Maps server-side errors to a small Python exception hierarchy so
the gateway can react sensibly.

Lifecycle is intentionally minimal in this slice -- the supervisor +
circuit breaker land in v1.24, the HTTP transport in v1.25. v1.23 ships
the spawn-call-shut-down path the gateway needs to make `tools/call` work
end-to-end.
"""
from __future__ import annotations

import json
import subprocess
import threading
from dataclasses import dataclass, field
from typing import Any

PROTOCOL_VERSION = "2025-03-26"
CLIENT_NAME = "aegis-mcp-client"
CLIENT_VERSION = "1.0.0"


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

class MCPError(Exception):
    """Base class for client-visible MCP failures."""


class MCPHandshakeError(MCPError):
    """initialize / notifications/initialized failed."""


class MCPTransportError(MCPError):
    """The subprocess died or stdio I/O failed."""


class MCPRemoteError(MCPError):
    """The MCP server returned a JSON-RPC error."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(f"[{code}] {message}")
        self.code = code
        self.message = message
        self.data = data


# ---------------------------------------------------------------------------
# Launch config
# ---------------------------------------------------------------------------

@dataclass
class LaunchConfig:
    """How to spawn an MCP server process."""
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    startup_timeout_s: float = 10.0
    call_timeout_s: float = 30.0


# ---------------------------------------------------------------------------
# Client
# ---------------------------------------------------------------------------

class MCPStdioClient:
    """One subprocess per client instance. Not safe to share across threads.

    Typical use:

        client = MCPStdioClient(LaunchConfig(command="python", args=["-m", "demo_mcp.server"]))
        client.start()
        tools = client.list_tools()
        out = client.call_tool("pubmed_search", {"query": "RAG"})
        client.close()
    """

    def __init__(self, cfg: LaunchConfig) -> None:
        self.cfg = cfg
        self._proc: subprocess.Popen[str] | None = None
        self._next_id = 0
        self._lock = threading.Lock()

    # -- lifecycle -----------------------------------------------------------

    def start(self) -> dict[str, Any]:
        """Spawn the subprocess and perform the MCP initialize handshake.
        Returns the server's initialize result (protocolVersion, serverInfo, ...)."""
        if self._proc is not None:
            raise MCPError("client already started")
        try:
            self._proc = subprocess.Popen(
                [self.cfg.command, *self.cfg.args],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, bufsize=1, env={**self.cfg.env} if self.cfg.env else None,
                cwd=self.cfg.cwd,
            )
        except (OSError, ValueError) as e:
            raise MCPTransportError(f"spawn failed: {e}") from e

        try:
            init_result = self._request("initialize", {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": CLIENT_NAME, "version": CLIENT_VERSION},
            }, timeout_s=self.cfg.startup_timeout_s)
        except MCPRemoteError as e:
            self.close()
            raise MCPHandshakeError(f"initialize rejected: {e.message}") from e
        except MCPTransportError:
            self.close()
            raise

        # Send the post-initialize notification (no id, no response expected).
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return init_result

    def close(self) -> None:
        if self._proc is None:
            return
        try:
            if self._proc.stdin and not self._proc.stdin.closed:
                self._proc.stdin.close()
        except Exception:  # noqa: BLE001
            pass
        try:
            self._proc.terminate()
            try:
                self._proc.wait(timeout=2.0)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=2.0)
        except Exception:  # noqa: BLE001
            pass
        self._proc = None

    # -- API -----------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        result = self._request("tools/list", {}, timeout_s=self.cfg.call_timeout_s)
        return result.get("tools", [])

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None,
                  *, timeout_s: float | None = None) -> dict[str, Any]:
        return self._request("tools/call",
                             {"name": name, "arguments": arguments or {}},
                             timeout_s=timeout_s or self.cfg.call_timeout_s)

    def ping(self) -> None:
        self._request("ping", {}, timeout_s=self.cfg.call_timeout_s)

    # -- transport -----------------------------------------------------------

    def _request(self, method: str, params: dict[str, Any],
                 *, timeout_s: float) -> dict[str, Any]:
        with self._lock:
            self._next_id += 1
            req_id = self._next_id
            msg = {"jsonrpc": "2.0", "id": req_id, "method": method, "params": params}
            self._send(msg)
            return self._recv_response(req_id, timeout_s=timeout_s)

    def _send(self, msg: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None:
            raise MCPTransportError("client not started")
        try:
            self._proc.stdin.write(json.dumps(msg, separators=(",", ":")) + "\n")
            self._proc.stdin.flush()
        except (BrokenPipeError, OSError) as e:
            raise MCPTransportError(f"send failed: {e}") from e

    def _recv_response(self, req_id: int, *, timeout_s: float) -> dict[str, Any]:
        if self._proc is None or self._proc.stdout is None:
            raise MCPTransportError("client not started")
        # Simple synchronous read loop; the supervisor in v1.24 introduces an
        # async reader thread + correlation map.
        import select
        deadline = _now() + timeout_s
        while True:
            remaining = max(0.0, deadline - _now())
            r, _w, _x = select.select([self._proc.stdout], [], [], min(remaining, 0.5))
            if not r:
                if _now() >= deadline:
                    raise MCPTransportError(f"timeout waiting for id={req_id}")
                if self._proc.poll() is not None:
                    raise MCPTransportError(f"process exited (code={self._proc.returncode}) before response")
                continue
            line = self._proc.stdout.readline()
            if line == "":
                raise MCPTransportError("stdout closed before response")
            line = line.strip()
            if not line:
                continue
            try:
                msg = json.loads(line)
            except json.JSONDecodeError as e:
                raise MCPTransportError(f"server emitted non-JSON: {e}") from e
            # MCP messages can be requests, notifications, or responses; we
            # only care about responses with our id. Other ids are queued
            # implicitly by the synchronous lock.
            if msg.get("id") != req_id:
                continue
            if "error" in msg:
                err = msg["error"]
                raise MCPRemoteError(err.get("code", -32000),
                                     err.get("message", "unknown"),
                                     data=err.get("data"))
            return msg.get("result") or {}


def _now() -> float:
    import time
    return time.monotonic()
