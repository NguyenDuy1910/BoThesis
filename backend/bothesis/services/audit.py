"""Append-only tenant administration audit service."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import AuditLog, User
from bothesis.services import (
    AUDIT_READ_PERMISSION,
    AuthContext,
    normalize_page,
    normalize_required_text,
    require_tenant_permission,
    timestamp,
)

_SENSITIVE_DETAIL_TERMS = frozenset(
    {"authorization", "content", "credential", "password", "secret", "token"}
)


class AuditService:
    """Write safe operational metadata and query it within one tenant."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def record(
        self,
        actor: AuthContext,
        *,
        action: str,
        resource_type: str,
        resource_id: str | None = None,
        outcome: str = "success",
        details: Mapping[str, Any] | None = None,
    ) -> AuditLog:
        tenant_id = require_tenant_permission(actor)
        event = AuditLog(
            tenant_id=tenant_id,
            actor_user_id=actor.user_id,
            action=normalize_required_text(action, "audit action", 96).casefold(),
            resource_type=normalize_required_text(
                resource_type, "resource type", 32
            ).casefold(),
            resource_id=(
                normalize_required_text(resource_id, "resource ID", 512)
                if resource_id is not None
                else None
            ),
            outcome=normalize_required_text(outcome, "audit outcome", 16).casefold(),
            details=_safe_details(details or {}),
        )
        self._session.add(event)
        await self._session.flush()
        return event

    async def list_events(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        search: str | None = None,
        action: str | None = None,
        resource_type: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = require_tenant_permission(actor, AUDIT_READ_PERMISSION)
        page, page_size, offset = normalize_page(page, page_size)
        filters = [AuditLog.tenant_id == tenant_id]
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    AuditLog.action.ilike(term),
                    AuditLog.resource_id.ilike(term),
                    User.email.ilike(term),
                    User.display_name.ilike(term),
                )
            )
        if action:
            filters.append(AuditLog.action == action.strip().casefold())
        if resource_type:
            filters.append(
                AuditLog.resource_type == resource_type.strip().casefold()
            )

        base = (
            select(AuditLog, User.email, User.display_name)
            .outerjoin(User, User.id == AuditLog.actor_user_id)
            .where(*filters)
        )
        total = await self._session.scalar(
            select(func.count()).select_from(base.subquery())
        )
        rows = (
            await self._session.execute(
                base.order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .limit(page_size)
                .offset(offset)
            )
        ).all()
        return {
            "items": [
                {
                    "id": str(event.id),
                    "action": event.action,
                    "resource_type": event.resource_type,
                    "resource_id": event.resource_id,
                    "outcome": event.outcome,
                    "details": dict(event.details),
                    "actor": {
                        "id": str(event.actor_user_id)
                        if event.actor_user_id is not None
                        else None,
                        "email": email,
                        "display_name": display_name,
                    },
                    "created_at": timestamp(event.created_at),
                }
                for event, email, display_name in rows
            ],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }


def _safe_details(value: Mapping[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for raw_key, raw_value in value.items():
        key = str(raw_key)[:128]
        normalized_key = key.casefold()
        if any(term in normalized_key for term in _SENSITIVE_DETAIL_TERMS):
            safe[key] = "[redacted]"
        elif isinstance(raw_value, Mapping):
            safe[key] = _safe_details(raw_value)
        elif isinstance(raw_value, (str, int, float, bool)) or raw_value is None:
            safe[key] = raw_value if not isinstance(raw_value, str) else raw_value[:512]
        elif isinstance(raw_value, (list, tuple)):
            safe[key] = [str(item)[:256] for item in raw_value[:50]]
        else:
            safe[key] = str(raw_value)[:512]
    return safe


__all__ = ["AuditService"]
