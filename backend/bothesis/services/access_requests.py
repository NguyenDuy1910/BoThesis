"""Tenant access request review and governed grant application."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import (
    AccessRequest,
    Document,
    Group,
    GroupMembership,
    Role,
    TenantMembership,
    User,
)
from bothesis.services import (
    ACCESS_MANAGE_PERMISSION,
    ACTIVE_STATUS,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuditService,
    AuthContext,
    AuthService,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)

_RESOURCE_TYPES = frozenset({"document", "group", "role"})


class AccessRequestService:
    """Review requests and atomically apply approved access grants."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        auth: AuthService | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._auth = auth or AuthService(session)
        self._audit = audit or AuditService(session)

    async def list_requests(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        status: str | None = None,
        resource_type: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        reviewer = User.__table__.alias("reviewer")
        filters = [
            AccessRequest.tenant_id == tenant_id,
            AccessRequest.deleted_at.is_(None),
        ]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    User.email.ilike(term),
                    User.display_name.ilike(term),
                    AccessRequest.resource_id.ilike(term),
                    AccessRequest.reason.ilike(term),
                )
            )
        if status:
            normalized_status = status.strip().casefold()
            if normalized_status not in {
                "pending",
                "approved",
                "denied",
                "cancelled",
            }:
                raise AdminValidationError("unsupported access request status")
            filters.append(AccessRequest.status == normalized_status)
        if resource_type:
            normalized_type = resource_type.strip().casefold()
            if normalized_type not in _RESOURCE_TYPES:
                raise AdminValidationError("unsupported access request resource type")
            filters.append(AccessRequest.resource_type == normalized_type)
        base = (
            select(
                AccessRequest,
                User.email,
                User.display_name,
                reviewer.c.email,
                reviewer.c.display_name,
            )
            .join(User, User.id == AccessRequest.requester_user_id)
            .outerjoin(reviewer, reviewer.c.id == AccessRequest.reviewed_by_user_id)
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        rows = (
            await self._session.execute(
                base.order_by(AccessRequest.created_at.desc(), AccessRequest.id.desc())
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [
                _request_payload(
                    request,
                    requester_email=email,
                    requester_name=display_name,
                    reviewer_email=reviewer_email,
                    reviewer_name=reviewer_name,
                )
                for request, email, display_name, reviewer_email, reviewer_name in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_request(
        self, actor: AuthContext, request_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        request = await self._request(tenant_id, request_id)
        requester = await self._session.get(User, request.requester_user_id)
        reviewer = (
            await self._session.get(User, request.reviewed_by_user_id)
            if request.reviewed_by_user_id is not None
            else None
        )
        if requester is None:
            raise AdminNotFoundError("access request user was not found")
        return _request_payload(
            request,
            requester_email=requester.email,
            requester_name=requester.display_name,
            reviewer_email=reviewer.email if reviewer else None,
            reviewer_name=reviewer.display_name if reviewer else None,
        )

    async def create_request(
        self,
        actor: AuthContext,
        *,
        requester_user_id: UUID,
        resource_type: str,
        resource_id: str,
        access_type: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        requester = await self._tenant_user(tenant_id, requester_user_id)
        normalized_type = resource_type.strip().casefold()
        if normalized_type not in _RESOURCE_TYPES:
            raise AdminValidationError("unsupported access request resource type")
        normalized_resource_id = normalize_required_text(
            resource_id, "resource ID", 512
        )
        normalized_access_type = normalize_required_text(
            access_type, "access type", 32
        ).casefold()
        await self._validate_resource(
            tenant_id, normalized_type, normalized_resource_id
        )
        duplicate = await self._session.scalar(
            select(AccessRequest.id).where(
                AccessRequest.tenant_id == tenant_id,
                AccessRequest.requester_user_id == requester.id,
                AccessRequest.resource_type == normalized_type,
                AccessRequest.resource_id == normalized_resource_id,
                AccessRequest.access_type == normalized_access_type,
                AccessRequest.status == "pending",
                AccessRequest.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise AdminConflictError("an equivalent access request is already pending")
        request = AccessRequest(
            tenant_id=tenant_id,
            requester_user_id=requester.id,
            resource_type=normalized_type,
            resource_id=normalized_resource_id,
            access_type=normalized_access_type,
            reason=(
                normalize_required_text(reason, "request reason", 4_000)
                if reason is not None
                else None
            ),
        )
        self._session.add(request)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="access_request.created",
            resource_type="access_request",
            resource_id=str(request.id),
            details={
                "requester_user_id": str(requester.id),
                "target_type": normalized_type,
                "target_id": normalized_resource_id,
            },
        )
        return _request_payload(
            request,
            requester_email=requester.email,
            requester_name=requester.display_name,
            reviewer_email=None,
            reviewer_name=None,
        )

    async def decide_request(
        self,
        actor: AuthContext,
        request_id: UUID,
        *,
        decision: str,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        request = await self._request(tenant_id, request_id, for_update=True)
        if request.status != "pending":
            raise AdminConflictError("only pending access requests can be reviewed")
        normalized_decision = decision.strip().casefold()
        if normalized_decision not in {"approved", "denied"}:
            raise AdminValidationError("decision must be approved or denied")
        requester = await self._tenant_user(tenant_id, request.requester_user_id)
        if normalized_decision == "approved":
            await self._apply_grant(tenant_id, requester, request)
        request.status = normalized_decision
        request.reviewed_by_user_id = actor.user_id
        request.review_note = (
            normalize_required_text(review_note, "review note", 4_000)
            if review_note is not None
            else None
        )
        request.reviewed_at = datetime.now(UTC)
        request.updated_at = request.reviewed_at
        await self._session.flush()
        await self._audit.record(
            actor,
            action=f"access_request.{normalized_decision}",
            resource_type="access_request",
            resource_id=str(request.id),
            details={
                "requester_user_id": str(requester.id),
                "target_type": request.resource_type,
                "target_id": request.resource_id,
            },
        )
        return _request_payload(
            request,
            requester_email=requester.email,
            requester_name=requester.display_name,
            reviewer_email=actor.email,
            reviewer_name=actor.display_name,
        )

    async def _apply_grant(
        self, tenant_id: UUID, requester: User, request: AccessRequest
    ) -> None:
        resource_uuid = _uuid_resource(request.resource_id)
        if request.resource_type == "document":
            document = await self._session.scalar(
                select(Document)
                .where(
                    Document.id == resource_uuid,
                    Document.tenant_id == tenant_id,
                    Document.lifecycle_status != "deleted",
                    Document.deleted_at.is_(None),
                )
                .with_for_update()
            )
            if document is None:
                raise AdminNotFoundError("requested document was not found")
            token = f"email:{requester.email.casefold()}"
            document.allowed_principal_tokens = sorted(
                {*document.allowed_principal_tokens, token}
            )
            document.denied_principal_tokens = sorted(
                set(document.denied_principal_tokens) - {token}
            )
            return
        if request.resource_type == "group":
            group = await self._session.scalar(
                select(Group).where(
                    Group.id == resource_uuid,
                    Group.tenant_id == tenant_id,
                    Group.status == ACTIVE_STATUS,
                    Group.deleted_at.is_(None),
                )
            )
            if group is None:
                raise AdminNotFoundError("requested group was not found")
            membership = await self._session.get(
                GroupMembership,
                {"group_id": group.id, "user_id": requester.id},
            )
            if membership is None:
                self._session.add(
                    GroupMembership(
                        group_id=group.id,
                        user_id=requester.id,
                        joined_at=datetime.now(UTC),
                    )
                )
            else:
                membership.status = ACTIVE_STATUS
                membership.deleted_at = None
                membership.joined_at = membership.joined_at or datetime.now(UTC)
            return
        if request.resource_type == "role":
            role = await self._session.scalar(
                select(Role).where(
                    Role.id == resource_uuid,
                    Role.tenant_id == tenant_id,
                    Role.status == ACTIVE_STATUS,
                )
            )
            if role is None:
                raise AdminNotFoundError("requested role was not found")
            await self._auth.assign_membership(requester.id, tenant_id, role.id)
            return
        raise AdminValidationError("unsupported access request resource type")

    async def _request(
        self, tenant_id: UUID, request_id: UUID, *, for_update: bool = False
    ) -> AccessRequest:
        statement = select(AccessRequest).where(
            AccessRequest.id == request_id,
            AccessRequest.tenant_id == tenant_id,
            AccessRequest.deleted_at.is_(None),
        )
        if for_update:
            statement = statement.with_for_update()
        request = await self._session.scalar(statement)
        if request is None:
            raise AdminNotFoundError(f"access request not found: {request_id}")
        return request

    async def _tenant_user(self, tenant_id: UUID, user_id: UUID) -> User:
        user = await self._session.scalar(
            select(User)
            .join(TenantMembership, TenantMembership.user_id == User.id)
            .where(
                User.id == user_id,
                User.status == ACTIVE_STATUS,
                TenantMembership.tenant_id == tenant_id,
                TenantMembership.status == ACTIVE_STATUS,
                TenantMembership.deleted_at.is_(None),
            )
        )
        if user is None:
            raise AdminNotFoundError(f"user not found: {user_id}")
        return user

    async def _validate_resource(
        self, tenant_id: UUID, resource_type: str, resource_id: str
    ) -> None:
        resource_uuid = _uuid_resource(resource_id)
        model = {"document": Document, "group": Group, "role": Role}[resource_type]
        statement = select(model.id).where(model.id == resource_uuid)
        if model is Document:
            statement = statement.where(
                Document.tenant_id == tenant_id,
                Document.lifecycle_status != "deleted",
                Document.deleted_at.is_(None),
            )
        elif model is Group:
            statement = statement.where(
                Group.tenant_id == tenant_id,
                Group.deleted_at.is_(None),
            )
        else:
            statement = statement.where(Role.tenant_id == tenant_id)
        if await self._session.scalar(statement) is None:
            raise AdminNotFoundError(f"{resource_type} not found: {resource_id}")


def _uuid_resource(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        raise AdminValidationError("resource ID must be a UUID") from exc


def _request_payload(
    request: AccessRequest,
    *,
    requester_email: str,
    requester_name: str | None,
    reviewer_email: str | None,
    reviewer_name: str | None,
) -> dict[str, Any]:
    return {
        "id": str(request.id),
        "resource_type": request.resource_type,
        "resource_id": request.resource_id,
        "access_type": request.access_type,
        "reason": request.reason,
        "status": request.status,
        "requester": {
            "id": str(request.requester_user_id),
            "email": requester_email,
            "display_name": requester_name,
        },
        "reviewer": (
            {
                "id": str(request.reviewed_by_user_id),
                "email": reviewer_email,
                "display_name": reviewer_name,
            }
            if request.reviewed_by_user_id is not None
            else None
        ),
        "review_note": request.review_note,
        "reviewed_at": timestamp(request.reviewed_at),
        "created_at": timestamp(request.created_at),
        "updated_at": timestamp(request.updated_at),
    }


__all__ = ["AccessRequestService"]
