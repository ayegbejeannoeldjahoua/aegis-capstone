# Kubernetes deployment skeleton

This folder intentionally contains a skeleton rather than a complete cluster-specific deployment. Production deployment should be expressed as Helm/Terraform after ADRs decide tenancy and runtime isolation.

Minimum production controls:

- API Deployment with no Docker socket.
- Separate Runtime Controller with restricted permissions.
- Runtime Cells as Jobs/Pods with restricted Pod Security.
- NetworkPolicies default-deny all egress, allow only PDP/memory/model proxy as needed.
- External Secrets Operator or Vault Agent Injector for secrets.
- OPA as HA service with signed bundles.
- PostgreSQL managed HA or operator-managed cluster.
- OpenTelemetry collector DaemonSet/Deployment.
