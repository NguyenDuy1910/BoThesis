"""Governed requests for user access to a Collection."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import AccessRequest, Item, TenantMembership, User
from bothesis.services.audit import AuditService
from bothesis.services.collection_access import CollectionAccessService
from bothesis.services import (
    ACCESS_MANAGE_PERMISSION,
    ACTIVE_STATUS,
    AdminConflictError,
    AdminNotFoundError,
    AdminValidationError,
    AuthContext,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)


class AccessRequestService:
    """Review Collection access requests and materialize approved grants."""

    def __init__(self, session: AsyncSession, *, audit: AuditService | None = None) -> None:
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
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            AccessRequest.tenant_id == tenant_id,
            AccessRequest.deleted_at.is_(None),
        ]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(User.email.ilike(term), User.display_name.ilike(term), Item.title.ilike(term))
            )
        if status:
            normalized = status.strip().casefold()
            if normalized not in {"pending", "approved", "denied", "cancelled"}:
                raise AdminValidationError("unsupported access request status")
            filters.append(AccessRequest.status == normalized)
        base = (
            select(AccessRequest, User, Item)
            .join(User, User.id == AccessRequest.requester_user_id)
            .join(Item, Item.id == AccessRequest.collection_item_id)
            .where(*filters)
        )
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = (
            await self._session.execute(
                base.order_by(AccessRequest.created_at.desc(), AccessRequest.id.desc())
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [self._payload(request, user=user, collection=item) for request, user, item in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def create_request(
        self,
        actor: AuthContext,
        *,
        requester_user_id: UUID,
        collection_item_id: UUID,
        requested_role: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor)
        if requester_user_id != actor.user_id:
            require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        user = await self._tenant_user(tenant_id, requester_user_id)
        collection = await self._collection(tenant_id, collection_item_id)
        role = requested_role.strip().casefold()
        if role not in {"owner", "editor", "viewer"}:
            raise AdminValidationError("requested role must be owner, editor, or viewer")
        duplicate = await self._session.scalar(
            select(AccessRequest.id).where(
                AccessRequest.tenant_id == tenant_id,
                AccessRequest.requester_user_id == user.id,
                AccessRequest.collection_item_id == collection.id,
                AccessRequest.requested_role == role,
                AccessRequest.status == "pending",
                AccessRequest.deleted_at.is_(None),
            )
        )
        if duplicate is not None:
            raise AdminConflictError("an equivalent Collection access request is pending")
        request = AccessRequest(
            tenant_id=tenant_id,
            requester_user_id=user.id,
            collection_item_id=collection.id,
            requested_role=role,
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
            action="collection.access.requested",
            resource_type="collection",
            resource_id=str(collection.id),
            details={"request_id": str(request.id), "requester_user_id": str(user.id)},
        )
        return self._payload(request, user=user, collection=collection)

    async def get_request(
        self, actor: AuthContext, request_id: UUID
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        row = (
            await self._session.execute(
                select(AccessRequest, User, Item)
                .join(User, User.id == AccessRequest.requester_user_id)
                .join(Item, Item.id == AccessRequest.collection_item_id)
                .where(
                    AccessRequest.id == request_id,
                    AccessRequest.tenant_id == tenant_id,
                    AccessRequest.deleted_at.is_(None),
                )
            )
        ).one_or_none()
        if row is None:
            raise AdminNotFoundError(f"access request not found: {request_id}")
        request, user, collection = row
        return self._payload(request, user=user, collection=collection)

    async def decide_request(
        self,
        actor: AuthContext,
        request_id: UUID,
        *,
        decision: str,
        review_note: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        request = await self._session.scalar(
            select(AccessRequest)
            .where(
                AccessRequest.id == request_id,
                AccessRequest.tenant_id == tenant_id,
                AccessRequest.deleted_at.is_(None),
            )
            .with_for_update()
        )
        if request is None:
            raise AdminNotFoundError(f"access request not found: {request_id}")
        if request.status != "pending":
            raise AdminConflictError("only pending access requests can be reviewed")
        normalized = decision.strip().casefold()
        if normalized not in {"approved", "denied"}:
            raise AdminValidationError("decision must be approved or denied")
        user = await self._tenant_user(tenant_id, request.requester_user_id)
        collection = await self._collection(tenant_id, request.collection_item_id)
        if normalized == "approved":
            await CollectionAccessService(self._session).grant(
                collection.id,
                principal_type="user",
                principal_id=user.id,
                role=request.requested_role,
                actor=actor,
            )
        request.status = normalized
        request.reviewed_by_user_id = actor.user_id
        request.review_note = (
            normalize_required_text(review_note, "review note", 4_000)
            if review_note is not None
            else None
        )
        request.reviewed_at = datetime.now(UTC)
        await self._session.flush()
        await self._audit.record(
            actor,
            action=f"collection.access_request.{normalized}",
            resource_type="collection",
            resource_id=str(collection.id),
            details={"request_id": str(request.id)},
        )
        return self._payload(request, user=user, collection=collection)

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
            raise AdminNotFoundError(f"tenant user not found: {user_id}")
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
            raise AdminNotFoundError(f"Collection not found: {item_id}")
        return item

    @staticmethod
    def _payload(request: AccessRequest, *, user: User, collection: Item) -> dict[str, Any]:
        return {
            "id": str(request.id),
            "requester": {
                "id": str(user.id),
                "email": user.email,
                "display_name": user.display_name,
            },
            "collection": {"id": str(collection.id), "title": collection.title},
            "requested_role": request.requested_role,
            "reason": request.reason,
            "status": request.status,
            "reviewed_by_user_id": (
                str(request.reviewed_by_user_id) if request.reviewed_by_user_id else None
            ),
            "review_note": request.review_note,
            "reviewed_at": timestamp(request.reviewed_at),
            "created_at": timestamp(request.created_at),
            "updated_at": timestamp(request.updated_at),
        }


__all__ = ["AccessRequestService"]
