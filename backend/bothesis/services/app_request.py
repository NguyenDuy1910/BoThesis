"""Durable governance requests for apps that are not enabled in a workspace."""

from __future__ import annotations

from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import AppRequest, User
from bothesis.services import (
    AdminValidationError,
    AuthContext,
    SOURCE_MANAGE_PERMISSION,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)
from bothesis.services.audit import AuditService


class AppRequestService:
    """Create and list tenant-scoped app enablement requests."""

    def __init__(self, session: AsyncSession, *, audit: AuditService | None = None) -> None:
        self._session = session
        self._audit = audit or AuditService(session)

    async def list_requests(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        status: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [
            AppRequest.tenant_id == tenant_id,
            AppRequest.deleted_at.is_(None),
        ]
        if status is not None:
            normalized = status.strip().casefold()
            if normalized not in {"pending", "approved", "denied", "cancelled"}:
                raise AdminValidationError("unsupported app request status")
            filters.append(AppRequest.status == normalized)
        base = select(AppRequest, User).join(User, User.id == AppRequest.requester_user_id).where(*filters)
        total = await self._session.scalar(select(func.count()).select_from(base.subquery()))
        rows = (await self._session.execute(
            base.order_by(AppRequest.created_at.desc(), AppRequest.id.desc()).limit(page_size).offset(offset)
        )).all()
        return {
            "items": [self._payload(request, user) for request, user in rows],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def create_request(
        self, actor: AuthContext, *, connector_key: str, reason: str | None = None
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, SOURCE_MANAGE_PERMISSION)
        key = normalize_required_text(connector_key, "connector key", 64).casefold()
        normalized_reason = None
        if reason is not None and reason.strip():
            normalized_reason = normalize_required_text(reason, "request reason", 2_000)
        existing = await self._session.scalar(
            select(AppRequest).where(
                AppRequest.tenant_id == tenant_id,
                AppRequest.requester_user_id == actor.user_id,
                AppRequest.connector_key == key,
                AppRequest.status == "pending",
                AppRequest.deleted_at.is_(None),
            )
        )
        if existing is not None:
            user = await self._session.scalar(select(User).where(User.id == actor.user_id))
            if user is None:
                raise AdminValidationError("requesting user no longer exists")
            return self._payload(existing, user)
        request = AppRequest(
            tenant_id=tenant_id,
            requester_user_id=actor.user_id,
            connector_key=key,
            reason=normalized_reason,
        )
        self._session.add(request)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="app.requested",
            resource_type="app_request",
            resource_id=str(request.id),
            details={"connector_key": key},
        )
        user = await self._session.scalar(select(User).where(User.id == actor.user_id))
        if user is None:
            raise AdminValidationError("requesting user no longer exists")
        return self._payload(request, user)

    @staticmethod
    def _payload(request: AppRequest, user: User) -> dict[str, Any]:
        return {
            "id": str(request.id),
            "connector_key": request.connector_key,
            "reason": request.reason,
            "status": request.status,
            "requester": {
                "id": str(user.id),
                "display_name": user.display_name,
                "email": user.email,
            },
            "created_at": timestamp(request.created_at),
            "updated_at": timestamp(request.updated_at),
        }


__all__ = ["AppRequestService"]
