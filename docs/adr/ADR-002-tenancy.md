# ADR-002 Tenancy model

Decision: every request carries a tenant claim; every persisted record carries `tenant_id`; every memory query filters by tenant before namespace, keyword, or vector similarity; runtime cells are labeled with tenant/request identifiers.

Production extension: for high-risk tenants, run dedicated gateway/runtime pools and dedicated database schemas or clusters.
