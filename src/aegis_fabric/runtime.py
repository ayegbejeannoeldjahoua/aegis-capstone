from __future__ import annotations

import tempfile
from pathlib import Path

from pydantic import BaseModel

from .settings import settings


class RuntimeExecResult(BaseModel):
    stdout: str
    stderr: str
    exit_code: int
    runtime_id: str


class DockerRuntimeCell:
    """Per-request, network-isolated sandbox executor.

    The docker client is injected so the class is unit-testable without a live
    daemon; in production it lazily connects via ``docker.from_env()``.
    """

    def __init__(self, client=None):
        self._client = client

    @property
    def client(self):
        if self._client is None:
            import docker  # imported lazily so the package imports without docker installed

            self._client = docker.from_env()
        return self._client

    def exec(self, command: str, tenant_id: str, trace_id: str, env: dict | None = None, *,
             timeout: int | None = None, mem_limit: str | None = None, network: str | None = None) -> RuntimeExecResult:
        net = network or settings.runtime_network
        mem = mem_limit or settings.runtime_memory_limit
        to = timeout or settings.runtime_timeout_seconds
        with tempfile.TemporaryDirectory(prefix=f"aegis-{tenant_id}-") as d:
            workspace = Path(d)
            (workspace / "README.txt").write_text("request-scoped workspace\n")
            container = self.client.containers.run(
                image=settings.runtime_image,
                command=command,
                detach=True,
                network_mode="none" if net == "none" else net,
                user="10001:10001",
                read_only=True,
                cap_drop=["ALL"],
                security_opt=["no-new-privileges:true"],
                tmpfs={"/tmp": "rw,noexec,nosuid,size=64m"},
                mem_limit=mem,
                cpu_quota=settings.runtime_cpu_quota,
                pids_limit=settings.runtime_pids_limit,
                volumes={str(workspace): {"bind": "/workspace", "mode": "rw"}},
                environment={"AEGIS_TENANT_ID": tenant_id, "AEGIS_TRACE_ID": trace_id, **(env or {})},
            )
            try:
                result = container.wait(timeout=to)
                logs = container.logs(stdout=True, stderr=True).decode(errors="replace")
                code = int(result.get("StatusCode", 1))
                runtime_id = container.id[:12]
            finally:
                container.remove(force=True)
            return RuntimeExecResult(stdout=logs, stderr="", exit_code=code, runtime_id=runtime_id)


# Single shared instance; the docker client connects lazily on first use.
runtime_cell = DockerRuntimeCell()
