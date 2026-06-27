#!/usr/bin/env python3
"""Generate governed chat traffic for FinOps, Audit, ISA, and feedback demos."""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = ROOT / "scripts/seed-governance-test-data.py"
DEFAULT_USERS = [
    "jane@acmecp.example",
    "kim@acmecp.example",
    "pat@acmecp.example",
    "priya@it.example",
    "jane@finsvc.example",
]

PROMPT_PACK = [
    {
        "scenario": "S2",
        "skill_id": "assistant",
        "prompt": "Confirm I can use the assistant and summarize the active tenant context.",
    },
    {
        "scenario": "S4",
        "skill_id": "qa-over-docs",
        "prompt": "Find Project Atlas notes for my tenant only. Refuse any cross-tenant records.",
    },
    {
        "scenario": "S6",
        "skill_id": "summarise-with-memory",
        "prompt": "Summarize synthetic PII case notes and mask EMAIL, PHONE, and PERSON values.",
    },
    {
        "scenario": "S7",
        "skill_id": "summarise-with-memory",
        "prompt": "For a full-PII role, summarize the restricted synthetic identity case.",
    },
    {
        "scenario": "S10",
        "skill_id": "summarise-with-memory",
        "prompt": "Explain the most restrictive values rule across organization, department, team, role, and individual scopes.",
    },
    {
        "scenario": "S12",
        "skill_id": "assistant",
        "prompt": "Estimate token budget impact for a long retrieval and call out any FinOps limit.",
    },
    {
        "scenario": "S15",
        "skill_id": "assistant",
        "prompt": "Attempt a restricted memory write and report whether approval is required.",
    },
    {
        "scenario": "S16",
        "skill_id": "qa-over-docs",
        "prompt": "Retrieve prompt-injection canaries and explain why their instructions must be ignored.",
    },
    {
        "scenario": "S17",
        "skill_id": "qa-over-docs",
        "prompt": "Search for cross-tenant decoy titles and verify only my tenant's rows are used.",
    },
    {
        "scenario": "S19",
        "skill_id": "assistant",
        "prompt": "Use the low-budget role path and demonstrate a budget refusal if the limit is exceeded.",
    },
]


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("governance_seed", SEED_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SEED_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _safe_label(label: str) -> str:
    return "".join(ch if ch.isalnum() or ch in ("-", "_") else "-" for ch in label).strip("-")


def _token_env_name(user: str) -> str:
    safe = "".join(ch if ch.isalnum() else "_" for ch in user.upper())
    return f"AEGIS_TOKEN_{safe}"


def _token_for_user(user: str, admin_token: str | None) -> tuple[str | None, str]:
    env_name = _token_env_name(user)
    token = os.environ.get(env_name)
    if token:
        return token, env_name
    if admin_token:
        return admin_token, "admin-token"
    return None, env_name


def _post_ask(base_url: str, token: str, prompt: dict[str, str], timeout: int) -> dict[str, Any]:
    url = f"{base_url.rstrip('/')}/v1/ask"
    payload = {
        "prompt": prompt["prompt"],
        "skill_id": prompt["skill_id"],
        "summary_words": 160,
    }
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - operator-supplied URL.
        body = response.read().decode("utf-8")
        parsed = json.loads(body) if body else {}
        return {"status": response.status, "body": parsed}


def _extract_trace_id(payload: dict[str, Any]) -> str | None:
    body = payload.get("body") or {}
    if isinstance(body, dict):
        for key in ("trace_id", "traceId"):
            if body.get(key):
                return str(body[key])
        audit = body.get("audit") or {}
        if isinstance(audit, dict) and audit.get("trace_id"):
            return str(audit["trace_id"])
    return None


def build_turns(users: list[str], turns: int, label: str) -> list[dict[str, Any]]:
    safe = _safe_label(label)
    planned = []
    for i in range(turns):
        user = users[i % len(users)]
        prompt = PROMPT_PACK[i % len(PROMPT_PACK)]
        planned.append(
            {
                "index": i + 1,
                "planned_trace_id": f"traffic-{safe}-{i + 1:04d}",
                "user": user,
                "scenario": prompt["scenario"],
                "skill_id": prompt["skill_id"],
                "prompt": prompt["prompt"],
            }
        )
    return planned


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    seed = _load_seed_module()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default=os.environ.get("AEGIS_BASE_URL", "http://localhost:8080"))
    parser.add_argument("--admin-token", default=os.environ.get("AEGIS_ADMIN_TOKEN"))
    parser.add_argument("--users", nargs="*", default=DEFAULT_USERS)
    parser.add_argument("--turns", type=int, default=200)
    parser.add_argument("--max-turns", type=int, default=None)
    parser.add_argument("--label", default=seed.DEFAULT_LABEL)
    parser.add_argument("--report", type=Path, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--skip-model-call", action="store_true")
    parser.add_argument("--timeout", type=int, default=60)
    parser.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between live calls.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not args.users:
        raise SystemExit("--users must contain at least one user")
    effective_turns = min(args.turns, args.max_turns) if args.max_turns else args.turns
    planned = build_turns(args.users, effective_turns, args.label)
    report: dict[str, Any] = {
        "label": args.label,
        "base_url": args.base_url,
        "dry_run": args.dry_run,
        "skip_model_call": args.skip_model_call,
        "requested_turns": args.turns,
        "effective_turns": effective_turns,
        "results": [],
    }

    for item in planned:
        result = dict(item)
        token, token_source = _token_for_user(item["user"], args.admin_token)
        result["token_source"] = token_source
        if args.dry_run or args.skip_model_call:
            result.update({"status": "planned", "trace_id": item["planned_trace_id"]})
        elif not token:
            result.update(
                {
                    "status": "skipped",
                    "reason": f"missing bearer token; set {token_source} or pass --admin-token",
                    "trace_id": item["planned_trace_id"],
                }
            )
        else:
            try:
                response = _post_ask(args.base_url, token, item, args.timeout)
                result.update(
                    {
                        "status": "ok",
                        "http_status": response["status"],
                        "trace_id": _extract_trace_id(response) or item["planned_trace_id"],
                    }
                )
            except urllib.error.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="replace")
                result.update({"status": "http_error", "http_status": exc.code, "error": body[:1000]})
            except Exception as exc:  # noqa: BLE001
                result.update({"status": "error", "error": str(exc)})
            if args.sleep:
                time.sleep(args.sleep)
        report["results"].append(result)

    output = args.report or ROOT / "exports" / f"governance-traffic-{_safe_label(args.label)}.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(json.dumps({"ok": True, "report": str(output), "turns": len(report["results"])}, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
