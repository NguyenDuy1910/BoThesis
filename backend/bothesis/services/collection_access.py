"""Collection-scoped authorization with bounded hierarchy inheritance."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import and_, func, literal, or_, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.db.models import CollectionAccess, Group, Item, TenantMembership, User
from bothesis.services import (
    ACCESS_MANAGE_PERMISSION,
    ACTIVE_STATUS,
    AdminNotFoundError,
    AdminValidationError,
    AuthContext,
    AuthorizationError,
    DocumentNotFoundError,
    require_tenant_permission,
)

_ROLE_RANK = {"viewer": 1, "editor": 2, "owner": 3}


class CollectionAccessService:
    """Resolve and administer user/group access to Collection subtrees."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def grant(
        self,
        item_id: UUID,
        *,
        principal_type: str,
        principal_id: UUID,
        role: str,
        actor: AuthContext,
    ) -> CollectionAccess:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        item = await self._collection(item_id, tenant_id=tenant_id)
        normalized_type = principal_type.strip().casefold()
        normalized_role = role.strip().casefold()
        if normalized_type not in {"user", "group"}:
            raise AdminValidationError("collection principal must be user or group")
        if normalized_role not in _ROLE_RANK:
            raise AdminValidationError("collection role must be owner, editor, or viewer")
        await self._validate_principal(
            tenant_id, principal_type=normalized_type, principal_id=principal_id
        )
        grant = await self._session.scalar(
            insert(CollectionAccess)
            .values(
                item_id=item.id,
                principal_type=normalized_type,
                principal_id=principal_id,
                role=normalized_role,
                created_by_user_id=actor.user_id,
                deleted_at=None,
            )
            .on_conflict_do_update(
                index_elements=[
                    CollectionAccess.item_id,
                    CollectionAccess.principal_type,
                    CollectionAccess.principal_id,
                ],
                set_={
                    "role": normalized_role,
                    "created_by_user_id": actor.user_id,
                    "deleted_at": None,
                    "updated_at": datetime.now(UTC),
                },
            )
            .returning(CollectionAccess)
        )
        if grant is None:
            raise RuntimeError("collection access grant was not stored")
        return grant

    async def revoke(
        self,
        item_id: UUID,
        *,
        principal_type: str,
        principal_id: UUID,
        actor: AuthContext,
    ) -> None:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        await self._collection(item_id, tenant_id=tenant_id)
        grant = await self._session.get(
            CollectionAccess,
            {
                "item_id": item_id,
                "principal_type": principal_type.strip().casefold(),
                "principal_id": principal_id,
            },
        )
        if grant is None or grant.deleted_at is not None:
            raise AdminNotFoundError("collection access grant not found")
        grant.deleted_at = datetime.now(UTC)
        await self._session.flush()

    async def list_grants(
        self,
        item_id: UUID,
        *,
        actor: AuthContext,
        page: int = 1,
        page_size: int = 100,
    ) -> dict[str, object]:
        tenant_id = require_tenant_permission(actor, ACCESS_MANAGE_PERMISSION)
        await self._collection(item_id, tenant_id=tenant_id)
        if page < 1 or not 1 <= page_size <= 100:
            raise AdminValidationError("invalid collection grant pagination")
        filters = (
            CollectionAccess.item_id == item_id,
            CollectionAccess.deleted_at.is_(None),
        )
        total = await self._session.scalar(
            select(func.count()).select_from(CollectionAccess).where(*filters)
        )
        grants = list(
            await self._session.scalars(
                select(CollectionAccess)
                .where(*filters)
                .order_by(
                    CollectionAccess.principal_type,
                    CollectionAccess.principal_id,
                )
                .limit(page_size)
                .offset((page - 1) * page_size)
            )
        )
        return {
            "items": [self._payload(grant) for grant in grants],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def allowed_collection_ids(self, access: AuthContext) -> tuple[UUID, ...]:
        if access.tenant_id is None:
            return ()
        active_collections = and_(
            Item.tenant_id == access.tenant_id,
            Item.item_type == "collection",
            Item.status != "deleted",
            Item.deleted_at.is_(None),
        )
        if access.is_admin:
            return tuple(
                await self._session.scalars(
                    select(Item.id).where(active_collections).order_by(Item.id)
                )
            )

        principal_match = and_(
            CollectionAccess.principal_type == "user",
            CollectionAccess.principal_id == access.user_id,
        )
        if access.group_ids:
            principal_match = or_(
                principal_match,
                and_(
                    CollectionAccess.principal_type == "group",
                    CollectionAccess.principal_id.in_(access.group_ids),
                ),
            )
        seed = (
            select(Item.id.label("item_id"))
            .join(CollectionAccess, CollectionAccess.item_id == Item.id)
            .where(
                active_collections,
                CollectionAccess.deleted_at.is_(None),
                principal_match,
            )
            .cte("accessible_collections", recursive=True)
        )
        descendants = select(Item.id.label("item_id")).join(
            seed, Item.parent_item_id == seed.c.item_id
        ).where(
            active_collections,
            Item.inherit_access.is_(True),
        )
        accessible = seed.union(descendants)
        return tuple(
            await self._session.scalars(
                select(accessible.c.item_id).distinct().order_by(accessible.c.item_id)
            )
        )

    async def authorization_collection_id(
        self, item_id: UUID, *, tenant_id: UUID
    ) -> UUID | None:
        ancestry = (
            select(
                Item.id.label("item_id"),
                Item.parent_item_id.label("parent_item_id"),
                Item.item_type.label("item_type"),
                literal(0).label("depth"),
            )
            .where(
                Item.id == item_id,
                Item.tenant_id == tenant_id,
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
            .cte("item_ancestry", recursive=True)
        )
        parent = Item.__table__.alias("parent_item")
        ancestry = ancestry.union_all(
            select(
                parent.c.id,
                parent.c.parent_item_id,
                parent.c.item_type,
                ancestry.c.depth + 1,
            ).where(
                parent.c.id == ancestry.c.parent_item_id,
                parent.c.tenant_id == tenant_id,
                parent.c.status != "deleted",
                parent.c.deleted_at.is_(None),
            )
        )
        return await self._session.scalar(
            select(ancestry.c.item_id)
            .where(ancestry.c.item_type == "collection")
            .order_by(ancestry.c.depth)
            .limit(1)
        )

    async def require_item_access(
        self,
        item_id: UUID,
        *,
        access: AuthContext,
        minimum_role: str = "viewer",
    ) -> Item:
        if access.tenant_id is None:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        item = await self._session.scalar(
            select(Item).where(
                Item.id == item_id,
                Item.tenant_id == access.tenant_id,
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if item is None:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        collection_id = await self.authorization_collection_id(
            item.id, tenant_id=access.tenant_id
        )
        allowed = set(await self.allowed_collection_ids(access))
        if collection_id is None or collection_id not in allowed:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        if access.is_admin or minimum_role == "viewer":
            return item
        effective_role = await self._effective_role(collection_id, access=access)
        if _ROLE_RANK.get(effective_role or "", 0) < _ROLE_RANK[minimum_role]:
            raise AuthorizationError(f"{minimum_role} collection access is required")
        return item

    async def _effective_role(
        self, collection_id: UUID, *, access: AuthContext
    ) -> str | None:
        assert access.tenant_id is not None
        current_id: UUID | None = collection_id
        rank = 0
        while current_id is not None:
            collection = await self._collection(current_id, tenant_id=access.tenant_id)
            filters = [
                CollectionAccess.item_id == current_id,
                CollectionAccess.deleted_at.is_(None),
                or_(
                    and_(
                        CollectionAccess.principal_type == "user",
                        CollectionAccess.principal_id == access.user_id,
                    ),
                    and_(
                        CollectionAccess.principal_type == "group",
                        CollectionAccess.principal_id.in_(access.group_ids or [UUID(int=0)]),
                    ),
                ),
            ]
            roles = await self._session.scalars(select(CollectionAccess.role).where(*filters))
            rank = max((rank, *(_ROLE_RANK[role] for role in roles)))
            if not collection.inherit_access:
                break
            current_id = collection.parent_item_id
        return next((role for role, value in _ROLE_RANK.items() if value == rank), None)

    async def _collection(self, item_id: UUID, *, tenant_id: UUID) -> Item:
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
            raise AdminNotFoundError(f"collection not found: {item_id}")
        return item

    async def _validate_principal(
        self, tenant_id: UUID, *, principal_type: str, principal_id: UUID
    ) -> None:
        if principal_type == "group":
            principal = await self._session.scalar(
                select(Group.id).where(
                    Group.id == principal_id,
                    Group.tenant_id == tenant_id,
                    Group.status == ACTIVE_STATUS,
                    Group.deleted_at.is_(None),
                )
            )
        else:
            principal = await self._session.scalar(
                select(User.id)
                .join(TenantMembership, TenantMembership.user_id == User.id)
                .where(
                    User.id == principal_id,
                    User.status == ACTIVE_STATUS,
                    TenantMembership.tenant_id == tenant_id,
                    TenantMembership.status == ACTIVE_STATUS,
                    TenantMembership.deleted_at.is_(None),
                )
            )
        if principal is None:
            raise AdminNotFoundError(f"{principal_type} principal not found")

    @staticmethod
    def _payload(grant: CollectionAccess) -> dict[str, object]:
        return {
            "item_id": str(grant.item_id),
            "principal_type": grant.principal_type,
            "principal_id": str(grant.principal_id),
            "role": grant.role,
            "created_by_user_id": (
                str(grant.created_by_user_id) if grant.created_by_user_id else None
            ),
            "created_at": grant.created_at.isoformat(),
            "updated_at": grant.updated_at.isoformat(),
        }


__all__ = ["CollectionAccessService"]
