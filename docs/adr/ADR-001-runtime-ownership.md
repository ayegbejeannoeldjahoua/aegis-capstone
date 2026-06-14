# ADR-001 Runtime ownership

Status: Ratified for production-mode scaffold.

Decision: keep the enterprise Command Plane as the root of trust. The Agent Gateway is a subsystem invoked after identity, tenancy, PDP, and values resolution. Runtime Cells enforce execution isolation.

Consequences: personal/local gateway patterns are reused, but trust decisions are centralized in the enterprise Trust Plane.
