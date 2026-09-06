"""The Docker executor against a scripted client: isolation and the tar round trip."""

from __future__ import annotations

import io
import json
import sys
import tarfile
from pathlib import Path
from typing import Any

import pytest
import requests
from docker.errors import ImageNotFound

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "backend"))

from bothesis.sandbox import (
    DockerSandboxExecutor,
    SandboxError,
    SandboxFile,
    SandboxOperationError,
    SandboxRequest,
    SandboxTimeoutError,
    SandboxUnavailableError,
)


def output_archive(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for name, data in files.items():
            info = tarfile.TarInfo(f"output/{name}")
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


class FakeContainer:
    def __init__(self, image: str, command: list[str], kwargs: dict[str, Any], script: dict[str, Any]) -> None:
        self.image = image
        self.command = command
        self.kwargs = kwargs
        self.script = script
        self.archives: list[tuple[str, bytes]] = []
        self.started = False
        self.killed = False
        self.removed: tuple[bool, bool] | None = None

    def put_archive(self, path: str, data: bytes) -> bool:
        self.archives.append((path, data))
        return True

    def start(self) -> None:
        self.started = True

    def wait(self, timeout: float) -> dict[str, Any]:
        if self.script.get("hang"):
            raise requests.exceptions.ReadTimeout("wait timed out")
        return {"StatusCode": self.script.get("exit_code", 0)}

    def logs(self, stdout: bool, stderr: bool) -> bytes:
        return b"runner stdout" if stdout else b"runner stderr"

    def get_archive(self, path: str) -> tuple[Any, dict[str, Any]]:
        data = output_archive(self.script["files"])
        return iter([data[:10], data[10:]]), {"size": len(data)}

    def kill(self) -> None:
        self.killed = True

    def remove(self, force: bool, v: bool) -> None:
        self.removed = (force, v)


class FakeClient:
    def __init__(self, script: dict[str, Any]) -> None:
        self.script = script
        self.created: list[FakeContainer] = []
        self.containers = self

    def create(self, image: str, command: list[str], **kwargs: Any) -> FakeContainer:
        if image == "missing:image":
            raise ImageNotFound("no such image")
        container = FakeContainer(image, command, kwargs, self.script)
        self.created.append(container)
        return container


def executor(script: dict[str, Any], **overrides: Any) -> tuple[DockerSandboxExecutor, FakeClient]:
    client = FakeClient(script)
    settings: dict[str, Any] = {
        "image": "bothesis-sandbox:test",
        "timeout_seconds": 5.0,
        "memory_bytes": 128 * 1024 * 1024,
        "cpu_count": 0.5,
        "pids_limit": 32,
        "max_output_bytes": 1024 * 1024,
    }
    settings.update(overrides)
    return DockerSandboxExecutor(client=client, **settings), client


@pytest.mark.asyncio
async def test_a_run_is_isolated_and_round_trips_the_workspace() -> None:
    result_payload = {"status": "ok", "operation": "replace", "file_name": "memo.md"}
    sandbox, client = executor(
        {"files": {"result.json": json.dumps(result_payload).encode(), "memo.md": b"edited\n"}}
    )

    result = await sandbox.run(
        SandboxRequest(
            "replace",
            {"file_name": "memo.md", "edits": [{"find": "a", "replace": "b"}]},
            files=(SandboxFile("memo.md", b"a\n"),),
        )
    )

    container = client.created[0]
    settings = container.kwargs
    # The model never runs commands: the container runs the fixed runner only.
    assert container.command == ["python3", "/workspace/context/runner.py", "/workspace"]
    assert settings["user"] == "65534:65534"
    assert settings["network_disabled"] is True
    assert settings["mem_limit"] == settings["memswap_limit"] == 128 * 1024 * 1024
    assert settings["nano_cpus"] == 500_000_000
    assert settings["pids_limit"] == 32
    assert settings["cap_drop"] == ["ALL"]
    assert settings["security_opt"] == ["no-new-privileges:true"]
    assert settings["read_only"] is True
    assert "/tmp" in settings["tmpfs"]
    assert settings["volumes"] == ["/workspace"]
    # No application, database, or cloud credentials reach the container.
    assert set(settings["environment"]) == {"PYTHONDONTWRITEBYTECODE", "PYTHONUNBUFFERED", "HOME"}
    # The workspace goes in as a tar stream addressed to the writable volume.
    path, archive = container.archives[0]
    assert path == "/workspace"
    with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
        members = {member.name: member for member in tar.getmembers()}
        assert {"input", "context", "work", "output"} <= set(members)
        assert all(member.uid == member.gid == 65534 for member in members.values())
        request = json.loads(tar.extractfile(members["context/request.json"]).read())
        assert request == {
            "operation": "replace",
            "arguments": {"file_name": "memo.md", "edits": [{"find": "a", "replace": "b"}]},
        }
        assert tar.extractfile(members["input/memo.md"]).read() == b"a\n"
        assert b"def main(" in tar.extractfile(members["context/runner.py"]).read()
    assert container.started is True
    # The container and its anonymous volume are always removed.
    assert container.removed == (True, True)
    assert result.operation == "replace"
    assert result.result == result_payload
    assert result.file("memo.md") == b"edited\n"
    assert "result.json" not in result.files
    assert result.stdout == "runner stdout"


@pytest.mark.asyncio
async def test_a_reported_operation_failure_carries_the_runners_message() -> None:
    sandbox, client = executor(
        {
            "exit_code": 1,
            "files": {"result.json": json.dumps({"status": "error", "error": "edit 1: text not found: 'x'"}).encode()},
        }
    )

    with pytest.raises(SandboxOperationError, match="text not found"):
        await sandbox.run(SandboxRequest("replace", {"file_name": "memo.md", "edits": []}))
    assert client.created[0].removed == (True, True)


@pytest.mark.asyncio
async def test_a_hung_container_is_killed_removed_and_reported_as_a_timeout() -> None:
    sandbox, client = executor({"hang": True, "files": {}})

    with pytest.raises(SandboxTimeoutError):
        await sandbox.run(SandboxRequest("write", {"file_name": "memo.md", "content": "x"}))
    container = client.created[0]
    assert container.killed is True
    assert container.removed == (True, True)


@pytest.mark.asyncio
async def test_missing_image_and_missing_result_are_distinct_failures() -> None:
    unavailable, _ = executor({"files": {}}, image="missing:image")
    with pytest.raises(SandboxUnavailableError, match="sandbox image"):
        await unavailable.run(SandboxRequest("write", {"file_name": "memo.md", "content": "x"}))

    silent, client = executor({"files": {"memo.md": b"x"}})
    with pytest.raises(SandboxError, match="no result"):
        await silent.run(SandboxRequest("write", {"file_name": "memo.md", "content": "x"}))
    assert client.created[0].removed == (True, True)


@pytest.mark.asyncio
async def test_output_larger_than_the_limit_is_refused() -> None:
    sandbox, _ = executor(
        {"files": {"result.json": b'{"status":"ok"}', "big.md": b"x" * 4096}},
        max_output_bytes=1024,
    )

    with pytest.raises(SandboxError, match="size limit"):
        await sandbox.run(SandboxRequest("write", {"file_name": "big.md", "content": "x"}))


@pytest.mark.asyncio
async def test_input_file_names_cannot_escape_the_input_directory() -> None:
    sandbox, _ = executor({"files": {}})

    with pytest.raises(ValueError, match="input file name"):
        await sandbox.run(
            SandboxRequest("import", {"file_name": "x"}, files=(SandboxFile("../etc/passwd", b""),))
        )
