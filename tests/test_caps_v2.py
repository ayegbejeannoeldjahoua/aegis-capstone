"""v1.6.0 capability-schema expansion."""
import aegis_fabric.rbac as rbac


def test_new_fields_present_in_empty_caps():
    for f in ["pii_scope", "egress_domains", "allowed_model_purposes", "max_output_tokens",
              "can_export", "max_export_classification", "max_retention_class", "can_erase",
              "max_tool_calls_per_request", "runtime_network", "can_manage_teams", "can_approve"]:
        assert f in rbac.EMPTY_CAPS, f


def test_normalize_fills_defaults_and_drops_junk():
    n = rbac.normalize_caps({"skills": ["x"], "pii_scope": "full", "junk": 1})
    assert n["pii_scope"] == "full" and "junk" not in n
    assert n["allowed_model_purposes"] == ["chat"] and n["max_output_tokens"] == 1024


def test_derived_adds_exportable_classifications():
    d = rbac.derived_caps(rbac.template_capabilities("lead"))
    assert "exportable_classifications" in d
    assert d["exportable_classifications"] == ["public", "internal"]  # lead export ceiling = internal


def test_template_profiles():
    v = rbac.template_capabilities("viewer")
    a = rbac.template_capabilities("analyst")
    p = rbac.template_capabilities("platform-admin")
    assert v["pii_scope"] == "none" and v["max_output_tokens"] == 512
    assert a["pii_scope"] == "masked" and "embedding" in a["allowed_model_purposes"]
    assert p["egress_domains"] == ["*"] and p["can_manage_signing_keys"] is True
