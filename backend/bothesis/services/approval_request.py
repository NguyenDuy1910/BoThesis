"""Governed approval requests with type-specific decision effects."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Mapping
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import ApprovalRequest, Item, Role, TenantMembership, User
from bothesis.services import (
    ACCESS_MANAGE_PERMISSION,
    ACTIVE_STATUS,
    COLLECTION_ROLE_CODES,
    COLLECTION_SCOPE,
    SOURCE_MANAGE_PERMISSION,
    ControlPlaneConflictError,
    ControlPlaneNotFoundError,
    ControlPlaneValidationError,
    AuthContext,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)
from bothesis.services.audit import AuditService
from bothesis.services.identity_access.role_assignments import RoleAssignmentService


class ApprovalRequestService:
    """Store a shared approval lifecycle and dispatch explicit type behavior."""

    _TYPES = frozenset({"resource_access", "plugin_installation"})
    _STATUSES = frozenset({"pending", "approved", "denied", "cancelled"})

    def __init__(
        self,
        session: AsyncSession,
        *,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def list_requests(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
        request_type: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor)
        allowed_types = self._visible_types(actor, request_type)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            ApprovalRequest.tenant_id == tenant_id,
            ApprovalRequest.deleted_at.is_(None),
            ApprovalRequest.request_type.in_(allowed_types),
        ]
        if status is not None:
            filters.append(ApprovalRequest.status == self._status(status))
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    User.email.ilike(term),
                    User.display_name.ilike(term),
                    ApprovalRequest.target_id.ilike(term),
                )
            )
        base = (
            select(ApprovalRequest, User, Role)
            .join(User, User.id == ApprovalRequest.requester_user_id)
            .outerjoin(Role, Role.id == ApprovalRequest.requested_role_id)
            .where(*filters)
        )
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = (
            await self._session.execute(
                base.order_by(ApprovalRequest.created_at.desc(), ApprovalRequest.id.desc())
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [
                self._payload(request, user, role) for request, user, role in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def create_request(
        self,
        actor: AuthContext,
        *,
        request_type: str,
        target_id: str,
        details: Mapping[str, Any] | None = None,
        reason: str | None = None,
        requester_user_id: UUID | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor)
        normalized_type = self._request_type(request_type)
        requester_id = requester_user_id or actor.user_id
        if normalized_type == "resource_access":
            if requester_id != actor.user_id:
                require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
            await self._tenant_user(tenant_id, requester_id)
            normalized_target, requested_role_id = await self._resource_access_target(
                tenant_id, target_id, details
            )
            normalized_details: dict[str, Any] = {}
        else:
            require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
            requested_role_id = None
            normalized_target, normalized_details = self._plugin_target(target_id, details)
        normalized_reason = (
            normalize_required_text(reason, "request reason", 4_000)
            if reason is not None
            else None
        )
        duplicate = await self._session.scalar(
            select(ApprovalRequest.id).where(
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.requester_user_id == requester_id,
                ApprovalRequest.request_type == normalized_type,
                ApprovalRequest.target_id == normalized_target,
                ApprovalRequest.status == "pending",
                ApprovalRequest.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise ControlPlaneConflictError("an equivalent approval request is pending")
        request = ApprovalRequest(
            tenant_id=tenant_id,
            requester_user_id=requester_id,
            request_type=normalized_type,
            target_id=normalized_target,
            requested_role_id=requested_role_id,
            details=normalized_details,
            reason=normalized_reason,
        )
        self._session.add(request)
        await self._session.flush()
        user = await self._tenant_user(tenant_id, requester_id)
        requested_role = await self._requested_role(request)
        await self._audit.record(
            actor,
            action=f"approval_request.{normalized_type}.created",
            resource_type="approval_request",
            resource_id=str(request.id),
            details={"target_id": normalized_target},
        )
        return self._payload(request, user, requested_role)

    async def get_request(self, actor: AuthContext, request_id: UUID) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor)
        row = (
            await self._session.execute(
                select(ApprovalRequest, User, Role)
                .join(User, User.id == ApprovalRequest.requester_user_id)
                .outerjoin(Role, Role.id == ApprovalRequest.requested_role_id)
                .where(
                    ApprovalRequest.id == request_id,
                    ApprovalRequest.tenant_id == tenant_id,
                    ApprovalRequest.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise ControlPlaneNotFoundError(f"approval request not found: {request_id}")
        request, user, role = row
        self._require_reviewer(actor, request.request_type)
        return self._payload(request, user, role)

    async def update_request(
        self,
        actor: AuthContext,
        request_id: UUID,
        *,
        status: str,
        decision_note: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor)
        request = await self._session.scalar(
            select(ApprovalRequest)
            .where(
                ApprovalRequest.id == request_id,
                ApprovalRequest.tenant_id == tenant_id,
                ApprovalRequest.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if request is None:
            raise ControlPlaneNotFoundError(f"approval request not found: {request_id}")
        if request.status != "pending":
            raise ControlPlaneConflictError("only pending approval requests can change status")
        next_status = self._status(status)
        if next_status == "pending":
            raise ControlPlaneValidationError("an approval request cannot be returned to pending")
        if next_status == "cancelled":
            if request.requester_user_id != actor.user_id:
                self._require_reviewer(actor, request.request_type)
        else:
            self._require_reviewer(actor, request.request_type)
            if next_status == "approved":
                await self._apply_approval(actor, request)
        request.status = next_status
        request.decided_by_user_id = actor.user_id
        request.decision_note = (
            normalize_required_text(decision_note, "decision note", 4_000)
            if decision_note is not None
            else None
        )
        request.decided_at = datetime.now(UTC)
        await self._session.flush()
        # updated_at is set by the database on update, so it is expired after the
        # flush. Reading it while building the payload would run lazy I/O from
        # synchronous code; refreshing here keeps that load on the await chain.
        await self._session.refresh(request)
        user = await self._tenant_user(tenant_id, request.requester_user_id)
        requested_role = await self._requested_role(request)
        await self._audit.record(
            actor,
            action=f"approval_request.{request.request_type}.{next_status}",
            resource_type="approval_request",
            resource_id=str(request.id),
            details={"target_id": request.target_id},
        )
        return self._payload(request, user, requested_role)

    async def _apply_approval(self, actor: AuthContext, request: ApprovalRequest) -> None:
        if request.request_type == "resource_access":
            collection = await self._collection(request.tenant_id, UUID(request.target_id))
            role = await self._session.get(Role, request.requested_role_id)
            if role is None:
                raise ControlPlaneValidationError("the requested role no longer exists")
            # Approving is exactly the grant the request named, so an approved
            # request and an administrator's grant produce the same row.
            await RoleAssignmentService(self._session).grant_collection_role(
                collection.id,
                principal_type="user",
                principal_id=request.requester_user_id,
                role_code=role.code,
                created_by_user_id=actor.user_id,
            )
            return
        # Connector availability is deployment-owned. A plugin request records
        # governance approval; connection creation later validates the target
        # against the configured connector registry and obtains its credentials.
        return

    async def _resource_access_target(
        self,
        tenant_id: UUID,
        target_id: str,
        details: Mapping[str, Any] | None,
    ) -> tuple[str, UUID]:
        """Resolve the Collection and the canonical role the request asks for."""

        try:
            item_id = UUID(normalize_required_text(target_id, "target ID", 512))
        except ValueError as exc:
            raise ControlPlaneValidationError("resource access target ID must be a UUID") from exc
        await self._collection(tenant_id, item_id)
        values = dict(details or {})
        if set(values) != {"role"} or not isinstance(values["role"], str):
            raise ControlPlaneValidationError("resource access details must contain only role")
        role_code = values["role"].strip().casefold()
        if role_code not in COLLECTION_ROLE_CODES:
            raise ControlPlaneValidationError(
                "resource access role must be one of: " + ", ".join(COLLECTION_ROLE_CODES)
            )
        role_id = await self._session.scalar(
            select(Role.id).where(
                Role.code == role_code,
                Role.scope_type == COLLECTION_SCOPE,
                Role.status == ACTIVE_STATUS,
            )
        )
        if role_id is None:
            raise ControlPlaneValidationError(f"collection role is unavailable: {role_code}")
        return str(item_id), role_id

    def _plugin_target(
        self, target_id: str, details: Mapping[str, Any] | None
    ) -> tuple[str, dict[str, Any]]:
        if details:
            raise ControlPlaneValidationError("plugin installation details must be empty")
        key = normalize_required_text(target_id, "plugin target ID", 64).casefold()
        return key, {}

    async def _tenant_user(self, tenant_id: UUID, user_id: UUID) -> User:
        user = await self._session.scalar(
            select(User)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(
                User.id == user_id,
                User.status.is_(True),
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == ACTIVE_STATUS,
                TenantMembership.deleted_at.is_(None),
            )
        )
        if user is None:
            raise ControlPlaneNotFoundError(f"tenant user not found: {user_id}")
        return user

    async def _collection(self, tenant_id: UUID, item_id: UUID) -> Item:
        item = await self._session.scalar(
            select(Item).where(
                Item.id == item_id,
                Item.tenant_id == tenant_id,
                Item.item_type == "collection",
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if item is None:
            raise ControlPlaneNotFoundError(f"Collection not found: {item_id}")
        return item

    def _visible_types(self, actor: AuthContext, request_type: str | None) -> tuple[str, ...]:
        if request_type is not None:
            normalized = self._request_type(request_type)
            self._require_reviewer(actor, normalized)
            return (normalized,)
        visible = tuple(
            request_type
            for request_type, permission in (
                ("resource_access", ACCESS_MANAGE_PERMISSION),
                ("plugin_installation", SOURCE_MANAGE_PERMISSION),
            )
            if actor.has_permissions(permission)
        )
        if not visible:
            raise ControlPlaneValidationError("no approval request types are available to this actor")
        return visible

    @classmethod
    def _request_type(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in cls._TYPES:
            raise ControlPlaneValidationError("unsupported approval request type")
        return normalized

    @classmethod
    def _status(cls, value: str) -> str:
        normalized = value.strip().casefold()
        if normalized not in cls._STATUSES:
            raise ControlPlaneValidationError("unsupported approval request status")
        return normalized

    @staticmethod
    def _require_reviewer(actor: AuthContext, request_type: str) -> None:
        permission = (
            ACCESS_MANAGE_PERMISSION
            if request_type == "resource_access"
            else SOURCE_MANAGE_PERMISSION
        )
        require_tenant_permission(actor, permission)

    async def _requested_role(self, request: ApprovalRequest) -> Role | None:
        if request.requested_role_id is None:
            return None
        return await self._session.get(Role, request.requested_role_id)

    @staticmethod
    def _payload(
        request: ApprovalRequest, user: User, requested_role: Role | None
    ) -> dict[str, Any]:
        return {
            "id": str(request.id),
            "request_type": request.request_type,
            "target_id": request.target_id,
            "requested_role": (
                {
                    "id": str(requested_role.id),
                    "code": requested_role.code,
                    "display_name": requested_role.display_name,
                }
                if requested_role is not None
                else None
            ),
            "details": dict(request.details),
            "reason": request.reason,
            "status": request.status,
            "requester": {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
            },
            "decided_by_user_id": (
                str(request.decided_by_user_id) if request.decided_by_user_id else None
            ),
            "decision_note": request.decision_note,
            "decided_at": timestamp(request.decided_at),
            "created_at": timestamp(request.created_at),
            "updated_at": timestamp(request.updated_at),
        }


__all__ = ["ApprovalRequestService"]
