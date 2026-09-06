"""Administration of tenant-scoped reusable Integration Connections."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from bothesis.connector import ConnectorDefinition
from bothesis.connector.registry import ConnectorRegistry
from bothesis.db.models import IngestionSource, IntegrationConnection
from bothesis.services.audit import AuditService
from bothesis.services.integration_credential import IntegrationCredentialService
from bothesis.services import (
    ACTIVE_STATUS,
    SOURCE_MANAGE_PERMISSION,
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    AuthContext,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)

_CONNECTION_STATUSES = {"draft", "active", "disabled", "error"}
_SECRET_KEY_TERMS = {
    "access_key",
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
}


class IntegrationConnectionService:
    """Manage connection configuration, credentials, and connector runtime."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: ConnectorRegistry | None = None,
        credential_encryption_key: str | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._registry = registry or ConnectorRegistry.default()
        self._credential_encryption_key = credential_encryption_key
        self._audit = audit or AuditService(session)

    async def capabilities(self, actor: AuthContext) -> dict[str, Any]:
        require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return {
            "connectors": [
                {
                    "connector_key": definition.key,
                    "display_name": definition.display_name,
                    "authentication_type": definition.authentication_type,
                    "capabilities": list(definition.capabilities),
                }
                for definition in self._registry.list()
            ]
        }

    async def create_connection(
        self,
        actor: AuthContext,
        *,
        connector_key: str,
        display_name: str,
        config: Mapping[str, Any],
        credentials: Mapping[str, Any] | None = None,
        credential_type: str | None = None,
        owner_type: str = "tenant",
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        normalized_key = normalize_required_text(
            connector_key, "connector key", 64
        ).casefold()
        definition = self._definition(normalized_key)
        normalized_name = normalize_required_text(
            display_name, "connection display name", 255
        )
        normalized_owner = owner_type.strip().casefold()
        if normalized_owner not in {"tenant", "user"}:
            raise AdminValidationError("connection owner_type must be user or tenant")
        duplicate = await self._session.scalar(
            select(IntegrationConnection.id).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.display_name == normalized_name,
                IntegrationConnection.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise AdminConflictError("connection display name already exists")
        if definition.authentication_type != "none" and not credentials:
            raise AdminValidationError(
                f"{definition.display_name} credentials are required"
            )
        connection = IntegrationConnection(
            tenant_id=tenant_id,
            connector_key=normalized_key,
            owner_type=normalized_owner,
            owner_user_id=actor.user_id if normalized_owner == "user" else None,
            display_name=normalized_name,
            config=self.non_secret_config(config),
            status="draft",
            created_by_user_id=actor.user_id,
        )
        self._session.add(connection)
        await self._session.flush()
        if credentials:
            await self._credentials().store(
                connection.id,
                credential_type=credential_type or normalized_key,
                payload=credentials,
            )
        await self._audit.record(
            actor,
            action="integration.connection.created",
            resource_type="integration_connection",
            resource_id=str(connection.id),
            details={"connector_key": normalized_key},
        )
        return await self.get_connection(actor, connection.id)

    async def list_connections(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        connector_key: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.deleted_at.is_(None),
        ]
        if connector_key:
            filters.append(
                IntegrationConnection.connector_key == connector_key.strip().casefold()
            )
        if status:
            normalized = status.strip().casefold()
            if normalized not in _CONNECTION_STATUSES:
                raise AdminValidationError("unsupported connection status")
            filters.append(IntegrationConnection.status == normalized)
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    IntegrationConnection.display_name.ilike(term),
                    IntegrationConnection.connector_key.ilike(term),
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(
                select(IntegrationConnection.id).where(*filters).subquery()
            )
        )
        connections = list(
            await self._session.scalars(
                select(IntegrationConnection)
                .options(
                    selectinload(IntegrationConnection.ingestion_sources),
                    joinedload(IntegrationConnection.credential),
                )
                .where(*filters)
                .order_by(IntegrationConnection.display_name, IntegrationConnection.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        return {
            "items": [self._connection_payload(value) for value in connections],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._session.scalar(
            select(IntegrationConnection)
            .options(
                selectinload(IntegrationConnection.ingestion_sources),
                joinedload(IntegrationConnection.credential),
            )
            .where(
                IntegrationConnection.id == integration_connection_id,
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.deleted_at.is_(None),
            )
        )
        if connection is None:
            raise AdminNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        return self._connection_payload(connection)

    async def update_connection(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        *,
        display_name: str | None = None,
        config: Mapping[str, Any] | None = None,
        credentials: Mapping[str, Any] | None = None,
        credential_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, integration_connection_id)
        if display_name is not None:
            normalized_name = normalize_required_text(
                display_name, "connection display name", 255
            )
            duplicate = await self._session.scalar(
                select(IntegrationConnection.id).where(
                    IntegrationConnection.tenant_id == tenant_id,
                    IntegrationConnection.display_name == normalized_name,
                    IntegrationConnection.id != connection.id,
                    IntegrationConnection.deleted_at.is_(None),
                )
            )
            if duplicate is not None:
                raise AdminConflictError("connection display name already exists")
            connection.display_name = normalized_name
        if config is not None:
            connection.config = self.non_secret_config(config)
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in _CONNECTION_STATUSES - {"error"}:
                raise AdminValidationError("unsupported connection status")
            connection.status = normalized_status
        if credentials is not None:
            await self._credentials().store(
                connection.id,
                credential_type=credential_type or connection.connector_key,
                payload=credentials,
            )
        await self._session.flush()
        await self._audit.record(
            actor,
            action="integration.connection.updated",
            resource_type="integration_connection",
            resource_id=str(connection.id),
        )
        return await self.get_connection(actor, connection.id)

    async def delete_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> None:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, integration_connection_id)
        now = datetime.now(UTC)
        sources = list(
            await self._session.scalars(
                select(IngestionSource).where(
                    IngestionSource.integration_connection_id == connection.id,
                    IngestionSource.deleted_at.is_(None),
                )
            )
        )
        for source in sources:
            source.status = "disabled"
            source.deleted_at = now
        connection.status = "disabled"
        connection.deleted_at = now
        await self._session.flush()
        await self._audit.record(
            actor,
            action="integration.connection.deleted",
            resource_type="integration_connection",
            resource_id=str(connection.id),
        )

    async def validate_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, integration_connection_id)
        try:
            runtime = await self.runtime_for(connection, source_config={})
            connected = await runtime.test_connection()
        except AdminValidationError:
            raise
        except Exception as exc:
            connection.status = "error"
            raise AdminExternalUnavailableError(
                f"{connection.connector_key} connection validation failed"
            ) from exc
        if not connected:
            connection.status = "error"
            raise AdminExternalUnavailableError(
                f"{connection.connector_key} connection validation failed"
            )
        connection.status = ACTIVE_STATUS
        await self._session.flush()
        await self._audit.record(
            actor,
            action="integration.connection.validated",
            resource_type="integration_connection",
            resource_id=str(connection.id),
        )
        return {"valid": True, "status": connection.status}

    async def runtime_for(
        self,
        connection: IntegrationConnection,
        *,
        source_config: Mapping[str, Any],
    ) -> Any:
        credentials = await self._resolved_credentials(connection)
        try:
            return self._runtime(
                connection,
                source_config=source_config,
                credentials=credentials,
            )
        except ValueError as exc:
            raise AdminValidationError(str(exc)) from exc

    @staticmethod
    def non_secret_config(values: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            raise AdminValidationError("integration config must be a JSON object")
        result = dict(values)
        for key, value in result.items():
            normalized_key = str(key).casefold()
            if any(term in normalized_key for term in _SECRET_KEY_TERMS):
                raise AdminValidationError(
                    "secret values must use Integration Credentials, not config"
                )
            if isinstance(value, Mapping):
                IntegrationConnectionService.non_secret_config(value)
        return result

    async def _connection(
        self, tenant_id: UUID, integration_connection_id: UUID
    ) -> IntegrationConnection:
        connection = await self._session.scalar(
            select(IntegrationConnection)
            .options(joinedload(IntegrationConnection.credential))
            .where(
                IntegrationConnection.id == integration_connection_id,
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.deleted_at.is_(None),
            )
        )
        if connection is None:
            raise AdminNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        return connection

    def _definition(self, key: str) -> ConnectorDefinition:
        try:
            return self._registry.get(key)
        except LookupError as exc:
            raise AdminValidationError(str(exc)) from exc

    def _credentials(self) -> IntegrationCredentialService:
        if not self._credential_encryption_key:
            raise AdminExternalUnavailableError(
                "BOTHESIS_INTEGRATION_ENCRYPTION_KEY is not configured"
            )
        return IntegrationCredentialService(
            self._session, self._credential_encryption_key
        )

    async def _resolved_credentials(
        self, connection: IntegrationConnection
    ) -> Mapping[str, Any]:
        definition = self._definition(connection.connector_key)
        if definition.authentication_type == "none":
            return {}
        return await self._credentials().resolve(connection.id)

    def _runtime(
        self,
        connection: IntegrationConnection,
        *,
        source_config: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> Any:
        definition = self._definition(connection.connector_key)
        connection_config = {
            **dict(connection.config),
            "_tenant_id": str(connection.tenant_id),
            "_integration_connection_id": str(connection.id),
            "connector_id": str(connection.id),
        }
        return definition.factory(connection_config, source_config, credentials)

    @staticmethod
    def _connection_payload(connection: IntegrationConnection) -> dict[str, Any]:
        sources = connection.__dict__.get("ingestion_sources", ())
        credential = connection.__dict__.get("credential")
        return {
            "id": str(connection.id),
            "tenant_id": str(connection.tenant_id),
            "connector_key": connection.connector_key,
            "display_name": connection.display_name,
            "config": dict(connection.config),
            "credential_configured": credential is not None,
            "owner_type": connection.owner_type,
            "owner_user_id": (
                str(connection.owner_user_id) if connection.owner_user_id else None
            ),
            "status": connection.status,
            "source_count": len(sources),
            "created_at": timestamp(connection.created_at),
            "updated_at": timestamp(connection.updated_at),
        }


__all__ = ["IntegrationConnectionService"]
