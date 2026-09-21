"""The single authorization path: WHO, ROLE, SCOPE, PERMISSION, RESOURCE.

Callers ask whether an actor may perform a named product action on a resource.
How the answer is reached — a tenant-wide grant, a grant on the Collection, a
grant on an ancestor Collection, a grant held through a group — stays here.

Scope widens outward, never inward. A capability granted at tenant scope
applies to every Collection in that tenant, which is what lets a workspace
administrator read the whole workspace without a per-Collection grant and
without a special case in the resolver. Platform capability grants nothing
inside a tenant: administering the platform and reading a workspace's
knowledge are separate things.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import and_, false, literal, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload

from bothesis.db.models import Item, Role, RoleAssignment, RolePermission
from bothesis.services import (
    ACTIVE_STATUS,
    COLLECTION_READ_PERMISSION,
    AuthContext,
    AuthorizationError,
    DocumentNotFoundError,
)


class AuthorizationService:
    """Resolve effective permissions on Items, and enforce them."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def require_item(
        self,
        item_id: UUID,
        *,
        access: AuthContext,
        permission: str = COLLECTION_READ_PERMISSION,
    ) -> Item:
        """Return the Item only if the actor holds ``permission`` on it.

        An actor who cannot even read the Item is told it does not exist, so a
        failed check never confirms that an Item they may not see is there.
        """

        if access.tenant_id is None:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        # Callers project the authorized Item outside this session's await
        # chain, so its upload lifecycle is loaded here. A lazy load would run
        # asyncpg I/O from synchronous code and fail with MissingGreenlet.
        item = await self._session.scalar(
            select(Item)
            .options(joinedload(Item.upload))
            .where(
                Item.id == item_id,
                Item.tenant_id == access.tenant_id,
                Item.status != "deleted",
                Item.deleted_at.is_(None),
            )
        )
        if item is None:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        effective = await self.permissions_for_item(item.id, access=access)
        if COLLECTION_READ_PERMISSION not in effective:
            raise DocumentNotFoundError(f"item not found: {item_id}")
        if permission not in effective:
            raise AuthorizationError(f"{permission} is required for this Collection")
        return item

    async def permissions_for_item(
        self, item_id: UUID, *, access: AuthContext
    ) -> frozenset[str]:
        """Return every capability the actor holds on one Item.

        The result is the union of what they hold tenant-wide and what the
        Item's own grants give them. Grants are collected from the Item and
        from each ancestor it still inherits from in one recursive query,
        rather than a walk that issues a query per level.
        """

        if access.tenant_id is None:
            return frozenset()
        tenant_wide = frozenset(access.permission_codes)
        ancestry = self._ancestry(item_id, tenant_id=access.tenant_id)
        inherited = await self._session.scalars(
            select(RolePermission.permission_code)
            .distinct()
            .select_from(ancestry)
            .join(RoleAssignment, RoleAssignment.item_id == ancestry.c.item_id)
            .join(
                Role,
                and_(Role.id == RoleAssignment.role_id, Role.status == ACTIVE_STATUS),
            )
            .join(RolePermission, RolePermission.granted_by(Role.id))
            .where(
                RoleAssignment.deleted_at.is_(None),
                _principal_match(access),
            )
        )
        return tenant_wide | frozenset(inherited)

    async def allowed_collection_ids(
        self,
        access: AuthContext,
        *,
        permission: str = COLLECTION_READ_PERMISSION,
    ) -> tuple[UUID, ...]:
        """Return the Collections the actor holds ``permission`` on.

        Used to filter retrieval and listings, so it must answer with Collection
        identity only and never with content.
        """

        if access.tenant_id is None:
            return ()
        active_collections = and_(
            Item.tenant_id == access.tenant_id,
            Item.item_type == "collection",
            Item.status != "deleted",
            Item.deleted_at.is_(None),
        )
        if permission in access.permission_codes:
            return tuple(
                await self._session.scalars(
                    select(Item.id).where(active_collections).order_by(Item.id)
                )
            )

        granted = (
            select(Item.id.label("item_id"))
            .join(RoleAssignment, RoleAssignment.item_id == Item.id)
            .join(
                Role,
                and_(Role.id == RoleAssignment.role_id, Role.status == ACTIVE_STATUS),
            )
            .join(RolePermission, RolePermission.granted_by(Role.id))
            .where(
                active_collections,
                RoleAssignment.deleted_at.is_(None),
                RolePermission.permission_code == permission,
                _principal_match(access),
            )
            .cte("granted_collections", recursive=True)
        )
        descendants = (
            select(Item.id.label("item_id"))
            .join(granted, Item.parent_item_id == granted.c.item_id)
            .where(active_collections, Item.inherit_access.is_(True))
        )
        accessible = granted.union(descendants)
        return tuple(
            await self._session.scalars(
                select(accessible.c.item_id).distinct().order_by(accessible.c.item_id)
            )
        )

    async def governing_collection_id(
        self, item_id: UUID, *, tenant_id: UUID
    ) -> UUID | None:
        """Return the nearest Collection an Item belongs to, itself included."""

        ancestry = self._ancestry(item_id, tenant_id=tenant_id, ignore_inheritance=True)
        return await self._session.scalar(
            select(ancestry.c.item_id)
            .where(ancestry.c.item_type == "collection")
            .order_by(ancestry.c.depth)
            .limit(1)
        )

    def _ancestry(
        self, item_id: UUID, *, tenant_id: UUID, ignore_inheritance: bool = False
    ):
        """Build the Item and the ancestors its access still flows from.

        Climbing stops at an Item that ended inheritance: that Item is its own
        authorization boundary, so grants above it do not reach down past it.
        """

        ancestry = (
            select(
                Item.id.label("item_id"),
                Item.parent_item_id.label("parent_item_id"),
                Item.item_type.label("item_type"),
                Item.inherit_access.label("inherit_access"),
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
        parent = Item.__table__.alias("ancestor_item")
        climb = select(
            parent.c.id,
            parent.c.parent_item_id,
            parent.c.item_type,
            parent.c.inherit_access,
            ancestry.c.depth + 1,
        ).where(
            parent.c.id == ancestry.c.parent_item_id,
            parent.c.tenant_id == tenant_id,
            parent.c.status != "deleted",
            parent.c.deleted_at.is_(None),
        )
        if not ignore_inheritance:
            climb = climb.where(ancestry.c.inherit_access.is_(True))
        return ancestry.union_all(climb)


def _principal_match(access: AuthContext):
    """Match grants held directly, or held through one of the actor's groups."""

    if access.user_id is None:
        return false()
    direct = RoleAssignment.user_id == access.user_id
    if not access.group_ids:
        return direct
    return or_(direct, RoleAssignment.group_id.in_(access.group_ids))


__all__ = ["AuthorizationService"]
