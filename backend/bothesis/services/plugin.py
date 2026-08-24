"""Plugin Connection, Binding, Schedule, and Sync Run administration."""

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
    PluginBinding,
    PluginConnection,
    Schedule,
    SyncRun,
)
from bothesis.plugin import PluginDefinition
from bothesis.plugin.registry import PluginRegistry
from bothesis.services import (
    ACTIVE_STATUS,
    SOURCE_MANAGE_PERMISSION,
    AdminConflictError,
    AdminExternalUnavailableError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    PluginCredentialService,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)

_CONNECTION_STATUSES = {"draft", "active", "disabled", "error"}
_SECRET_KEY_TERMS = {"access_key", "api_key", "authorization", "password", "secret", "token"}


class PluginService:
    """Manage reusable Connections and independently checkpointed Bindings."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        registry: PluginRegistry | None = None,
        credential_encryption_key: str | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._registry = registry or self.default_registry()
        self._credential_encryption_key = credential_encryption_key
        self._audit = audit or AuditService(session)

    @staticmethod
    def default_registry() -> PluginRegistry:
        return PluginRegistry(
            (
                PluginDefinition(
                    key="confluence",
                    display_name="Confluence",
                    authentication_type="credentials",
                    capabilities=("knowledge_ingestion",),
                    factory=PluginService._confluence_factory,
                ),
                PluginDefinition(
                    key="file",
                    display_name="Managed files",
                    authentication_type="none",
                    capabilities=("knowledge_ingestion", "file_upload"),
                    factory=PluginService._file_factory,
                ),
            )
        )

    async def capabilities(self, actor: AuthContext) -> dict[str, Any]:
        require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        return {
            "plugins": [
                {
                    "plugin_key": definition.key,
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
        plugin_key: str,
        display_name: str,
        config: Mapping[str, Any],
        credentials: Mapping[str, Any] | None = None,
        credential_type: str | None = None,
        owner_type: str = "tenant",
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        normalized_key = normalize_required_text(plugin_key, "plugin key", 64).casefold()
        definition = self._definition(normalized_key)
        normalized_name = normalize_required_text(display_name, "connection display name", 255)
        normalized_owner = owner_type.strip().casefold()
        if normalized_owner not in {"tenant", "user"}:
            raise AdminValidationError("connection owner_type must be user or tenant")
        duplicate = await self._session.scalar(
            select(PluginConnection.id).where(
                PluginConnection.tenant_id == tenant_id,
                PluginConnection.display_name == normalized_name,
                PluginConnection.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise AdminConflictError("connection display name already exists")
        if definition.authentication_type != "none" and not credentials:
            raise AdminValidationError(f"{definition.display_name} credentials are required")
        connection = PluginConnection(
            tenant_id=tenant_id,
            plugin_key=normalized_key,
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
            action="plugin.connection.created",
            resource_type="plugin_connection",
            resource_id=str(connection.id),
            details={"plugin_key": normalized_key},
        )
        return await self.get_connection(actor, connection.id)

    async def get_connection(
        self, actor: AuthContext, connection_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._session.scalar(
            select(PluginConnection)
            .options(
                selectinload(PluginConnection.bindings),
                joinedload(PluginConnection.credential),
            )
            .where(
                PluginConnection.id == connection_id,
                PluginConnection.tenant_id == tenant_id,
                PluginConnection.deleted_at.is_(None),
            )
        )
        if connection is None:
            raise AdminNotFoundError(f"plugin Connection not found: {connection_id}")
        return self._connection_payload(connection)

    async def update_connection(
        self,
        actor: AuthContext,
        connection_id: UUID,
        *,
        display_name: str | None = None,
        config: Mapping[str, Any] | None = None,
        credentials: Mapping[str, Any] | None = None,
        credential_type: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, connection_id)
        if display_name is not None:
            normalized_name = normalize_required_text(
                display_name, "connection display name", 255
            )
            duplicate = await self._session.scalar(
                select(PluginConnection.id).where(
                    PluginConnection.tenant_id == tenant_id,
                    PluginConnection.display_name == normalized_name,
                    PluginConnection.id != connection.id,
                    PluginConnection.deleted_at.is_(None),
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
                credential_type=credential_type or connection.plugin_key,
                payload=credentials,
            )
        await self._session.flush()
        await self._audit.record(
            actor,
            action="plugin.connection.updated",
            resource_type="plugin_connection",
            resource_id=str(connection.id),
        )
        return await self.get_connection(actor, connection.id)

    async def delete_connection(
        self, actor: AuthContext, connection_id: UUID
    ) -> None:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, connection_id)
        now = datetime.now(UTC)
        bindings = list(
            await self._session.scalars(
                select(PluginBinding)
                .options(joinedload(PluginBinding.schedule))
                .where(
                    PluginBinding.connection_id == connection.id,
                    PluginBinding.deleted_at.is_(None),
                )
            )
        )
        for binding in bindings:
            binding.status = "disabled"
            binding.deleted_at = now
            if binding.schedule is not None and binding.schedule.deleted_at is None:
                binding.schedule.enabled = False
                binding.schedule.deleted_at = now
        connection.status = "disabled"
        connection.deleted_at = now
        await self._session.flush()
        await self._audit.record(
            actor,
            action="plugin.connection.deleted",
            resource_type="plugin_connection",
            resource_id=str(connection.id),
        )

    async def create_binding(
        self,
        actor: AuthContext,
        connection_id: UUID,
        *,
        target_item_id: UUID,
        display_name: str | None,
        config: Mapping[str, Any],
        schedule: Mapping[str, Any] | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, connection_id)
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
        binding = PluginBinding(
            connection_id=connection.id,
            target_item_id=target.id,
            display_name=(
                normalize_required_text(display_name, "binding display name", 255)
                if display_name is not None
                else None
            ),
            config=self._non_secret_mapping(config),
            checkpoint={},
            status=ACTIVE_STATUS,
            created_by_user_id=actor.user_id,
        )
        self._session.add(binding)
        await self._session.flush()
        if schedule is not None:
            await self._set_schedule(binding, schedule)
        await self._audit.record(
            actor,
            action="plugin.binding.created",
            resource_type="plugin_binding",
            resource_id=str(binding.id),
            details={
                "connection_id": str(connection.id),
                "target_item_id": str(target.id),
            },
        )
        return await self.get_binding(actor, binding.id)

    async def list_connections(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        plugin_key: str | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            PluginConnection.tenant_id == tenant_id,
            PluginConnection.deleted_at.is_(None),
        ]
        if plugin_key:
            filters.append(PluginConnection.plugin_key == plugin_key.strip().casefold())
        if status:
            normalized = status.strip().casefold()
            if normalized not in _CONNECTION_STATUSES:
                raise AdminValidationError("unsupported connection status")
            filters.append(PluginConnection.status == normalized)
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    PluginConnection.display_name.ilike(term),
                    PluginConnection.plugin_key.ilike(term),
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(
                select(PluginConnection.id).where(*filters).subquery()
            )
        )
        connections = list(
            await self._session.scalars(
                select(PluginConnection)
                .options(
                    selectinload(PluginConnection.bindings),
                    joinedload(PluginConnection.credential),
                )
                .where(*filters)
                .order_by(PluginConnection.display_name, PluginConnection.id)
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

    async def list_bindings(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        connection_id: UUID | None = None,
        target_item_id: UUID | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            PluginConnection.tenant_id == tenant_id,
            PluginConnection.deleted_at.is_(None),
            PluginBinding.deleted_at.is_(None),
        ]
        if connection_id is not None:
            filters.append(PluginBinding.connection_id == connection_id)
        if target_item_id is not None:
            filters.append(PluginBinding.target_item_id == target_item_id)
        if status is not None:
            filters.append(PluginBinding.status == status.strip().casefold())
        query = (
            select(PluginBinding)
            .join(PluginConnection, PluginConnection.id == PluginBinding.connection_id)
            .options(
                joinedload(PluginBinding.connection),
                joinedload(PluginBinding.target_item),
                joinedload(PluginBinding.schedule),
            )
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(query.with_only_columns(PluginBinding.id).subquery())
        )
        bindings = list(
            await self._session.scalars(
                query.order_by(PluginBinding.created_at.desc(), PluginBinding.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        return {
            "items": [self._binding_payload(value) for value in bindings],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_binding(self, actor: AuthContext, binding_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        binding = await self._session.scalar(
            select(PluginBinding)
            .join(PluginConnection, PluginConnection.id == PluginBinding.connection_id)
            .options(
                joinedload(PluginBinding.connection),
                joinedload(PluginBinding.target_item),
                joinedload(PluginBinding.schedule),
            )
            .where(
                PluginBinding.id == binding_id,
                PluginBinding.deleted_at.is_(None),
                PluginConnection.tenant_id == tenant_id,
                PluginConnection.deleted_at.is_(None),
            )
        )
        if binding is None:
            raise AdminNotFoundError(f"plugin Binding not found: {binding_id}")
        return self._binding_payload(binding)

    async def update_binding(
        self,
        actor: AuthContext,
        binding_id: UUID,
        *,
        display_name: str | None = None,
        config: Mapping[str, Any] | None = None,
        status: str | None = None,
        schedule: Mapping[str, Any] | None = None,
        clear_schedule: bool = False,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        binding = await self._binding(tenant_id, binding_id, for_update=True)
        if display_name is not None:
            binding.display_name = normalize_required_text(
                display_name, "binding display name", 255
            )
        if config is not None:
            binding.config = self._non_secret_mapping(config)
        if status is not None:
            normalized_status = status.strip().casefold()
            if normalized_status not in {"active", "disabled", "error"}:
                raise AdminValidationError("unsupported Binding status")
            binding.status = normalized_status
        existing_schedule = await self._session.scalar(
            select(Schedule).where(
                Schedule.binding_id == binding.id,
                Schedule.deleted_at.is_(None),
            )
        )
        if clear_schedule and existing_schedule is not None:
            existing_schedule.enabled = False
            existing_schedule.deleted_at = datetime.now(UTC)
        elif schedule is not None:
            if existing_schedule is not None:
                self._apply_schedule_values(existing_schedule, schedule)
            else:
                await self._set_schedule(binding, schedule)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="plugin.binding.updated",
            resource_type="plugin_binding",
            resource_id=str(binding.id),
        )
        return await self.get_binding(actor, binding.id)

    async def delete_binding(self, actor: AuthContext, binding_id: UUID) -> None:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        binding = await self._binding(tenant_id, binding_id, for_update=True)
        now = datetime.now(UTC)
        binding.status = "disabled"
        binding.deleted_at = now
        schedule = await self._session.scalar(
            select(Schedule).where(
                Schedule.binding_id == binding.id,
                Schedule.deleted_at.is_(None),
            )
        )
        if schedule is not None:
            schedule.enabled = False
            schedule.deleted_at = now
        await self._session.flush()
        await self._audit.record(
            actor,
            action="plugin.binding.deleted",
            resource_type="plugin_binding",
            resource_id=str(binding.id),
        )

    async def validate_connection(
        self, actor: AuthContext, connection_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        connection = await self._connection(tenant_id, connection_id)
        credentials = await self._resolved_credentials(connection)
        runtime = self._runtime(connection, config={}, credentials=credentials)
        try:
            connected = await runtime.test_connection()
        except Exception as exc:
            connection.status = "error"
            raise AdminExternalUnavailableError(
                f"{connection.plugin_key} connection validation failed"
            ) from exc
        if not connected:
            connection.status = "error"
            raise AdminExternalUnavailableError(
                f"{connection.plugin_key} connection validation failed"
            )
        connection.status = ACTIVE_STATUS
        await self._session.flush()
        await self._audit.record(
            actor,
            action="plugin.connection.validated",
            resource_type="plugin_connection",
            resource_id=str(connection.id),
        )
        return {"valid": True, "status": connection.status}

    async def trigger_binding(
        self,
        actor: AuthContext,
        binding_id: UUID,
        *,
        trigger_type: str = "manual",
        schedule_id: UUID | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        binding = await self._binding(tenant_id, binding_id, for_update=True)
        normalized_trigger = trigger_type.strip().casefold()
        if normalized_trigger not in {"manual", "scheduled", "webhook", "initial"}:
            raise AdminValidationError("unsupported sync trigger type")
        active_run = await self._session.scalar(
            select(SyncRun.id).where(
                SyncRun.binding_id == binding.id,
                SyncRun.status.in_(("pending", "running")),
            )
        )
        status = "skipped" if active_run is not None else "pending"
        now = datetime.now(UTC)
        run = SyncRun(
            binding_id=binding.id,
            schedule_id=schedule_id,
            trigger_type=normalized_trigger,
            status=status,
            error_code="overlap_skipped" if active_run is not None else None,
            finished_at=now if active_run is not None else None,
        )
        self._session.add(run)
        if schedule_id is not None:
            schedule = await self._session.get(Schedule, schedule_id)
            if schedule is None or schedule.binding_id != binding.id:
                raise AdminValidationError("schedule does not belong to Binding")
            schedule.last_run_at = now
        await self._session.flush()
        await self._audit.record(
            actor,
            action="plugin.binding.sync_requested",
            resource_type="plugin_binding",
            resource_id=str(binding.id),
            details={"run_id": str(run.id), "status": status},
        )
        return self._sync_payload(run, binding)

    async def list_sync_runs(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
        connection_id: UUID | None = None,
        binding_id: UUID | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            PluginConnection.tenant_id == tenant_id,
            PluginConnection.deleted_at.is_(None),
            PluginBinding.deleted_at.is_(None),
        ]
        if status:
            filters.append(SyncRun.status == status.strip().casefold())
        if connection_id:
            filters.append(PluginConnection.id == connection_id)
        if binding_id:
            filters.append(PluginBinding.id == binding_id)
        base = (
            select(SyncRun, PluginBinding)
            .join(PluginBinding, PluginBinding.id == SyncRun.binding_id)
            .join(PluginConnection, PluginConnection.id == PluginBinding.connection_id)
            .options(joinedload(PluginBinding.connection), joinedload(PluginBinding.target_item))
            .where(*filters)
        )
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = (
            await self._session.execute(
                base.order_by(SyncRun.created_at.desc(), SyncRun.id.desc())
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [self._sync_payload(run, binding) for run, binding in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_sync_run(
        self, actor: AuthContext, run_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        row = (
            await self._session.execute(
                select(SyncRun, PluginBinding)
                .join(PluginBinding, PluginBinding.id == SyncRun.binding_id)
                .join(
                    PluginConnection,
                    PluginConnection.id == PluginBinding.connection_id,
                )
                .options(
                    joinedload(PluginBinding.connection),
                    joinedload(PluginBinding.target_item),
                )
                .where(
                    SyncRun.id == run_id,
                    PluginConnection.tenant_id == tenant_id,
                    PluginConnection.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise AdminNotFoundError(f"Sync Run not found: {run_id}")
        run, binding = row
        return self._sync_payload(run, binding)

    async def retry_sync_run(
        self, actor: AuthContext, run_id: UUID
    ) -> dict[str, Any]:
        payload = await self.get_sync_run(actor, run_id)
        if payload["status"] not in {"failed", "cancelled", "skipped"}:
            raise AdminConflictError(
                "only failed, cancelled, or skipped Sync Runs can be retried"
            )
        return await self.trigger_binding(
            actor, UUID(str(payload["binding_id"])), trigger_type="manual"
        )

    async def cancel_sync_run(
        self, actor: AuthContext, run_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        run = await self._session.scalar(
            select(SyncRun)
            .join(PluginBinding, PluginBinding.id == SyncRun.binding_id)
            .join(
                PluginConnection, PluginConnection.id == PluginBinding.connection_id
            )
            .where(
                SyncRun.id == run_id,
                PluginConnection.tenant_id == tenant_id,
                PluginConnection.deleted_at.is_(None),
            )
            .with_for_update(of=SyncRun)
        )
        if run is None:
            raise AdminNotFoundError(f"Sync Run not found: {run_id}")
        if run.status not in {"pending", "running"}:
            raise AdminConflictError("only pending or running Sync Runs can be cancelled")
        run.status = "cancelled"
        run.finished_at = datetime.now(UTC)
        run.error_code = "cancelled_by_user"
        await self._session.flush()
        await self._audit.record(
            actor,
            action="plugin.sync_run.cancelled",
            resource_type="sync_run",
            resource_id=str(run.id),
        )
        return await self.get_sync_run(actor, run.id)

    async def runtime_for_binding(self, binding_id: UUID) -> tuple[PluginBinding, Any]:
        binding = await self._session.scalar(
            select(PluginBinding)
            .options(joinedload(PluginBinding.connection), joinedload(PluginBinding.target_item))
            .where(PluginBinding.id == binding_id)
        )
        if (
            binding is None
            or binding.status != ACTIVE_STATUS
            or binding.deleted_at is not None
            or binding.connection.status != ACTIVE_STATUS
            or binding.connection.deleted_at is not None
        ):
            raise AdminNotFoundError(f"active plugin Binding not found: {binding_id}")
        credentials = await self._resolved_credentials(binding.connection)
        return binding, self._runtime(
            binding.connection, config=binding.config, credentials=credentials
        )

    async def _set_schedule(
        self, binding: PluginBinding, values: Mapping[str, Any]
    ) -> Schedule:
        schedule = Schedule(
            binding_id=binding.id,
        )
        self._apply_schedule_values(schedule, values)
        self._session.add(schedule)
        await self._session.flush()
        return schedule

    @staticmethod
    def _apply_schedule_values(schedule: Schedule, values: Mapping[str, Any]) -> None:
        schedule_type = str(
            values.get("schedule_type") or schedule.schedule_type or "cron"
        ).strip().casefold()
        overlap_policy = str(
            values.get("overlap_policy") or schedule.overlap_policy or "skip"
        ).strip().casefold()
        if schedule_type not in {"cron", "interval"}:
            raise AdminValidationError("schedule_type must be cron or interval")
        if overlap_policy not in {"skip", "queue", "replace"}:
            raise AdminValidationError("unsupported overlap policy")
        enabled = values.get("enabled", schedule.enabled if schedule.id else True)
        if not isinstance(enabled, bool):
            raise AdminValidationError("schedule enabled must be a boolean")
        schedule.schedule_type = schedule_type
        schedule.cron_expression = (
            str(values["cron_expression"]).strip()
            if values.get("cron_expression") is not None
            else schedule.cron_expression
        )
        schedule.timezone = (
            str(values["timezone"]).strip()
            if values.get("timezone") is not None
            else schedule.timezone
        )
        schedule.enabled = enabled
        schedule.overlap_policy = overlap_policy
        if "next_run_at" in values:
            schedule.next_run_at = values.get("next_run_at")
        if not schedule.cron_expression:
            raise AdminValidationError("schedule expression is required")

    async def _connection(
        self, tenant_id: UUID, connection_id: UUID
    ) -> PluginConnection:
        connection = await self._session.scalar(
            select(PluginConnection)
            .options(joinedload(PluginConnection.credential))
            .where(
                PluginConnection.id == connection_id,
                PluginConnection.tenant_id == tenant_id,
                PluginConnection.deleted_at.is_(None),
            )
        )
        if connection is None:
            raise AdminNotFoundError(f"plugin Connection not found: {connection_id}")
        return connection

    async def _binding(
        self, tenant_id: UUID, binding_id: UUID, *, for_update: bool = False
    ) -> PluginBinding:
        statement = (
            select(PluginBinding)
            .options(joinedload(PluginBinding.connection), joinedload(PluginBinding.target_item))
            .join(PluginConnection, PluginConnection.id == PluginBinding.connection_id)
            .where(
                PluginBinding.id == binding_id,
                PluginBinding.deleted_at.is_(None),
                PluginConnection.tenant_id == tenant_id,
                PluginConnection.deleted_at.is_(None),
            )
        )
        if for_update:
            statement = statement.with_for_update(of=PluginBinding)
        binding = await self._session.scalar(statement)
        if binding is None:
            raise AdminNotFoundError(f"plugin Binding not found: {binding_id}")
        return binding

    def _definition(self, key: str) -> PluginDefinition:
        try:
            return self._registry.get(key)
        except LookupError as exc:
            raise AdminValidationError(str(exc)) from exc

    def _credentials(self) -> PluginCredentialService:
        if not self._credential_encryption_key:
            raise AdminExternalUnavailableError(
                "BOTHESIS_PLUGIN_ENCRYPTION_KEY is not configured"
            )
        return PluginCredentialService(self._session, self._credential_encryption_key)

    async def _resolved_credentials(
        self, connection: PluginConnection
    ) -> Mapping[str, Any]:
        definition = self._definition(connection.plugin_key)
        if definition.authentication_type == "none":
            return {}
        return await self._credentials().resolve(connection.id)

    def _runtime(
        self,
        connection: PluginConnection,
        *,
        config: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> Any:
        definition = self._definition(connection.plugin_key)
        connection_config = {
            **dict(connection.config),
            "_tenant_id": str(connection.tenant_id),
            "_connection_id": str(connection.id),
            "connector_id": str(connection.id),
        }
        return definition.factory(connection_config, config, credentials)

    @staticmethod
    def _non_secret_mapping(values: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            raise AdminValidationError("plugin config must be a JSON object")
        result = dict(values)
        for key, value in result.items():
            normalized_key = str(key).casefold()
            if any(term in normalized_key for term in _SECRET_KEY_TERMS):
                raise AdminValidationError(
                    "secret values must use Plugin Credentials, not config"
                )
            if isinstance(value, Mapping):
                PluginService._non_secret_mapping(value)
        return result

    @staticmethod
    def _connection_payload(connection: PluginConnection) -> dict[str, Any]:
        bindings = connection.__dict__.get("bindings", ())
        credential = connection.__dict__.get("credential")
        return {
            "id": str(connection.id),
            "tenant_id": str(connection.tenant_id),
            "plugin_key": connection.plugin_key,
            "display_name": connection.display_name,
            "config": dict(connection.config),
            "credential_configured": credential is not None,
            "owner_type": connection.owner_type,
            "owner_user_id": str(connection.owner_user_id) if connection.owner_user_id else None,
            "status": connection.status,
            "binding_count": len(bindings),
            "created_at": timestamp(connection.created_at),
            "updated_at": timestamp(connection.updated_at),
        }

    @staticmethod
    def _binding_payload(binding: PluginBinding) -> dict[str, Any]:
        schedule = binding.schedule
        return {
            "id": str(binding.id),
            "connection_id": str(binding.connection_id),
            "target_item_id": str(binding.target_item_id),
            "display_name": binding.display_name,
            "config": dict(binding.config),
            "checkpoint": dict(binding.checkpoint),
            "status": binding.status,
            "last_synced_at": timestamp(binding.last_synced_at),
            "last_indexed_at": timestamp(binding.last_indexed_at),
            "schedule": (
                {
                    "id": str(schedule.id),
                    "schedule_type": schedule.schedule_type,
                    "cron_expression": schedule.cron_expression,
                    "timezone": schedule.timezone,
                    "enabled": schedule.enabled,
                    "overlap_policy": schedule.overlap_policy,
                    "next_run_at": timestamp(schedule.next_run_at),
                    "last_run_at": timestamp(schedule.last_run_at),
                }
                if schedule is not None and schedule.deleted_at is None
                else None
            ),
        }

    @staticmethod
    def _sync_payload(run: SyncRun, binding: PluginBinding) -> dict[str, Any]:
        return {
            "id": str(run.id),
            "binding_id": str(run.binding_id),
            "schedule_id": str(run.schedule_id) if run.schedule_id else None,
            "trigger_type": run.trigger_type,
            "status": run.status,
            "discovered_item_count": run.discovered_item_count,
            "processed_item_count": run.processed_item_count,
            "written_chunk_count": run.written_chunk_count,
            "deleted_item_count": run.deleted_item_count,
            "error_code": run.error_code,
            "error_message": run.error_message,
            "started_at": timestamp(run.started_at),
            "finished_at": timestamp(run.finished_at),
            "created_at": timestamp(run.created_at),
            "connection": {
                "id": str(binding.connection.id),
                "display_name": binding.connection.display_name,
                "plugin_key": binding.connection.plugin_key,
            },
            "binding": {
                "id": str(binding.id),
                "display_name": binding.display_name,
                "target_item_id": str(binding.target_item_id),
            },
        }

    @staticmethod
    def _file_factory(
        connection: Mapping[str, Any],
        binding: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> FileConnector:
        del credentials
        return FileConnector({**dict(connection), **dict(binding)})

    @staticmethod
    def _confluence_factory(
        connection: Mapping[str, Any],
        binding: Mapping[str, Any],
        credentials: Mapping[str, Any],
    ) -> ConfluenceConnector:
        config = {**dict(connection), **dict(binding)}
        wiki_base = str(config.get("wiki_base") or "").strip()
        if not wiki_base:
            raise AdminValidationError("Confluence wiki_base is required")
        runtime = ConfluenceConnector(
            wiki_base,
            is_cloud=PluginService._config_bool(config, "is_cloud", True),
            space=str(config.get("space") or ""),
            page_id=str(config.get("page_id") or ""),
            index_recursively=PluginService._config_bool(
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
                provider_key=str(config.get("_connection_id") or "confluence"),
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


__all__ = ["PluginService"]
