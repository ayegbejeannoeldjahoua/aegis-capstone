# ADR-003 Policy engine

Decision: use OPA/Rego as the active PDP because it is easy to deploy as a sidecar/service and straightforward to test. Include Cedar-style sketches for future comparison where entity-based authorization becomes important.

Failure mode: PDP unreachable means deny.
