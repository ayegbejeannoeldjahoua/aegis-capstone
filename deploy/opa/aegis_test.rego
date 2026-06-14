package aegis.authz_test

import data.aegis.authz
import rego.v1

rbac := {"acme-corp": {
	"analyst": {"skills": ["summarise-with-memory"], "tools": ["external_lookup"], "readable_namespaces": ["analyst-notes"], "writable_namespaces": ["analyst-notes"], "allowed_model_regions": ["AC1"], "runtime_exec": false, "allowed_providers": [], "writable_classifications": ["public", "internal"]},
	"lead": {"skills": ["summarise-with-memory"], "tools": ["external_lookup"], "readable_namespaces": ["analyst-notes", "team-decisions"], "writable_namespaces": ["analyst-notes", "team-decisions"], "allowed_model_regions": ["AC1"], "runtime_exec": true, "allowed_providers": [], "writable_classifications": ["public", "internal", "confidential"]},
	"viewer": {"skills": [], "tools": [], "readable_namespaces": ["analyst-notes"], "writable_namespaces": [], "allowed_model_regions": ["AC1"], "runtime_exec": false, "allowed_providers": [], "writable_classifications": ["public"]},
	"restricted-models": {"skills": [], "tools": [], "readable_namespaces": [], "writable_namespaces": [], "allowed_model_regions": ["AC1"], "runtime_exec": false, "allowed_providers": ["ollama"], "writable_classifications": ["public"]},
}}

analyst := {"tenant_id": "acme-corp", "role": "analyst"}

test_result_defined if {
	r := authz.result with input as {"subject": analyst, "action": "noop", "resource": {"tenant_id": "acme-corp"}} with data.aegis.rbac as rbac
	r.allow == false
	is_array(r.reasons)
}

test_analyst_reads_own_tenant if {
	authz.allow with input as {"subject": analyst, "action": "memory.read", "resource": {"tenant_id": "acme-corp", "namespace": "analyst-notes"}} with data.aegis.rbac as rbac
}

test_cross_tenant_denied if {
	not authz.allow with input as {"subject": analyst, "action": "memory.read", "resource": {"tenant_id": "beta-corp", "namespace": "analyst-notes"}} with data.aegis.rbac as rbac
}

test_analyst_can_write_team_decisions if {
	# Within a tenant, any role can write any namespace at or below their
	# classification ceiling — the per-role namespace grant was removed.
	authz.allow with input as {"subject": analyst, "action": "memory.write", "resource": {"tenant_id": "acme-corp", "namespace": "team-decisions"}} with data.aegis.rbac as rbac
}

test_lead_can_write_team_decisions if {
	lead := {"tenant_id": "acme-corp", "role": "lead"}
	authz.allow with input as {"subject": lead, "action": "memory.write", "resource": {"tenant_id": "acme-corp", "namespace": "team-decisions"}} with data.aegis.rbac as rbac
}

test_write_above_classification_denied if {
	not authz.allow with input as {"subject": analyst, "action": "memory.write", "resource": {"tenant_id": "acme-corp", "namespace": "analyst-notes", "classification": "restricted"}} with data.aegis.rbac as rbac
}

test_write_within_classification_allowed if {
	authz.allow with input as {"subject": analyst, "action": "memory.write", "resource": {"tenant_id": "acme-corp", "namespace": "analyst-notes", "classification": "internal"}} with data.aegis.rbac as rbac
}

test_model_region_enforced if {
	authz.allow with input as {"subject": analyst, "action": "model.call", "resource": {"tenant_id": "acme-corp", "region": "AC1", "provider": "ollama"}} with data.aegis.rbac as rbac
	not authz.allow with input as {"subject": analyst, "action": "model.call", "resource": {"tenant_id": "acme-corp", "region": "EU1", "provider": "ollama"}} with data.aegis.rbac as rbac
}

test_provider_allowlist if {
	rm := {"tenant_id": "acme-corp", "role": "restricted-models"}
	authz.allow with input as {"subject": rm, "action": "model.call", "resource": {"tenant_id": "acme-corp", "region": "AC1", "provider": "ollama"}} with data.aegis.rbac as rbac
	not authz.allow with input as {"subject": rm, "action": "model.call", "resource": {"tenant_id": "acme-corp", "region": "AC1", "provider": "openai"}} with data.aegis.rbac as rbac
}

test_any_role_can_invoke_skill if {
	# Skills are open to every authenticated user (per-skill governance happens
	# via the actions the skill executes, which remain role-gated).
	viewer := {"tenant_id": "acme-corp", "role": "viewer"}
	authz.allow with input as {"subject": viewer, "action": "skill.invoke", "resource": {"tenant_id": "acme-corp", "skill_id": "summarise-with-memory"}} with data.aegis.rbac as rbac
}

test_unknown_role_denied if {
	ghost := {"tenant_id": "acme-corp", "role": "ghost"}
	not authz.allow with input as {"subject": ghost, "action": "memory.read", "resource": {"tenant_id": "acme-corp", "namespace": "analyst-notes"}} with data.aegis.rbac as rbac
}
