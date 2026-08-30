"""Integration Connection and independently checkpointed Ingestion Source administration."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from bothesis.connector.base import StaticCredentialsProvider
from bothesis.connector.confluence.connector import ConfluenceConnector
from bothesis.connector.file.file_connector import FileConnector
from bothesis.db.models import (
    Item,
    IngestionSource,
    IntegrationConnection,
)
from bothesis.connector import ConnectorDefinition
from bothesis.connector.registry import ConnectorRegistry
from bothesis.services import (
    ACTIVE_STATUS,
    SOURCE_MANAGE_PERMISSION,
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    IntegrationCredentialService,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)

_CONNECTION_STATUSES = {"draft", "active", "disabled", "error"}
_SECRET_KEY_TERMS = {"access_key", "api_key", "authorization", "password", "secret", "token"}


class IntegrationService:
    """Manage reusable Connections and independently checkpointed Ingestion Sources."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: ConnectorRegistry | None = None,
        credential_encryption_key: str | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._registry = registry or self.default_registry()
        self._credential_encryption_key = credential_encryption_key
        self._audit = audit or AuditService(session)

    @staticmethod
    def default_registry() -> ConnectorRegistry:
        return ConnectorRegistry(
            (
                ConnectorDefinition(
                    key="confluence",
                    display_name="Confluence",
                    authentication_type="credentials",
                    capabilities=("knowledge_ingestion",),
                    factory=IntegrationService._confluence_factory,
                ),
                ConnectorDefinition(
                    key="file",
                    display_name="Managed files",
                    authentication_type="none",
                    capabilities=("knowledge_ingestion", "file_upload"),
                    factory=IntegrationService._file_factory,
                ),
            )
        )

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
        normalized_key = normalize_required_text(connector_key, "connector key", 64).casefold()
        definition = self._definition(normalized_key)
        normalized_name = normalize_required_text(display_name, "connection display name", 255)
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
            raise AdminValidationError(f"{definition.display_name} credentials are required")
        connection = IntegrationConnection(
            tenant_id=tenant_id,
            connector_key=normalized_key,
            owner_type=normalized_owner,
            owner_user_id=actor.user_id if normalized_owner == "user" else None,
            display_name=normalized_name,
            config=self._non_secret_mapping(config),
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
            raise AdminNotFoundError(f"integration connection not found: {integration_connection_id}")
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
            connection.config = self._non_secret_mapping(config)
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
        ingestion_sources = list(
            await self._session.scalars(
                select(IngestionSource).where(
                    IngestionSource.integration_connection_id == connection.id,
                    IngestionSource.deleted_at.is_(None),
                )
            )
        )
        for source in ingestion_sources:
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

    async def create_source(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        *,
        target_item_id: UUID,
        display_name: str | None,
        config: Mapping[str, Any],
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, integration_connection_id)
        target = await self._session.scalar(
            select(Item).where(
                Item.id == target_item_id,
                Item.tenant_id == tenant_id,
                Item.item_type == "collection",
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if target is None:
            raise AdminNotFoundError(f"target Collection not found: {target_item_id}")
        source = IngestionSource(
            integration_connection_id=connection.id,
            target_item_id=target.id,
            display_name=(
                normalize_required_text(display_name, "source display name", 255)
                if display_name is not None
                else None
            ),
            config=self._non_secret_mapping(config),
            checkpoint={},
            status=ACTIVE_STATUS,
            created_by_user_id=actor.user_id,
        )
        self._session.add(source)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="ingestion.source.created",
            resource_type="ingestion_source",
            resource_id=str(source.id),
            details={
                "integration_connection_id": str(connection.id),
                "target_item_id": str(target.id),
            },
        )
        return await self.get_source(actor, source.id)

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
            filters.append(IntegrationConnection.connector_key == connector_key.strip().casefold())
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

    async def list_sources(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        integration_connection_id: UUID | None = None,
        target_item_id: UUID | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.deleted_at.is_(None),
            IngestionSource.deleted_at.is_(None),
        ]
        if integration_connection_id is not None:
            filters.append(IngestionSource.integration_connection_id == integration_connection_id)
        if target_item_id is not None:
            filters.append(IngestionSource.target_item_id == target_item_id)
        if status is not None:
            filters.append(IngestionSource.status == status.strip().casefold())
        query = (
            select(IngestionSource)
            .join(IntegrationConnection, IntegrationConnection.id == IngestionSource.integration_connection_id)
            .options(
                joinedload(IngestionSource.integration_connection),
                joinedload(IngestionSource.target_item),
            )
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(query.with_only_columns(IngestionSource.id).subquery())
        )
        ingestion_sources = list(
            await self._session.scalars(
                query.order_by(IngestionSource.created_at.desc(), IngestionSource.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        return {
            "items": [self._source_payload(value) for value in ingestion_sources],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_source(self, actor: AuthContext, source_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        source = await self._session.scalar(
            select(IngestionSource)
            .join(IntegrationConnection, IntegrationConnection.id == IngestionSource.integration_connection_id)
            .options(
                joinedload(IngestionSource.integration_connection),
                joinedload(IngestionSource.target_item),
            )
            .where(
                IngestionSource.id == source_id,
                IngestionSource.deleted_at.is_(None),
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.deleted_at.is_(None),
            )
        )
        if source is None:
            raise AdminNotFoundError(f"ingestion source not found: {source_id}")
        return self._source_payload(source)

    async def update_source(
        self,
        actor: AuthContext,
        source_id: UUID,
        *,
        display_name: str | None = None,
        config: Mapping[str, Any] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        source = await self._source(tenant_id, source_id, for_update=True)
        if display_name is not None:
            source.display_name = normalize_required_text(
                display_name, "source display name", 255
            )
        if config is not None:
            source.config = self._non_secret_mapping(config)
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in {"active", "disabled", "error"}:
                raise AdminValidationError("unsupported Ingestion Source status")
            source.status = normalized_status
        await self._session.flush()
        await self._audit.record(
            actor,
            action="ingestion.source.updated",
            resource_type="ingestion_source",
            resource_id=str(source.id),
        )
        return await self.get_source(actor, source.id)

    async def delete_source(self, actor: AuthContext, source_id: UUID) -> None:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        source = await self._source(tenant_id, source_id, for_update=True)
        now = datetime.now(UTC)
        source.status = "disabled"
        source.deleted_at = now
        await self._session.flush()
        await self._audit.record(
            actor,
            action="ingestion.source.deleted",
            resource_type="ingestion_source",
            resource_id=str(source.id),
        )

    async def validate_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, integration_connection_id)
        credentials = await self._resolved_credentials(connection)
        runtime = self._runtime(connection, config={}, credentials=credentials)
        try:
            connected = await runtime.test_connection()
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

    async def runtime_for_source(self, source_id: UUID) -> tuple[IngestionSource, Any]:
        source = await self._session.scalar(
            select(IngestionSource)
            .options(joinedload(IngestionSource.integration_connection), joinedload(IngestionSource.target_item))
            .where(IngestionSource.id == source_id)
        )
        if (
            source is None
            or source.status != ACTIVE_STATUS
            or source.deleted_at is not None
            or source.integration_connection.status != ACTIVE_STATUS
            or source.integration_connection.deleted_at is not None
        ):
            raise AdminNotFoundError(f"active ingestion source not found: {source_id}")
        credentials = await self._resolved_credentials(source.integration_connection)
        return source, self._runtime(
            source.integration_connection, config=source.config, credentials=credentials
        )

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
            raise AdminNotFoundError(f"integration connection not found: {integration_connection_id}")
        return connection

    async def _source(
        self, tenant_id: UUID, source_id: UUID, *, for_update: bool = False
    ) -> IngestionSource:
        statement = (
            select(IngestionSource)
            .options(joinedload(IngestionSource.integration_connection), joinedload(IngestionSource.target_item))
            .join(IntegrationConnection, IntegrationConnection.id == IngestionSource.integration_connection_id)
            .where(
                IngestionSource.id == source_id,
                IngestionSource.deleted_at.is_(None),
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.deleted_at.is_(None),
            )
        )
        if for_update:
            statement = statement.with_for_update(of=IngestionSource)
        source = await self._session.scalar(statement)
        if source is None:
            raise AdminNotFoundError(f"ingestion source not found: {source_id}")
        return source

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
        return IntegrationCredentialService(self._session, self._credential_encryption_key)

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
        config: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> Any:
        definition = self._definition(connection.connector_key)
        connection_config = {
            **dict(connection.config),
            "_tenant_id": str(connection.tenant_id),
            "_integration_connection_id": str(connection.id),
            "connector_id": str(connection.id),
        }
        return definition.factory(connection_config, config, credentials)

    @staticmethod
    def _non_secret_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
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
                IntegrationService._non_secret_mapping(value)
        return result

    @staticmethod
    def _connection_payload(connection: IntegrationConnection) -> dict[str, Any]:
        ingestion_sources = connection.__dict__.get("ingestion_sources", ())
        credential = connection.__dict__.get("credential")
        return {
            "id": str(connection.id),
            "tenant_id": str(connection.tenant_id),
            "connector_key": connection.connector_key,
            "display_name": connection.display_name,
            "config": dict(connection.config),
            "credential_configured": credential is not None,
            "owner_type": connection.owner_type,
            "owner_user_id": str(connection.owner_user_id) if connection.owner_user_id else None,
            "status": connection.status,
            "source_count": len(ingestion_sources),
            "created_at": timestamp(connection.created_at),
            "updated_at": timestamp(connection.updated_at),
        }

    @staticmethod
    def _source_payload(source: IngestionSource) -> dict[str, Any]:
        return {
            "id": str(source.id),
            "integration_connection_id": str(source.integration_connection_id),
            "target_item_id": str(source.target_item_id),
            "display_name": source.display_name,
            "config": dict(source.config),
            "checkpoint": dict(source.checkpoint),
            "status": source.status,
            "last_ingested_at": timestamp(source.last_ingested_at),
            "last_indexed_at": timestamp(source.last_indexed_at),
            "integration_connection": {
                "id": str(source.integration_connection.id),
                "display_name": source.integration_connection.display_name,
                "connector_key": source.integration_connection.connector_key,
            },
            "schedule": None,
        }

    @staticmethod
    def _file_factory(
        connection: Mapping[str, Any],
        source: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> FileConnector:
        del credentials
        return FileConnector({**dict(connection), **dict(source)})

    @staticmethod
    def _confluence_factory(
        connection: Mapping[str, Any],
        source: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> ConfluenceConnector:
        config = {**dict(connection), **dict(source)}
        wiki_base = str(config.get("wiki_base") or "").strip()
        if not wiki_base:
            raise AdminValidationError("Confluence wiki_base is required")
        runtime = ConfluenceConnector(
            wiki_base,
            is_cloud=IntegrationService._config_bool(config, "is_cloud", True),
            space=str(config.get("space") or ""),
            page_id=str(config.get("page_id") or ""),
            index_recursively=IntegrationService._config_bool(
                config, "index_recursively", False
            ),
            cql_query=(str(config["cql_query"]) if config.get("cql_query") else None),
            batch_size=int(config.get("batch_size") or 50),
            labels_to_skip=[str(value) for value in config.get("labels_to_skip") or []],
            timezone_offset=float(config.get("timezone_offset") or 0),
        )
        runtime.set_credentials_provider(
            StaticCredentialsProvider(
                tenant_id=str(config.get("_tenant_id") or "default"),
                provider_key=str(config.get("_integration_connection_id") or "confluence"),
                credentials=dict(credentials),
            )
        )
        return runtime

    @staticmethod
    def _config_bool(config: Mapping[str, Any], key: str, default: bool) -> bool:
        value = config.get(key, default)
        if not isinstance(value, bool):
            raise AdminValidationError(f"{key} must be a boolean")
        return value


__all__ = ["IntegrationService"]
