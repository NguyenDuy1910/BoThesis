"""Transactional application service for the tenant Admin control plane."""

from __future__ import annotations

import os
from collections.abc import AsyncIterable, AsyncIterator
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import unquote
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from bothesis.db.engine import get_session_factory, session_scope
from bothesis.document_index.vector_store import VectorStore
from bothesis.document_index.raw_storage import S3DocumentStorage
from bothesis.services import (
    AccessRequestService,
    AclService,
    AdminConflictError,
    AdminItemService,
    AdminService,
    AuditService,
    AuthContext,
    DatasourceService,
    GroupService,
    RequestIdentity,
    RoleService,
    TenantService,
    UserService,
)
from bothesis.services.request_identity import resolve_auth_context


class AdminApiService:
    """Own request transactions and delegate admin work to focused services."""

    def __init__(self, *, allow_insecure_development_identity: bool) -> None:
        self._allow_insecure_development_identity = (
            allow_insecure_development_identity
        )
        self._session_factory: Any | None = None

    async def overview(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AdminService(session).overview(actor)

    async def list_spaces(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).list_spaces(actor)

    async def get_space(
        self, identity: RequestIdentity, tenant_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).get_space(actor, tenant_id)

    async def update_space(
        self, identity: RequestIdentity, tenant_id: UUID, changes: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await TenantService(session).update_space(
                actor, tenant_id, **changes
            )

    async def list_users(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).list_users(actor, **filters)

    async def create_user(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).create_user(actor, **values)

    async def get_user(
        self, identity: RequestIdentity, user_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).get_user(actor, user_id)

    async def update_user(
        self,
        identity: RequestIdentity,
        user_id: UUID,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await UserService(session).update_user(
                actor, user_id, **changes
            )

    async def list_permissions(self, identity: RequestIdentity) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).list_permissions(actor)

    async def list_roles(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).list_roles(actor, **filters)

    async def create_role(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).create_role(actor, **values)

    async def get_role(
        self, identity: RequestIdentity, role_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).get_role(actor, role_id)

    async def update_role(
        self,
        identity: RequestIdentity,
        role_id: UUID,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await RoleService(session).update_role(
                actor, role_id, **changes
            )

    async def disable_role(
        self, identity: RequestIdentity, role_id: UUID
    ) -> None:
        async with self._request(identity) as (session, actor):
            await RoleService(session).disable_role(actor, role_id)

    async def list_groups(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).list_groups(actor, **filters)

    async def create_group(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).create_group(actor, **values)

    async def get_group(
        self, identity: RequestIdentity, group_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).get_group(actor, group_id)

    async def update_group(
        self,
        identity: RequestIdentity,
        group_id: UUID,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).update_group(
                actor, group_id, **changes
            )

    async def replace_group_members(
        self,
        identity: RequestIdentity,
        group_id: UUID,
        user_ids: list[UUID],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await GroupService(session).replace_members(
                actor, group_id, user_ids
            )

    async def delete_group(
        self, identity: RequestIdentity, group_id: UUID
    ) -> None:
        async with self._request(identity) as (session, actor):
            await GroupService(session).delete_group(actor, group_id)

    async def datasource_capabilities(
        self, identity: RequestIdentity
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).capabilities(actor)

    async def list_datasources(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).list_datasources(
                actor, **filters
            )

    async def create_datasource(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).create_datasource(
                actor, **values
            )

    async def upload_datasource_file(
        self,
        identity: RequestIdentity,
        connector_id: int,
        *,
        file_name: str,
        content: AsyncIterable[bytes],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            storage = self._object_storage()
            try:
                return await DatasourceService(
                    session,
                    credential_encryption_key=os.getenv(
                        "BOTHESIS_CONNECTOR_ENCRYPTION_KEY"
                    ),
                    object_storage=storage,
                ).upload_file(
                    actor,
                    connector_id,
                    file_name=unquote(file_name),
                    content=content,
                )
            finally:
                await storage.aclose()

    async def get_datasource(
        self, identity: RequestIdentity, connector_id: int
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).get_datasource(
                actor, connector_id
            )

    async def update_datasource(
        self,
        identity: RequestIdentity,
        connector_id: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).update_datasource(
                actor, connector_id, **changes
            )

    async def delete_datasource(
        self, identity: RequestIdentity, connector_id: int
    ) -> None:
        async with self._request(identity) as (session, actor):
            await self._datasources(session).delete_datasource(actor, connector_id)

    async def validate_datasource(
        self, identity: RequestIdentity, connector_id: int
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).validate_datasource(
                actor, connector_id
            )

    async def sync_datasource(
        self,
        identity: RequestIdentity,
        connector_id: int,
        scope_id: int | None,
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).trigger_sync(
                actor, connector_id, scope_id=scope_id
            )

    async def list_ingestion_jobs(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).list_sync_runs(
                actor, **filters
            )

    async def get_ingestion_job(
        self, identity: RequestIdentity, run_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).get_sync_run(actor, run_id)

    async def retry_ingestion_job(
        self, identity: RequestIdentity, run_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).retry_sync(actor, run_id)

    async def cancel_ingestion_job(
        self, identity: RequestIdentity, run_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await self._datasources(session).cancel_sync(actor, run_id)

    async def list_items(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.list_items(actor, **filters)

    async def get_item(
        self, identity: RequestIdentity, item_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.get_item(actor, item_id)

    async def update_item(
        self,
        identity: RequestIdentity,
        item_id: UUID,
        status: str,
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.update_status(actor, item_id, status=status)

    async def retry_item(
        self, identity: RequestIdentity, item_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                return await service.retry_item(actor, item_id)

    async def delete_item(
        self, identity: RequestIdentity, item_id: UUID
    ) -> None:
        async with self._request(identity) as (session, actor):
            async with self._item_service(session) as service:
                await service.delete_item(actor, item_id)

    async def list_access_requests(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).list_requests(
                actor, **filters
            )

    async def create_access_request(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).create_request(
                actor, **values
            )

    async def get_access_request(
        self, identity: RequestIdentity, request_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AccessRequestService(session).get_request(
                actor, request_id
            )

    async def decide_access_request(
        self,
        identity: RequestIdentity,
        request_id: UUID,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._vector_index() as vector_store:
                return await AccessRequestService(
                    session, vector_store=vector_store
                ).decide_request(actor, request_id, **values)

    async def list_acl_policies(
        self, identity: RequestIdentity, **filters: Any
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AclService(session).list_policies(actor, **filters)

    async def create_acl_policy(
        self, identity: RequestIdentity, values: dict[str, Any]
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._vector_index() as vector_store:
                return await AclService(
                    session, vector_store=vector_store
                ).create_policy(actor, **values)

    async def get_acl_policy(
        self, identity: RequestIdentity, policy_id: UUID
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            return await AclService(session).get_policy(actor, policy_id)

    async def update_acl_policy(
        self,
        identity: RequestIdentity,
        policy_id: UUID,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        async with self._request(identity) as (session, actor):
            async with self._vector_index() as vector_store:
                return await AclService(
                    session, vector_store=vector_store
                ).update_policy(actor, policy_id, **changes)

    async def delete_acl_policy(
        self, identity: RequestIdentity, policy_id: UUID
    ) -> None:
        async with self._request(identity) as (session, actor):
            async with self._vector_index() as vector_store:
                await AclService(
                    session, vector_store=vector_store
                ).delete_policy(actor, policy_id)

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
    def _datasources(session: Any) -> DatasourceService:
        return DatasourceService(
            session,
            credential_encryption_key=os.getenv(
                "BOTHESIS_CONNECTOR_ENCRYPTION_KEY"
            ),
        )

    @staticmethod
    def _object_storage() -> S3DocumentStorage:
        provider = (os.getenv("BOTHESIS_OBJECT_STORAGE_PROVIDER") or "aws_s3").strip().casefold()
        bucket = (
            os.getenv("BOTHESIS_OBJECT_STORAGE_BUCKET")
            or os.getenv("BOTHESIS_S3_BUCKET")
            or os.getenv("BOTHESIS_R2_BUCKET")
            or ""
        ).strip()
        if not bucket:
            raise RuntimeError("BOTHESIS_OBJECT_STORAGE_BUCKET is required")
        if provider == "cloudflare_r2":
            return S3DocumentStorage.for_cloudflare_r2(
                bucket=bucket,
                account_id=os.getenv("BOTHESIS_R2_ACCOUNT_ID") or None,
                endpoint_url=os.getenv("BOTHESIS_R2_ENDPOINT_URL") or None,
                access_key_id=os.getenv("BOTHESIS_R2_ACCESS_KEY_ID") or None,
                secret_access_key=os.getenv("BOTHESIS_R2_SECRET_ACCESS_KEY") or None,
            )
        if provider != "aws_s3":
            raise RuntimeError(
                "BOTHESIS_OBJECT_STORAGE_PROVIDER must be aws_s3 or cloudflare_r2"
            )
        return S3DocumentStorage(
            bucket=bucket,
            region=os.getenv("BOTHESIS_S3_REGION") or None,
            endpoint_url=os.getenv("BOTHESIS_S3_ENDPOINT_URL") or None,
            addressing_style=(os.getenv("BOTHESIS_S3_ADDRESSING_STYLE") or "auto"),
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
                credential_encryption_key=os.getenv(
                    "BOTHESIS_CONNECTOR_ENCRYPTION_KEY"
                ),
                vector_store=store,
            )
        finally:
            await store.aclose()

    @staticmethod
    @asynccontextmanager
    async def _vector_index() -> AsyncIterator[VectorStore]:
        store = VectorStore(
            collection_name=os.getenv("QDRANT_COLLECTION"),
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            timeout=20,
        )
        try:
            yield store
        finally:
            await store.aclose()


__all__ = ["AdminApiService"]
