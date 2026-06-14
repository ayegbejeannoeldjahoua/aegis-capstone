#!/usr/bin/env python3
"""SAF reference MCP stdio server (services/demo_mcp, v1.23.0).

Spec-compliant Model Context Protocol stdio server: receives JSON-RPC 2.0
messages on stdin, emits responses on stdout, one JSON object per line.
Implements the MCP handshake (initialize + notifications/initialized),
tools/list, tools/call, ping, and the standard JSON-RPC error codes.

Exposes two demo tools so the SAF mcp_gateway has a real, working backend to
exercise end-to-end without depending on an external package:

  pubmed_search(query, max_results=5)  -> list of paper stubs
  kb_query(query)                      -> string echo with a 'note' field

Run standalone for debugging:

    echo '{"jsonrpc":"2.0","id":1,"method":"tools/list","params":{}}' \\
      | python -m services.demo_mcp.server

In SAF this is spawned by mcp_gateway via mcp_client.MCPStdioClient.
"""
from __future__ import annotations

import json
import sys
from typing import Any

PROTOCOL_VERSION = "2025-03-26"
SERVER_NAME = "saf-demo-mcp"
SERVER_VERSION = "1.0.0"

# JSON-RPC error codes (RFC equivalents)
PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603

TOOLS: list[dict[str, Any]] = [
    {
        "name": "pubmed_search",
        "description": "Search PubMed for biomedical papers matching a query.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search terms"},
                "max_results": {"type": "integer", "default": 5, "minimum": 1, "maximum": 50},
            },
            "required": ["query"],
        },
    },
    {
        "name": "kb_query",
        "description": "Look up an internal KB note by free-text query.",
        "inputSchema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
    },
]


def _result(req_id: Any, value: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": value}


def _error(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _tool_pubmed_search(args: dict[str, Any]) -> dict[str, Any]:
    q = args.get("query", "")
    n = max(1, min(50, int(args.get("max_results", 5))))
    items = [
        {"pmid": f"99{i:05d}", "title": f"Stub result {i} for '{q}'",
         "year": 2025 - (i % 3), "abstract": "Demo abstract."}
        for i in range(n)
    ]
    return {"content": [{"type": "text",
                          "text": json.dumps({"query": q, "count": n, "items": items})}]}


def _tool_kb_query(args: dict[str, Any]) -> dict[str, Any]:
    q = args.get("query", "")
    return {"content": [{"type": "text",
                          "text": json.dumps({"query": q, "match": "demo", "note": "echo"})}]}


_DISPATCH = {"pubmed_search": _tool_pubmed_search, "kb_query": _tool_kb_query}


def handle(message: dict[str, Any]) -> dict[str, Any] | None:
    method = message.get("method")
    req_id = message.get("id")
    params = message.get("params") or {}

    # Notifications carry no id and expect no response.
    if method == "notifications/initialized":
        return None
    if method == "initialize":
        return _result(req_id, {
            "protocolVersion": PROTOCOL_VERSION,
            "serverInfo": {"name": SERVER_NAME, "version": SERVER_VERSION},
            "capabilities": {"tools": {}},
        })
    if method == "ping":
        return _result(req_id, {})
    if method == "tools/list":
        return _result(req_id, {"tools": TOOLS})
    if method == "tools/call":
        name = params.get("name")
        if name not in _DISPATCH:
            return _error(req_id, METHOD_NOT_FOUND, f"tool not found: {name}")
        try:
            return _result(req_id, _DISPATCH[name](params.get("arguments") or {}))
        except Exception as e:  # noqa: BLE001
            return _error(req_id, INTERNAL_ERROR, f"tool error: {e}")
    return _error(req_id, METHOD_NOT_FOUND, f"unknown method: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError as e:
            sys.stdout.write(json.dumps(_error(None, PARSE_ERROR, str(e))) + "\n")
            sys.stdout.flush()
            continue
        resp = handle(msg)
        if resp is not None:
            sys.stdout.write(json.dumps(resp) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
