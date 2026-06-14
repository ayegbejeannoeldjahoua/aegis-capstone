// Cedar-style companion sketch, included for architecture comparison.
// OPA/Rego is active in docker-compose. This file documents the equivalent intent.
permit(
  principal in Role::"analyst",
  action in [Action::"memory.read", Action::"memory.write"],
  resource in Namespace::"analyst-notes"
) when { principal.tenant == resource.tenant };

permit(
  principal in Role::"lead",
  action == Action::"memory.write",
  resource in Namespace::"team-decisions"
) when { principal.tenant == resource.tenant };

forbid(
  principal,
  action == Action::"model.call",
  resource
) unless { resource.region == principal.resolved_values.allowed_model_region };
