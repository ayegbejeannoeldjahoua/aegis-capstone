package aegis.authz

import rego.v1

# Generic, data-driven authorization. Per-(tenant, role) capabilities are pushed into
# data.aegis.rbac by the application. Adding a tenant/role or editing governance is a
# DATA change; this policy never needs editing.
default allow := false

result := {"allow": allow, "reasons": reasons}

caps := data.aegis.rbac[input.subject.tenant_id][input.subject.role]

valid_tenant if {
	input.subject.tenant_id != ""
	input.subject.tenant_id == input.resource.tenant_id
}

action_permitted if {
	# Skills are open to every authenticated user; per-skill governance
	# happens via the actions the skill itself executes (memory.read,
	# tool.call, model.call), which remain gated by the role's capabilities.
	input.action == "skill.invoke"
	input.resource.skill_id != ""
}

action_permitted if {
	# Memory reads are tenant-scoped at the SQL layer; within a tenant, any
	# authenticated user can read any namespace. The per-role namespace
	# grant was removed in tandem with the policy.py rule change.
	input.action == "memory.read"
	input.resource.namespace != ""
	pii_read_ok
}

action_permitted if {
	# Writes likewise no longer require a per-role namespace grant within
	# the tenant; the classification ceiling is preserved.
	input.action == "memory.write"
	input.resource.namespace != ""
	write_classification_ok
	retention_ok
}

action_permitted if {
	input.action == "memory.delete"
	caps.can_erase == true
}

action_permitted if {
	# Tools are open to every authenticated user; per-tool side-effects are
	# still governed via egress allowlist + DLP on returned payloads.
	input.action == "tool.call"
	input.resource.tool_id != ""
	egress_ok
}

action_permitted if {
	input.action == "model.call"
	input.resource.region in caps.allowed_model_regions
	provider_ok
	purpose_ok
	output_tokens_ok
	input_tokens_ok
}

action_permitted if {
	input.action == "runtime.exec"
	caps.runtime_exec == true
	runtime_network_ok
	runtime_lang_ok
}

# data.export: leaving the tenant boundary, gated by can_export + a classification ceiling
action_permitted if {
	input.action == "data.export"
	caps.can_export == true
	export_classification_ok
}

# classification on writes: if no classification supplied, the namespace check stands alone
write_classification_ok if not input.resource.classification
write_classification_ok if input.resource.classification in caps.writable_classifications

# retention label on writes: absent label passes; otherwise must be in the role's allowed set
retention_ok if not input.resource.retention_class
retention_ok if input.resource.retention_class in caps.allowed_retention_classes

# provider allowlist on model calls: empty allowlist = unrestricted
provider_ok if count(caps.allowed_providers) == 0
provider_ok if input.resource.provider in caps.allowed_providers

# model purpose allowlist (chat/embedding/vision/code); absent purpose passes
purpose_ok if not input.resource.purpose
purpose_ok if input.resource.purpose in caps.allowed_model_purposes

# per-call output-token ceiling; absent value passes
output_tokens_ok if not input.resource.max_output_tokens
output_tokens_ok if input.resource.max_output_tokens <= caps.max_output_tokens

# per-call input-token ceiling; absent value passes
input_tokens_ok if not input.resource.input_tokens
input_tokens_ok if input.resource.input_tokens <= caps.max_input_tokens

# runtime network: "none" always allowed; otherwise must match the role's runtime_network
runtime_network_ok if input.resource.network == "none"
runtime_network_ok if input.resource.network == caps.runtime_network

# egress allowlist for egress-class tools; "*" = any; absent domain passes
egress_ok if not input.resource.egress_domain
egress_ok if "*" in caps.egress_domains
egress_ok if input.resource.egress_domain in caps.egress_domains

# export classification ceiling; absent classification passes
export_classification_ok if not input.resource.classification
export_classification_ok if input.resource.classification in caps.exportable_classifications

# runtime language allowlist; empty allowlist or absent language passes
runtime_lang_ok if not input.resource.language
runtime_lang_ok if count(caps.allowed_runtime_languages) == 0
runtime_lang_ok if input.resource.language in caps.allowed_runtime_languages

# PII retrieval: a non-PII read always passes; a PII read needs pii_scope != none
pii_read_ok if not input.resource.pii
pii_read_ok if caps.pii_scope != "none"

allow if {
	valid_tenant
	action_permitted
}

reasons contains "missing_or_invalid_tenant_claim" if not valid_tenant
reasons contains "no_capabilities_for_role" if not caps
reasons contains sprintf("action_not_permitted:%s", [input.action]) if {
	valid_tenant
	caps
	not action_permitted
}
