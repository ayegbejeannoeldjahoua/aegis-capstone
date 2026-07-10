from __future__ import annotations

import importlib.util
import sys
from collections import Counter
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
SEED_SCRIPT = ROOT / "scripts/seed-governance-test-data.py"
VALUES_CASCADE_FIXTURE = ROOT / "configs/fixtures/values_cascade_seed.yaml"


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("governance_seed", SEED_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _doc_key(doc: dict) -> tuple[str | None, str, str | None]:
    return doc.get("tenant_id"), doc["scope_type"], doc.get("scope_id")


def test_values_cascade_seed_fixture_contains_five_levels():
    fixture = yaml.safe_load(VALUES_CASCADE_FIXTURE.read_text(encoding="utf-8"))

    assert fixture["version"] == "values-cascade-v1"
    assert fixture["organization_values"]
    assert fixture["tenant_department_values"]
    assert fixture["team_values"]
    assert fixture["role_values"]
    assert fixture["individual_values"]

    assert any(value["id"] == "TD-ACME-SC-01" for doc in fixture["tenant_department_values"] for value in doc["values"])
    assert any(value["id"] == "TV-SC-REL-01" for doc in fixture["team_values"] for value in doc["values"])
    assert any(value["id"] == "RV-ANALYST-01" for doc in fixture["role_values"] for value in doc["values"])
    assert any(value["id"] == "IV-JANE-01" for doc in fixture["individual_values"] for value in doc["values"])


def test_values_cascade_seed_transforms_to_runtime_documents():
    seed = _load_seed_module()
    docs = seed.values_cascade_documents(label="unit-test")
    keys = [_doc_key(doc) for doc in docs]
    scopes = Counter(doc["scope_type"] for doc in docs)

    assert len(keys) == len(set(keys))
    assert set(scopes) == {"organization", "department", "team", "role", "individual"}
    assert all("<!-- fixture_label: unit-test -->" in doc["body_md"] for doc in docs)

    by_key = {_doc_key(doc): doc for doc in docs}
    assert by_key[("tenant-acmecp", "department", None)]["title"] == "AcmeCP Department Values"
    assert by_key[("tenant-acmecp", "team", "research")]["title"] == "Supply Chain Reliability Team Values"
    assert by_key[("tenant-acmecp", "role", "analyst")]["title"] == "Analyst Role Values"
    assert by_key[("tenant-acmecp", "individual", "jane@acmecp.example")]["title"] == (
        "Jane Analyst Individual Values"
    )


def test_jane_acmecp_values_seed_supports_five_layer_cascade():
    seed = _load_seed_module()
    data = seed.build_fixture(label="unit-test")

    def applies_to_jane(doc: dict) -> bool:
        scope = doc["scope_type"]
        if scope == "organization":
            return True
        if doc.get("tenant_id") != "tenant-acmecp":
            return False
        if scope == "department":
            return True
        if scope == "team":
            return doc.get("scope_id") == "research"
        if scope == "role":
            return doc.get("scope_id") == "analyst"
        if scope == "individual":
            return doc.get("scope_id") == "jane@acmecp.example"
        return False

    cascade = sorted(
        [doc for doc in data["values_documents"] if applies_to_jane(doc)],
        key=lambda doc: seed.VALUES_DOCUMENT_SCOPE_ORDER[doc["scope_type"]],
    )

    assert [doc["scope_type"] for doc in cascade] == [
        "organization",
        "department",
        "team",
        "role",
        "individual",
    ]
    body = "\n".join(doc["body_md"] for doc in cascade)
    assert "TD-ACME-SC-01" in body
    assert "TV-SC-REL-01" in body
    assert "RV-ANALYST-01" in body
    assert "IV-JANE-01" in body
