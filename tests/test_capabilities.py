import aegis_fabric.rbac as rbac


def test_classification_helpers():
    assert rbac.class_rank("public") < rbac.class_rank("restricted")
    assert set(rbac.classes_up_to("confidential")) == {"public", "internal", "confidential"}
    assert "restricted" not in rbac.classes_up_to("confidential")
    assert rbac.risk_rank("T1") < rbac.risk_rank("T3")


def test_normalize_fills_new_caps():
    c = rbac.normalize_caps({"skills": ["x"]})
    assert c["max_read_classification"] == "internal"
    assert c["admin_scope"] == "none"
    assert c["audit_scope"] == "own"
    assert c["allowed_providers"] == []


def test_derived_caps_adds_classification_lists():
    d = rbac.derived_caps(rbac.template_capabilities("analyst"))
    assert "confidential" in d["readable_classifications"]      # analyst max_read=confidential
    assert "confidential" not in d["writable_classifications"]  # analyst max_write=internal


def test_templates_present():
    assert set(rbac.DEFAULT_TEMPLATES) >= {"analyst", "lead", "viewer", "tenant-admin", "platform-admin"}
    pa = rbac.template_capabilities("platform-admin")
    assert pa["admin_scope"] == "platform" and pa["can_manage_roles"] is True
    ta = rbac.template_capabilities("tenant-admin")
    assert ta["admin_scope"] == "tenant"
    assert rbac.template_capabilities("analyst")["admin_scope"] == "none"


def test_can_delete_tenant_only_platform_admin():
    assert rbac.template_capabilities("platform-admin")["can_delete_tenant"] is True
    assert rbac.template_capabilities("tenant-admin")["can_delete_tenant"] is False
    assert rbac.template_capabilities("analyst")["can_delete_tenant"] is False
