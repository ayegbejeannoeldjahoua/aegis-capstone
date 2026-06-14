# ADR-005 Runtime Cells

Decision: use Docker for local production-mode demonstration but design the interface to be replaceable by Kubernetes, gVisor, Kata, Firecracker, or another enterprise workload runtime.

Minimum contract: non-root, read-only root filesystem, cap-drop all, no-new-privileges, pids/memory/cpu limits, network default-deny, request-scoped workspace, request-scoped secrets only.
