"""Materialized document ACL policy administration."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import AclPolicy, Document
from bothesis.services import (
    ACCESS_MANAGE_PERMISSION,
    ACTIVE_STATUS,
    INACTIVE_STATUS,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    normalize_codes,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)


class AclService:
    """Persist policies and materialize active document principal tokens."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def list_policies(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            AclPolicy.tenant_id == tenant_id,
            AclPolicy.deleted_at.is_(None),
        ]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    AclPolicy.name.ilike(term),
                    AclPolicy.resource_id.ilike(term),
                    Document.title.ilike(term),
                )
            )
        if status:
            normalized = status.strip().casefold()
            if normalized not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("ACL policy status must be active or inactive")
            filters.append(AclPolicy.status == normalized)
        base = (
            select(AclPolicy, Document.title)
            .outerjoin(
                Document,
                (AclPolicy.resource_type == "document")
                & (AclPolicy.resource_id == cast(Document.id, String)),
            )
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        rows = (
            await self._session.execute(
                base.order_by(AclPolicy.name, AclPolicy.id)
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [
                _policy_payload(policy, resource_title=resource_title)
                for policy, resource_title in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_policy(
        self, actor: AuthContext, policy_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        policy = await self._policy(tenant_id, policy_id)
        document = await self._document(tenant_id, policy.resource_id)
        return _policy_payload(policy, resource_title=document.title)

    async def create_policy(
        self,
        actor: AuthContext,
        *,
        name: str,
        resource_type: str,
        resource_id: str,
        allowed_principal_tokens: list[str],
        denied_principal_tokens: list[str],
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        normalized_name = normalize_required_text(name, "ACL policy name", 255)
        if await self._session.scalar(
            select(AclPolicy.id).where(
                AclPolicy.tenant_id == tenant_id,
                AclPolicy.name == normalized_name,
            )
        ) is not None:
            raise AdminConflictError(
                f"ACL policy name already exists in tenant: {normalized_name}"
            )
        normalized_type = resource_type.strip().casefold()
        if normalized_type != "document":
            raise AdminValidationError(
                "document is the only materialized ACL resource type"
            )
        document = await self._document(tenant_id, resource_id)
        allowed, denied = _principal_sets(
            allowed_principal_tokens, denied_principal_tokens
        )
        policy = AclPolicy(
            tenant_id=tenant_id,
            name=normalized_name,
            resource_type=normalized_type,
            resource_id=str(document.id),
            allowed_principal_tokens=allowed,
            denied_principal_tokens=denied,
            created_by_user_id=actor.user_id,
        )
        self._session.add(policy)
        _materialize(document, policy)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="acl_policy.created",
            resource_type="acl_policy",
            resource_id=str(policy.id),
            details={"document_id": str(document.id)},
        )
        return _policy_payload(policy, resource_title=document.title)

    async def update_policy(
        self,
        actor: AuthContext,
        policy_id: UUID,
        *,
        name: str | None = None,
        allowed_principal_tokens: list[str] | None = None,
        denied_principal_tokens: list[str] | None = None,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        policy = await self._policy(tenant_id, policy_id)
        document = await self._document(tenant_id, policy.resource_id)
        changed: list[str] = []
        if name is not None:
            normalized_name = normalize_required_text(name, "ACL policy name", 255)
            duplicate = await self._session.scalar(
                select(AclPolicy.id).where(
                    AclPolicy.tenant_id == tenant_id,
                    AclPolicy.name == normalized_name,
                    AclPolicy.id != policy.id,
                )
            )
            if duplicate is not None:
                raise AdminConflictError(
                    f"ACL policy name already exists in tenant: {normalized_name}"
                )
            policy.name = normalized_name
            changed.append("name")
        if allowed_principal_tokens is not None or denied_principal_tokens is not None:
            allowed, denied = _principal_sets(
                allowed_principal_tokens
                if allowed_principal_tokens is not None
                else policy.allowed_principal_tokens,
                denied_principal_tokens
                if denied_principal_tokens is not None
                else policy.denied_principal_tokens,
            )
            policy.allowed_principal_tokens = allowed
            policy.denied_principal_tokens = denied
            changed.append("principals")
        if status is not None:
            normalized = status.strip().casefold()
            if normalized not in {ACTIVE_STATUS, INACTIVE_STATUS}:
                raise AdminValidationError("ACL policy status must be active or inactive")
            policy.status = normalized
            changed.append("status")
        if policy.status == ACTIVE_STATUS:
            _materialize(document, policy)
        else:
            document.allowed_principal_tokens = []
            document.denied_principal_tokens = []
        await self._session.flush()
        await self._audit.record(
            actor,
            action="acl_policy.updated",
            resource_type="acl_policy",
            resource_id=str(policy.id),
            details={"changed_fields": changed, "document_id": str(document.id)},
        )
        return _policy_payload(policy, resource_title=document.title)

    async def delete_policy(self, actor: AuthContext, policy_id: UUID) -> None:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        policy = await self._policy(tenant_id, policy_id)
        document = await self._document(tenant_id, policy.resource_id)
        policy.status = INACTIVE_STATUS
        policy.deleted_at = datetime.now(UTC)
        document.allowed_principal_tokens = []
        document.denied_principal_tokens = []
        await self._session.flush()
        await self._audit.record(
            actor,
            action="acl_policy.deleted",
            resource_type="acl_policy",
            resource_id=str(policy.id),
            details={"document_id": str(document.id)},
        )

    async def _policy(self, tenant_id: UUID, policy_id: UUID) -> AclPolicy:
        policy = await self._session.scalar(
            select(AclPolicy).where(
                AclPolicy.id == policy_id,
                AclPolicy.tenant_id == tenant_id,
                AclPolicy.deleted_at.is_(None),
            )
        )
        if policy is None:
            raise AdminNotFoundError(f"ACL policy not found: {policy_id}")
        return policy

    async def _document(self, tenant_id: UUID, resource_id: str) -> Document:
        try:
            document_id = UUID(resource_id)
        except ValueError as exc:
            raise AdminValidationError("document resource ID must be a UUID") from exc
        document = await self._session.scalar(
            select(Document).where(
                Document.id == document_id,
                Document.tenant_id == tenant_id,
                Document.lifecycle_status != "deleted",
                Document.deleted_at.is_(None),
            )
        )
        if document is None:
            raise AdminNotFoundError(f"document not found: {resource_id}")
        return document


def _principal_sets(
    allowed_values: list[str], denied_values: list[str]
) -> tuple[list[str], list[str]]:
    allowed = normalize_codes(allowed_values, "allowed principal token", 512)
    denied = normalize_codes(denied_values, "denied principal token", 512)
    overlap = sorted(set(allowed) & set(denied))
    if overlap:
        raise AdminValidationError(
            "principal tokens cannot be both allowed and denied: " + ", ".join(overlap)
        )
    if not allowed:
        raise AdminValidationError("at least one allowed principal token is required")
    return allowed, denied


def _materialize(document: Document, policy: AclPolicy) -> None:
    document.allowed_principal_tokens = list(policy.allowed_principal_tokens)
    document.denied_principal_tokens = list(policy.denied_principal_tokens)


def _policy_payload(
    policy: AclPolicy, *, resource_title: str | None
) -> dict[str, Any]:
    return {
        "id": str(policy.id),
        "name": policy.name,
        "resource_type": policy.resource_type,
        "resource_id": policy.resource_id,
        "resource_title": resource_title,
        "allowed_principal_tokens": sorted(policy.allowed_principal_tokens),
        "denied_principal_tokens": sorted(policy.denied_principal_tokens),
        "status": policy.status,
        "created_by_user_id": (
            str(policy.created_by_user_id)
            if policy.created_by_user_id is not None
            else None
        ),
        "created_at": timestamp(policy.created_at),
        "updated_at": timestamp(policy.updated_at),
    }


__all__ = ["AclService"]
