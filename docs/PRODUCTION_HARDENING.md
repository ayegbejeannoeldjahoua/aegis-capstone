# Production Hardening Checklist

## Identity

- Use enterprise IdP or hardened Keycloak.
- Disable password grant outside local demonstration.
- Use auth code + PKCE for clients.
- Map IdP groups to tenant/team/role claims.
- Enforce token audience, issuer, expiry, tenant claim, and role claim.

## Policy

- Deploy OPA with signed bundles.
- Treat PDP as HA infrastructure.
- Cache only versioned decisions; invalidate on policy/values change.
- Fail closed on PDP unreachable.

## Runtime Cells

- Prefer Kubernetes with restricted Pod Security, NetworkPolicy, seccomp, AppArmor, non-root, read-only root.
- Consider gVisor/Kata/Firecracker for stronger isolation.
- Avoid raw Docker socket in production unless mediated by a narrow runtime controller.
- Pin images by digest, scan them, and generate SBOMs.

## Memory

- Use tenant_id as mandatory primary filter.
- For vector search, tenant filter before similarity ranking.
- Embeddings inherit max classification from source content.
- Support CMK/BYOK extension points.

## Model routing

- Use allowlisted provider/model refs only.
- Define primary/fallbacks per tenant/risk tier.
- Use local/private providers for restricted data.
- Record model, provider, region, policy version, values version in audit.

## Audit

- Store no raw sensitive content unless explicitly required.
- Prefer references/hashes/tombstones for erasure compatibility.
- Replicate audit to immutable/WORM/SIEM storage.
- Verify hash chain continuously.

## Telemetry

- Propagate W3C trace context.
- Attach tenant_id only if allowed by privacy policy; otherwise use salted tenant hash.
- Export traces/metrics/logs to monitored backend.
