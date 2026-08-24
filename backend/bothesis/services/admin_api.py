"""Transactional application service for the tenant Admin control plane."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from bothesis.db.engine import get_session_factory, session_scope
from bothesis.document_index.vector_store import VectorStore
from bothesis.services import (
    AccessRequestService,
    AdminConflictError,
    AdminItemService,
    AdminService,
    AuditService,
    AuthContext,
    CollectionAccessService,
    GroupService,
    PluginService,
    RequestIdentity,
    RoleService,
    TenantService,
    UserService,
)
from bothesis.services.request_identity import resolve_auth_context


class AdminApiService:
    """Own request transactions and delegate admin work to focused services."""

    def __init__(self, *, allow_insecure_development_identity: bool) -> None:
        self._allow_insecure_development_identity = allow_insecure_development_identity
        self._session_factory: Any | None = None

    async def overview(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AdminService(session).overview(actor)

    async def list_spaces(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).list_spaces(actor)

    async def get_space(self, identity: RequestIdentity, tenant_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).get_space(actor, tenant_id)

    async def update_space(
        self, identity: RequestIdentity, tenant_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).update_space(actor, tenant_id, **changes)

    async def list_users(self, identity: RequestIdentity, **filters: Any) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).list_users(actor, **filters)

    async def create_user(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).create_user(actor, **values)

    async def get_user(self, identity: RequestIdentity, user_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).get_user(actor, user_id)

    async def update_user(
        self, identity: RequestIdentity, user_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).update_user(actor, user_id, **changes)

    async def list_permissions(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).list_permissions(actor)

    async def list_roles(self, identity: RequestIdentity, **filters: Any) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).list_roles(actor, **filters)

    async def create_role(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).create_role(actor, **values)

    async def get_role(self, identity: RequestIdentity, role_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).get_role(actor, role_id)

    async def update_role(
        self, identity: RequestIdentity, role_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).update_role(actor, role_id, **changes)

    async def disable_role(self, identity: RequestIdentity, role_id: UUID) -> None:
        async with self._request(identity) as (session, actor):
            await RoleService(session).disable_role(actor, role_id)

    async def list_groups(self, identity: RequestIdentity, **filters: Any) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).list_groups(actor, **filters)

    async def create_group(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).create_group(actor, **values)

    async def get_group(self, identity: RequestIdentity, group_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).get_group(actor, group_id)

    async def update_group(
        self, identity: RequestIdentity, group_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).update_group(actor, group_id, **changes)

    async def replace_group_members(
        self, identity: RequestIdentity, group_id: UUID, user_ids: list[UUID]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).replace_members(actor, group_id, user_ids)

    async def delete_group(self, identity: RequestIdentity, group_id: UUID) -> None:
        async with self._request(identity) as (session, actor):
            await GroupService(session).delete_group(actor, group_id)

    async def plugin_capabilities(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).capabilities(actor)

    async def list_plugin_connections(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).list_connections(actor, **filters)

    async def create_plugin_connection(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).create_connection(actor, **values)

    async def get_plugin_connection(
        self, identity: RequestIdentity, connection_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).get_connection(actor, connection_id)

    async def update_plugin_connection(
        self, identity: RequestIdentity, connection_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).update_connection(actor, connection_id, **changes)

    async def delete_plugin_connection(
        self, identity: RequestIdentity, connection_id: UUID
    ) -> None:
        async with self._request(identity) as (session, actor):
            await self._plugins(session).delete_connection(actor, connection_id)

    async def validate_plugin_connection(
        self, identity: RequestIdentity, connection_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).validate_connection(actor, connection_id)

    async def list_plugin_bindings(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).list_bindings(actor, **filters)

    async def create_plugin_binding(
        self, identity: RequestIdentity, connection_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).create_binding(actor, connection_id, **values)

    async def get_plugin_binding(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).get_binding(actor, binding_id)

    async def update_plugin_binding(
        self, identity: RequestIdentity, binding_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).update_binding(actor, binding_id, **changes)

    async def delete_plugin_binding(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> None:
        async with self._request(identity) as (session, actor):
            await self._plugins(session).delete_binding(actor, binding_id)

    async def sync_plugin_binding(
        self, identity: RequestIdentity, binding_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).trigger_binding(actor, binding_id)

    async def list_ingestion_jobs(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).list_sync_runs(actor, **filters)

    async def get_ingestion_job(
        self, identity: RequestIdentity, run_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).get_sync_run(actor, run_id)

    async def retry_ingestion_job(
        self, identity: RequestIdentity, run_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).retry_sync_run(actor, run_id)

    async def cancel_ingestion_job(
        self, identity: RequestIdentity, run_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._plugins(session).cancel_sync_run(actor, run_id)

    async def list_items(self, identity: RequestIdentity, **filters: Any) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.list_items(actor, **filters)

    async def get_item(self, identity: RequestIdentity, item_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.get_item(actor, item_id)

    async def update_item(
        self, identity: RequestIdentity, item_id: UUID, status: str
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.update_status(actor, item_id, status=status)

    async def retry_item(self, identity: RequestIdentity, item_id: UUID) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.retry_item(actor, item_id)

    async def delete_item(self, identity: RequestIdentity, item_id: UUID) -> None:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                await service.delete_item(actor, item_id)

    async def list_collection_access(
        self, identity: RequestIdentity, item_id: UUID, **filters: Any
    ) -> dict[str, object]:
        async with self._request(identity) as (session, actor):
            return await CollectionAccessService(session).list_grants(
                item_id, actor=actor, **filters
            )

    async def grant_collection_access(
        self, identity: RequestIdentity, item_id: UUID, values: dict[str, Any]
    ) -> dict[str, object]:
        async with self._request(identity) as (session, actor):
            grant = await CollectionAccessService(session).grant(item_id, actor=actor, **values)
            await AuditService(session).record(
                actor,
                action="collection.access.granted",
                resource_type="collection",
                resource_id=str(item_id),
                details={
                    "principal_type": grant.principal_type,
                    "principal_id": str(grant.principal_id),
                    "role": grant.role,
                },
            )
            return CollectionAccessService._payload(grant)

    async def revoke_collection_access(
        self,
        identity: RequestIdentity,
        item_id: UUID,
        *,
        principal_type: str,
        principal_id: UUID,
    ) -> None:
        async with self._request(identity) as (session, actor):
            await CollectionAccessService(session).revoke(
                item_id,
                principal_type=principal_type,
                principal_id=principal_id,
                actor=actor,
            )
            await AuditService(session).record(
                actor,
                action="collection.access.revoked",
                resource_type="collection",
                resource_id=str(item_id),
                details={
                    "principal_type": principal_type,
                    "principal_id": str(principal_id),
                },
            )

    async def list_access_requests(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).list_requests(actor, **filters)

    async def create_access_request(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).create_request(actor, **values)

    async def get_access_request(
        self, identity: RequestIdentity, request_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).get_request(actor, request_id)

    async def decide_access_request(
        self, identity: RequestIdentity, request_id: UUID, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).decide_request(
                actor, request_id, **values
            )

    async def list_audit_logs(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AuditService(session).list_events(actor, **filters)

    @asynccontextmanager
    async def _request(
        self, identity: RequestIdentity
    ) -> AsyncIterator[tuple[Any, AuthContext]]:
        if self._session_factory is None:
            self._session_factory = get_session_factory()
        try:
            async with session_scope(self._session_factory) as session:
                actor = await resolve_auth_context(
                    identity,
                    session,
                    allow_insecure_development_identity=(
                        self._allow_insecure_development_identity
                    ),
                )
                yield session, actor
        except IntegrityError as exc:
            raise AdminConflictError(
                "the requested change conflicts with durable state"
            ) from exc

    @staticmethod
    def _plugins(session: Any) -> PluginService:
        return PluginService(
            session,
            credential_encryption_key=os.getenv("BOTHESIS_PLUGIN_ENCRYPTION_KEY"),
        )

    @staticmethod
    @asynccontextmanager
    async def _item_service(session: Any) -> AsyncIterator[AdminItemService]:
        store = VectorStore(
            collection_name=os.getenv("QDRANT_COLLECTION"),
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            timeout=20,
        )
        try:
            yield AdminItemService(
                session,
                plugin_encryption_key=os.getenv("BOTHESIS_PLUGIN_ENCRYPTION_KEY"),
                vector_store=store,
            )
        finally:
            await store.aclose()


__all__ = ["AdminApiService"]
