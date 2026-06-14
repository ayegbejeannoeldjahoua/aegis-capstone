from aegis_fabric.runtime import DockerRuntimeCell


class FakeContainer:
    id = "abcdef1234567890"

    def wait(self, timeout=None):
        return {"StatusCode": 0}

    def logs(self, stdout=True, stderr=True):
        return b"runtime cell ready"

    def remove(self, force=False):
        self.removed = True


class FakeContainers:
    def __init__(self):
        self.kwargs = None

    def run(self, **kwargs):
        self.kwargs = kwargs
        return FakeContainer()


class FakeDocker:
    def __init__(self):
        self.containers = FakeContainers()


def test_runtime_applies_hardening():
    fake = FakeDocker()
    cell = DockerRuntimeCell(client=fake)
    result = cell.exec("echo hi", tenant_id="acme", trace_id="t1")
    kw = fake.containers.kwargs
    assert kw["network_mode"] == "none"
    assert kw["read_only"] is True
    assert kw["cap_drop"] == ["ALL"]
    assert kw["user"] == "10001:10001"
    assert "no-new-privileges:true" in kw["security_opt"]
    assert kw["pids_limit"] == 128
    assert result.exit_code == 0
    assert "ready" in result.stdout
    assert result.runtime_id == "abcdef123456"
