"""Map internal service payloads to public contract resource names."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5


def connection_payload(value: dict[str, Any]) -> dict[str, Any]:
    owner_type = value.get("owner_type", "user")
    return {
        "id": value["id"],
        "connector_key": value.get("connector_key", ""),
        "display_name": value.get("display_name", ""),
        "owner_type": "workspace" if owner_type == "tenant" else owner_type,
        "owner_user_id": value.get("owner_user_id"),
        "status": value.get("status", "error"),
        "source_count": value.get("source_count", 0),
        "config": value.get("config", {}),
        "created_at": value["created_at"],
        "updated_at": value["updated_at"],
    }


def source_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value["id"],
        "connection_id": value.get("integration_connection_id"),
        "collection_id": value.get("target_item_id"),
        "display_name": value.get("display_name"),
        "resource_type": value.get("resource_type"),
        "external_resource_id": value.get("external_resource_id"),
        "sync_mode": value.get("sync_mode", "manual"),
        "status": value.get("status", "failed"),
        "schedule": value.get("schedule"),
    }


def ingestion_id(workflow_id: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"bothesis:ingestion:{workflow_id}")


def ingestion_payload(value: dict[str, Any]) -> dict[str, Any]:
    raw_id = str(value.get("id") or value.get("workflow_id"))
    now = datetime.now(UTC)
    return {
        "id": ingestion_id(raw_id),
        "source_id": value.get("source_id"),
        "document_id": value.get("document_id"),
        "connection_id": value.get("integration_connection_id"),
        "status": value.get("status", "pending"),
        "trigger_type": value.get("trigger_type", "manual"),
        "retry_of_ingestion_id": value.get("retry_of_ingestion_id"),
        "progress": value.get("progress"),
        "started_at": value.get("started_at"),
        "finished_at": value.get("finished_at"),
        "created_at": value.get("created_at") or value.get("started_at") or now,
        "updated_at": value.get("updated_at") or value.get("finished_at") or value.get("started_at") or now,
    }


def workspace_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value["id"],
        "code": value.get("code", ""),
        "name": value.get("name", ""),
        "status": value.get("status", "active"),
        "visibility": value.get("visibility"),
        "settings": value.get("settings", {}),
    }


def user_payload(value: dict[str, Any]) -> dict[str, Any]:
    status = value.get("status", "active")
    if isinstance(status, bool):
        status = "active" if status else "inactive"
    membership = value.get("membership") or {}
    return {
        "id": value["id"],
        "email": value["email"],
        "display_name": value.get("display_name"),
        "status": status,
        "roles": membership.get("roles", value.get("roles", [])),
        "groups": value.get("groups", []),
    }


def role_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": value["id"],
        "code": value.get("code", ""),
        "display_name": value.get("display_name", ""),
        "status": value.get("status", "active"),
        "permission_codes": value.get("permission_codes", []),
    }


def approval_request_payload(value: dict[str, Any]) -> dict[str, Any]:
    return {
        **value,
        "created_at": value.get("created_at") or datetime.now(UTC),
    }


__all__ = [
    "approval_request_payload",
    "connection_payload",
    "ingestion_id",
    "ingestion_payload",
    "role_payload",
    "source_payload",
    "user_payload",
    "workspace_payload",
]
