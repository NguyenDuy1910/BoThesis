"""Disposable sandbox execution for model-decided file operations.

The model never runs commands. It decides *what* should happen to a document
(write it, apply replacements, import a source document, export a PDF) and BoThesis
executes that fixed operation inside a short-lived, isolated container. The
workspace layout is the only contract between this host and the container:

    /workspace/input           the file(s) the operation reads
    /workspace/context         the request and the runner script
    /workspace/context/skills  format capability modules the runner selects
    /workspace/work            scratch space
    /workspace/output          result.json plus every produced file

A skill is a standalone module owning one document format's manipulation
logic (``skills/docx.py``, ``skills/pdf.py``). The runner selects a skill
deterministically from the file format of the operation — never the model —
so adding a format is additive: a new module plus a runner table entry.

The container is disposable and never the source of truth: durable bytes stay
in object storage and durable state in PostgreSQL.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable

WORKSPACE_ROOT = "/workspace"
INPUT_DIRECTORY = "input"
CONTEXT_DIRECTORY = "context"
WORK_DIRECTORY = "work"
OUTPUT_DIRECTORY = "output"
WORKSPACE_DIRECTORIES = (
    INPUT_DIRECTORY,
    CONTEXT_DIRECTORY,
    WORK_DIRECTORY,
    OUTPUT_DIRECTORY,
)
REQUEST_FILE_NAME = "request.json"
RESULT_FILE_NAME = "result.json"
RUNNER_FILE_NAME = "runner.py"
SKILLS_DIRECTORY = "skills"
# ``nobody`` on Debian-based images: an unprivileged uid that exists everywhere.
SANDBOX_USER = "65534:65534"


class SandboxError(RuntimeError):
    """The sandbox could not complete an operation."""


class SandboxUnavailableError(SandboxError):
    """The container runtime or the sandbox image cannot be used."""


class SandboxTimeoutError(SandboxError):
    """The operation exceeded its wall-clock budget and was killed."""


class SandboxOperationError(SandboxError):
    """The runner completed but reported that the operation failed.

    The message is the runner's own explanation (for example which text to
    replace was not found) and is safe to hand back to the model.
    """


@dataclass(frozen=True, slots=True)
class SandboxFile:
    """One file placed under ``/workspace/input`` before the operation runs."""

    name: str
    data: bytes


@dataclass(frozen=True, slots=True)
class SandboxRequest:
    """One fixed operation with JSON arguments and its input files."""

    operation: str
    arguments: Mapping[str, Any]
    files: tuple[SandboxFile, ...] = ()


@dataclass(frozen=True, slots=True)
class SandboxResult:
    """What the runner reported plus every file it produced."""

    operation: str
    result: Mapping[str, Any]
    files: Mapping[str, bytes]
    duration_ms: int
    stdout: str = ""
    stderr: str = ""

    def file(self, name: str) -> bytes:
        """Return one produced file, failing when the runner did not write it."""

        data = self.files.get(name)
        if data is None:
            raise SandboxOperationError(f"sandbox did not produce {name}")
        return data


@runtime_checkable
class SandboxExecutor(Protocol):
    """Run one request in an isolated, disposable environment."""

    async def run(self, request: SandboxRequest) -> SandboxResult: ...


from .docker import DockerSandboxExecutor  # noqa: E402

__all__ = [
    "CONTEXT_DIRECTORY",
    "INPUT_DIRECTORY",
    "OUTPUT_DIRECTORY",
    "REQUEST_FILE_NAME",
    "RESULT_FILE_NAME",
    "RUNNER_FILE_NAME",
    "SANDBOX_USER",
    "SKILLS_DIRECTORY",
    "WORKSPACE_DIRECTORIES",
    "WORKSPACE_ROOT",
    "WORK_DIRECTORY",
    "DockerSandboxExecutor",
    "SandboxError",
    "SandboxExecutor",
    "SandboxFile",
    "SandboxOperationError",
    "SandboxRequest",
    "SandboxResult",
    "SandboxTimeoutError",
    "SandboxUnavailableError",
]
