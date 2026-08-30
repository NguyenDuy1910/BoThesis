"""Shared contracts and configuration for the Temporal runtime boundary."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass

INGESTION_ACTIVITY_NAME = "bothesis.run_ingestion"
INGESTION_TASK_QUEUE = "bothesis-ingestion"
INGESTION_WORKFLOW_NAME = "bothesis.ingestion"
TEMPORAL_DEFAULT_NAMESPACE = "default"
TEMPORAL_DEFAULT_TARGET = "127.0.0.1:7233"


@dataclass(frozen=True, slots=True)
class TemporalSettings:
    target: str = TEMPORAL_DEFAULT_TARGET
    namespace: str = TEMPORAL_DEFAULT_NAMESPACE
    task_queue: str = INGESTION_TASK_QUEUE
    api_key: str | None = None
    tls: bool = False

    @classmethod
    def from_environment(cls) -> TemporalSettings:
        """Parse Temporal process configuration once at a composition boundary."""

        return cls(
            target=(
                os.getenv("BOTHESIS_TEMPORAL_TARGET") or TEMPORAL_DEFAULT_TARGET
            ).strip(),
            namespace=(
                os.getenv("BOTHESIS_TEMPORAL_NAMESPACE")
                or TEMPORAL_DEFAULT_NAMESPACE
            ).strip(),
            task_queue=(
                os.getenv("BOTHESIS_TEMPORAL_TASK_QUEUE") or INGESTION_TASK_QUEUE
            ).strip(),
            api_key=(os.getenv("BOTHESIS_TEMPORAL_API_KEY") or "").strip() or None,
            tls=_environment_boolean("BOTHESIS_TEMPORAL_TLS"),
        )

    def __post_init__(self) -> None:
        if not self.target:
            raise ValueError("Temporal target must not be blank")
        if not self.namespace:
            raise ValueError("Temporal namespace must not be blank")
        if not self.task_queue:
            raise ValueError("Temporal task queue must not be blank")


@dataclass(frozen=True, slots=True)
class IngestionWorkflowInput:
    source_id: str
    tenant_id: str
    connector_key: str
    integration_connection_id: str | None = None
    trigger_type: str = "manual"
    test_connection: bool = True

    def __post_init__(self) -> None:
        if not self.source_id.strip():
            raise ValueError("source_id must not be blank")
        if not self.tenant_id.strip():
            raise ValueError("tenant_id must not be blank")
        if not self.connector_key.strip():
            raise ValueError("connector_key must not be blank")
        if self.trigger_type not in {"manual", "scheduled", "webhook", "initial"}:
            raise ValueError("unsupported ingestion trigger type")


@dataclass(frozen=True, slots=True)
class IngestionProgress:
    phase: str = "queued"
    discovered_count: int = 0
    processed_count: int = 0
    indexed_count: int = 0
    deleted_count: int = 0
    failed_count: int = 0


@dataclass(frozen=True, slots=True)
class IngestionResult:
    source_id: str
    discovered_count: int
    processed_count: int
    indexed_count: int
    deleted_count: int
    failed_count: int
    checkpoint_advanced: bool
    duration_ms: int


class WorkflowExecutionNotFoundError(LookupError):
    """Raised when a Temporal workflow or schedule is not present."""


def ingestion_workflow_id(source_id: str) -> str:
    normalized = source_id.strip()
    if not normalized:
        raise ValueError("source_id must not be blank")
    return f"ingestion:{normalized}"


def ingestion_schedule_id(source_id: str) -> str:
    normalized = source_id.strip()
    if not normalized:
        raise ValueError("source_id must not be blank")
    return f"ingestion-schedule:{normalized}"


def _environment_boolean(name: str, *, default: bool = False) -> bool:
    raw_value = os.getenv(name)
    if raw_value is None:
        return default
    try:
        value = json.loads(raw_value)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"{name} must be a JSON boolean") from exc
    if not isinstance(value, bool):
        raise RuntimeError(f"{name} must be a JSON boolean")
    return value


__all__ = [
    "INGESTION_ACTIVITY_NAME",
    "INGESTION_TASK_QUEUE",
    "INGESTION_WORKFLOW_NAME",
    "IngestionProgress",
    "IngestionResult",
    "IngestionWorkflowInput",
    "TemporalSettings",
    "WorkflowExecutionNotFoundError",
    "ingestion_schedule_id",
    "ingestion_workflow_id",
]
