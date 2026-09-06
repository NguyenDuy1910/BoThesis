"""Run one sandbox operation in a disposable, locked-down Docker container."""

from __future__ import annotations

import asyncio
import io
import json
import logging
import tarfile
from pathlib import Path
from time import perf_counter
from typing import Any

import docker
import requests
from docker.errors import DockerException, ImageNotFound, NotFound

from bothesis.sandbox import (
    CONTEXT_DIRECTORY,
    INPUT_DIRECTORY,
    OUTPUT_DIRECTORY,
    REQUEST_FILE_NAME,
    RESULT_FILE_NAME,
    RUNNER_FILE_NAME,
    SANDBOX_USER,
    WORKSPACE_DIRECTORIES,
    WORKSPACE_ROOT,
    SandboxError,
    SandboxOperationError,
    SandboxRequest,
    SandboxResult,
    SandboxTimeoutError,
    SandboxUnavailableError,
)

log = logging.getLogger(__name__)

_RUNNER_PATH = Path(__file__).with_name(RUNNER_FILE_NAME)
_SANDBOX_UID = int(SANDBOX_USER.split(":")[0])
_LOG_TAIL_BYTES = 4_096


class DockerSandboxExecutor:
    """Execute fixed operations in an ephemeral container.

    Every run creates a fresh container from the sandbox image, copies the
    workspace in as a tar stream, starts it, waits with a hard timeout, copies
    ``/workspace/output`` back out, and force-removes the container together
    with its anonymous volume. Nothing is bind-mounted from this host and no
    environment variable other than Python hygiene reaches the container, so
    the sandbox never sees application, database, or cloud credentials.

    Isolation applied to each container: unprivileged user, networking
    disabled, memory and swap capped, CPU and pid limits, all capabilities
    dropped, ``no-new-privileges``, a read-only root filesystem with a small
    ``tmpfs`` for ``/tmp`` and an anonymous volume for the workspace.
    """

    def __init__(
        self,
        *,
        image: str,
        timeout_seconds: float,
        memory_bytes: int,
        cpu_count: float,
        pids_limit: int,
        max_output_bytes: int,
        client: Any | None = None,
    ) -> None:
        if not image.strip():
            raise ValueError("sandbox image must not be blank")
        if timeout_seconds <= 0 or cpu_count <= 0:
            raise ValueError("sandbox timeout and CPU limits must be positive")
        if min(memory_bytes, pids_limit, max_output_bytes) < 1:
            raise ValueError("sandbox memory, pid, and output limits must be positive")
        self._image = image.strip()
        self._timeout_seconds = timeout_seconds
        self._memory_bytes = memory_bytes
        self._cpu_count = cpu_count
        self._pids_limit = pids_limit
        self._max_output_bytes = max_output_bytes
        self._client = client
        self._runner_source = _RUNNER_PATH.read_bytes()

    async def run(self, request: SandboxRequest) -> SandboxResult:
        # The Docker SDK is synchronous; the thread keeps the event loop free
        # and, if the caller stops waiting, still reaches the cleanup below.
        return await asyncio.to_thread(self._run, request)

    def _run(self, request: SandboxRequest) -> SandboxResult:
        client = self._docker()
        archive = _workspace_archive(request, self._runner_source)
        started_at = perf_counter()
        try:
            container = client.containers.create(
                self._image,
                command=[
                    "python3",
                    f"{WORKSPACE_ROOT}/{CONTEXT_DIRECTORY}/{RUNNER_FILE_NAME}",
                    WORKSPACE_ROOT,
                ],
                **self.isolation(),
            )
        except ImageNotFound as exc:
            raise SandboxUnavailableError(
                f"sandbox image is not available: {self._image}"
            ) from exc
        except (DockerException, requests.RequestException) as exc:
            raise SandboxUnavailableError("sandbox runtime is unavailable") from exc

        try:
            # The root filesystem is read-only; only the workspace volume
            # accepts the copy, so the archive is addressed to it directly.
            container.put_archive(WORKSPACE_ROOT, archive)
            container.start()
            try:
                waited = container.wait(timeout=self._timeout_seconds)
            except requests.RequestException as exc:
                _kill(container)
                raise SandboxTimeoutError(
                    f"sandbox operation exceeded {self._timeout_seconds:g}s"
                ) from exc
            exit_code = int(waited.get("StatusCode", -1))
            stdout = _tail(container.logs(stdout=True, stderr=False))
            stderr = _tail(container.logs(stdout=False, stderr=True))
            files = self._output_files(container)
        except SandboxError:
            raise
        except (DockerException, requests.RequestException) as exc:
            raise SandboxError("sandbox execution failed") from exc
        finally:
            _remove(container)

        raw_result = files.pop(RESULT_FILE_NAME, None)
        if raw_result is None:
            log.warning(
                "sandbox produced no result exit_code=%s stderr=%s", exit_code, stderr
            )
            raise SandboxError("sandbox produced no result")
        try:
            result = json.loads(raw_result)
        except ValueError as exc:
            raise SandboxError("sandbox produced an unreadable result") from exc
        if not isinstance(result, dict):
            raise SandboxError("sandbox produced an unreadable result")
        if result.get("status") != "ok":
            raise SandboxOperationError(
                str(result.get("error") or "the operation could not be applied")
            )
        return SandboxResult(
            operation=request.operation,
            result=result,
            files=files,
            duration_ms=round((perf_counter() - started_at) * 1_000),
            stdout=stdout,
            stderr=stderr,
        )

    def isolation(self) -> dict[str, Any]:
        """The container settings every run is created with."""

        return {
            "user": SANDBOX_USER,
            "network_disabled": True,
            "mem_limit": self._memory_bytes,
            "memswap_limit": self._memory_bytes,
            "nano_cpus": int(self._cpu_count * 1_000_000_000),
            "pids_limit": self._pids_limit,
            "cap_drop": ["ALL"],
            "security_opt": ["no-new-privileges:true"],
            "read_only": True,
            "tmpfs": {"/tmp": "rw,noexec,nosuid,size=64m"},
            "volumes": [WORKSPACE_ROOT],
            "environment": {
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "HOME": "/tmp",
            },
            "working_dir": WORKSPACE_ROOT,
            "labels": {"bothesis.sandbox": "artifact"},
            "detach": True,
            "stdin_open": False,
            "tty": False,
        }

    def _docker(self) -> Any:
        if self._client is None:
            try:
                self._client = docker.from_env()
            except DockerException as exc:
                raise SandboxUnavailableError("sandbox runtime is unavailable") from exc
        return self._client

    def _output_files(self, container: Any) -> dict[str, bytes]:
        try:
            stream, _ = container.get_archive(f"{WORKSPACE_ROOT}/{OUTPUT_DIRECTORY}")
        except NotFound:
            return {}
        buffer = io.BytesIO()
        received = 0
        for chunk in stream:
            received += len(chunk)
            if received > self._max_output_bytes:
                raise SandboxError("sandbox output exceeds the configured size limit")
            buffer.write(chunk)
        buffer.seek(0)
        files: dict[str, bytes] = {}
        with tarfile.open(fileobj=buffer, mode="r") as archive:
            for member in archive.getmembers():
                if not member.isfile():
                    continue
                name = Path(member.name).name
                extracted = archive.extractfile(member)
                if extracted is None:
                    continue
                files[name] = extracted.read()
        return files


def _workspace_archive(request: SandboxRequest, runner_source: bytes) -> bytes:
    """Build the tar stream extracted into ``/workspace`` inside the container."""

    payload = json.dumps(
        {"operation": request.operation, "arguments": dict(request.arguments)},
        ensure_ascii=False,
    ).encode("utf-8")
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        for directory in WORKSPACE_DIRECTORIES:
            _add_directory(archive, directory)
        _add_file(archive, f"{CONTEXT_DIRECTORY}/{RUNNER_FILE_NAME}", runner_source)
        _add_file(archive, f"{CONTEXT_DIRECTORY}/{REQUEST_FILE_NAME}", payload)
        for file in request.files:
            _add_file(archive, f"{INPUT_DIRECTORY}/{_input_name(file.name)}", file.data)
    return buffer.getvalue()


def _add_directory(archive: tarfile.TarFile, name: str) -> None:
    info = tarfile.TarInfo(name)
    info.type = tarfile.DIRTYPE
    info.mode = 0o755
    info.uid = info.gid = _SANDBOX_UID
    archive.addfile(info)


def _add_file(archive: tarfile.TarFile, name: str, data: bytes) -> None:
    info = tarfile.TarInfo(name)
    info.size = len(data)
    info.mode = 0o644
    info.uid = info.gid = _SANDBOX_UID
    archive.addfile(info, io.BytesIO(data))


def _input_name(name: str) -> str:
    normalized = name.strip()
    if not normalized or "/" in normalized or "\\" in normalized or normalized in {".", ".."}:
        raise ValueError(f"sandbox input file name is invalid: {name!r}")
    return normalized


def _tail(value: bytes | str | None) -> str:
    if not value:
        return ""
    data = value.encode("utf-8", errors="replace") if isinstance(value, str) else value
    return data[-_LOG_TAIL_BYTES:].decode("utf-8", errors="replace")


def _kill(container: Any) -> None:
    try:
        container.kill()
    except (DockerException, requests.RequestException):
        log.warning("sandbox container could not be killed after timeout")


def _remove(container: Any) -> None:
    try:
        container.remove(force=True, v=True)
    except (DockerException, requests.RequestException):
        log.warning("sandbox container could not be removed")


__all__ = ["DockerSandboxExecutor"]
