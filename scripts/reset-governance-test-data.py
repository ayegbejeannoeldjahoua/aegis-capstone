#!/usr/bin/env python3
"""Remove rows created by the governance acceptance-test fixture label."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = ROOT / "scripts/seed-governance-test-data.py"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("governance_seed", SEED_SCRIPT)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Cannot load {SEED_SCRIPT}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    seed = _load_seed_module()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=seed.GOVERNANCE_FIXTURE)
    parser.add_argument("--label", default=seed.DEFAULT_LABEL)
    parser.add_argument("--dry-run", action="store_true", help="Print the planned label scope only.")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    seed = _load_seed_module()
    args = parse_args(argv)
    data = seed.load_fixture(args.fixture, args.label)
    stats = seed.fixture_stats(data)
    if args.dry_run:
        print(json.dumps({"dry_run": True, "label": args.label, "stats": stats}, indent=2, sort_keys=True))
        return 0
    result = seed.reset_database(args.label, data)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
