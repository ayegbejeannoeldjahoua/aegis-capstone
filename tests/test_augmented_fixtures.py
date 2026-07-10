from __future__ import annotations

import hashlib
import importlib.util
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BASELINE_FIXTURE = ROOT / "configs/fixtures/tenant_fixture.yaml"
GOVERNANCE_FIXTURE = ROOT / "configs/fixtures/governance_test_fixture.yaml"
SEED_SCRIPT = ROOT / "scripts/seed-governance-test-data.py"

REQUIRED_NAMESPACES = {
    "analyst-notes",
    "team-decisions",
    "research-log",
    "case-notes",
    "policy-drafts",
    "transcripts",
}
TEST_ROLE_IDS = {
    "analyst-no-egress",
    "analyst-low-budget",
    "auditor",
    "approval-reviewer",
    "restricted-reader",
    "runtime-denied-engineer",
    "runtime-python-engineer",
}


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _load_seed_module():
    spec = importlib.util.spec_from_file_location("governance_seed", SEED_SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _combined_memories(baseline: dict, augmented: dict) -> dict[str, list[dict]]:
    out: dict[str, list[dict]] = defaultdict(list)
    for source in (baseline, augmented):
        for tenant in source["tenants"]:
            out[tenant["tenant_id"]].extend(tenant.get("memories", []))
    return out


def _frontmatter(mem: dict) -> dict:
    return mem.get("frontmatter") or {}


def test_augmented_fixture_keeps_required_tenants_and_counts():
    baseline = _load_yaml(BASELINE_FIXTURE)
    augmented = _load_yaml(GOVERNANCE_FIXTURE)
    seed = _load_seed_module()

    expected_tenants = {tenant["tenant_id"] for tenant in baseline["tenants"]}
    assert {tenant["tenant_id"] for tenant in augmented["tenants"]} == expected_tenants
    assert len(expected_tenants) == 9

    stats = seed.fixture_stats(augmented, baseline)
    assert stats["users_added"] == 72
    assert 100 <= stats["users_final_estimate"] <= 115
    assert stats["test_role_templates_added"] == 7
    assert stats["role_templates_final_estimate"] == 12
    assert stats["memory_docs_added"] == 207
    assert stats["memory_docs_final_estimate"] == 270
    assert stats["pending_actions"] == 18
    assert stats["turn_feedback"] == 54
    assert stats["isas"] == 54


def test_required_users_are_present_and_synthetic():
    augmented = _load_yaml(GOVERNANCE_FIXTURE)
    domains = {
        "tenant-acmecp": "acmecp.example",
        "tenant-betago": "betago.example",
        "tenant-gammac": "gammac.example",
        "tenant-finsvc": "finsvc.example",
        "tenant-hrops": "hrops.example",
        "tenant-saleseu": "saleseu.example",
        "tenant-engcore": "engcore.example",
        "tenant-legalco": "legalco.example",
        "tenant-it": "it.example",
    }
    local_parts = {
        "governance-analyst",
        "governance-no-egress",
        "governance-low-budget",
        "governance-auditor",
        "governance-approver",
        "governance-restricted",
        "governance-runtime-denied",
        "governance-runtime-python",
    }
    expected = {f"{local}@{domain}" for domain in domains.values() for local in local_parts}
    actual = {user["email"] for user in augmented["users"]}
    assert expected == actual
    assert all(user.get("synthetic") is True for user in augmented["users"])
    assert all(user["email"].endswith((".example", ".test")) for user in augmented["users"])


def test_all_test_role_templates_and_deltas_exist():
    augmented = _load_yaml(GOVERNANCE_FIXTURE)
    templates = {template["template_id"]: template for template in augmented["role_templates"]}

    assert set(templates) == TEST_ROLE_IDS
    assert all(template.get("test_only") is True for template in templates.values())
    assert templates["analyst-no-egress"]["capabilities"]["egress_domains"] == []
    assert templates["analyst-low-budget"]["capabilities"]["token_budget_per_day"] == 100
    assert templates["analyst-low-budget"]["capabilities"]["max_output_tokens"] == 512

    auditor = templates["auditor"]["capabilities"]
    assert auditor["audit_scope"] == "tenant"
    assert auditor["can_view_traces"] is True
    assert auditor["can_manage_users"] is False
    assert auditor["can_manage_roles"] is False
    assert auditor["can_edit_governance"] is False

    reviewer = templates["approval-reviewer"]["capabilities"]
    assert reviewer["can_approve"] == "tenant"
    assert reviewer["can_manage_users"] is False
    assert reviewer["can_manage_roles"] is False

    restricted = templates["restricted-reader"]["capabilities"]
    assert restricted["max_read_classification"] == "restricted"
    assert restricted["pii_scope"] == "full"
    assert restricted["can_export"] is False

    denied = templates["runtime-denied-engineer"]["capabilities"]
    assert denied["runtime_exec"] is False
    assert "code_exec" not in denied["tools"]
    assert denied["allowed_runtime_languages"] == []

    runtime = templates["runtime-python-engineer"]["capabilities"]
    assert runtime["runtime_exec"] is True
    assert runtime["runtime_network"] == "none"
    assert runtime["allowed_runtime_languages"] == ["python"]


def test_combined_memory_corpus_covers_namespaces_classifications_canaries_and_pii():
    baseline = _load_yaml(BASELINE_FIXTURE)
    augmented = _load_yaml(GOVERNANCE_FIXTURE)
    combined = _combined_memories(baseline, augmented)

    assert set(combined) == {tenant["tenant_id"] for tenant in baseline["tenants"]}
    for tenant_id, memories in combined.items():
        assert len(memories) == 30, tenant_id
        namespaces = Counter(mem["namespace"] for mem in memories)
        assert set(namespaces) == REQUIRED_NAMESPACES
        assert all(namespaces[namespace] >= 5 for namespace in REQUIRED_NAMESPACES)

        classifications = Counter(mem.get("classification", "internal") for mem in memories)
        assert classifications["public"] >= 2
        assert classifications["internal"] >= 5
        assert classifications["confidential"] >= 5
        assert classifications["restricted"] >= 3

        canary_namespaces = {
            mem["namespace"]
            for mem in memories
            if _frontmatter(mem).get("is_injection_canary")
        }
        assert len(canary_namespaces) >= 2

        pii_types = set()
        for mem in memories:
            fm = _frontmatter(mem)
            pii_types.update(fm.get("pii_types") or fm.get("expected_entities") or [])
        assert {"PERSON", "EMAIL", "PHONE"}.issubset(pii_types)
        assert pii_types.intersection({"ADDRESS", "GOVERNMENT_ID", "DATE_OF_BIRTH"})

        assert any(_frontmatter(mem).get("cross_tenant_decoy") for mem in memories)


def test_values_documents_cover_all_required_scopes():
    seed = _load_seed_module()
    augmented = seed.load_fixture(GOVERNANCE_FIXTURE)
    scopes = Counter(doc["scope_type"] for doc in augmented["values_documents"])
    team_count = sum(len(tenant["teams"]) for tenant in augmented["tenants"])

    assert set(scopes) == {"organization", "department", "team", "role", "individual"}
    assert scopes["organization"] == 1
    assert scopes["department"] == 9
    assert scopes["team"] == team_count
    assert scopes["role"] >= 9 * len(TEST_ROLE_IDS)
    assert scopes["individual"] >= len(augmented["users"])

    role_scopes = {(doc["tenant_id"], doc["scope_id"]) for doc in augmented["values_documents"] if doc["scope_type"] == "role"}
    for tenant in augmented["tenants"]:
        for role_id in TEST_ROLE_IDS:
            assert (tenant["tenant_id"], role_id) in role_scopes

    docs_by_scope = {
        (doc.get("tenant_id"), doc["scope_type"], doc.get("scope_id")): doc
        for doc in augmented["values_documents"]
    }
    assert docs_by_scope[("tenant-acmecp", "department", None)]["title"] == "AcmeCP Department Values"
    assert docs_by_scope[("tenant-acmecp", "team", "research")]["title"] == "Supply Chain Reliability Team Values"
    assert docs_by_scope[("tenant-acmecp", "role", "analyst")]["title"] == "Analyst Role Values"
    assert docs_by_scope[("tenant-acmecp", "individual", "jane@acmecp.example")]["title"] == (
        "Jane Analyst Individual Values"
    )
    assert "TD-ACME-SC-01" in docs_by_scope[("tenant-acmecp", "department", None)]["body_md"]
    assert "TV-SC-REL-01" in docs_by_scope[("tenant-acmecp", "team", "research")]["body_md"]
    assert "RV-ANALYST-01" in docs_by_scope[("tenant-acmecp", "role", "analyst")]["body_md"]
    assert "IV-JANE-01" in docs_by_scope[("tenant-acmecp", "individual", "jane@acmecp.example")]["body_md"]


def test_fixture_memory_keys_are_stable_for_repeat_seed_runs():
    baseline = _load_yaml(BASELINE_FIXTURE)
    seed = _load_seed_module()
    first = seed.build_fixture(baseline, label="capstone-demo-2026")
    second = seed.build_fixture(baseline, label="capstone-demo-2026")

    def keys_and_hashes(data: dict) -> set[tuple[str, str, str, str]]:
        rows = set()
        for tenant in data["tenants"]:
            for mem in tenant.get("memories", []):
                fixture_id = _frontmatter(mem)["fixture_id"]
                body_hash = hashlib.sha256(mem["body"].encode("utf-8")).hexdigest()
                rows.add((tenant["tenant_id"], mem["namespace"], fixture_id, body_hash))
        return rows

    first_keys = keys_and_hashes(first)
    second_keys = keys_and_hashes(second)
    assert first_keys == second_keys
    assert len(first_keys) == sum(len(tenant.get("memories", [])) for tenant in first["tenants"])
