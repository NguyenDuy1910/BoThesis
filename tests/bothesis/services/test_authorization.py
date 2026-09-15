"""Authorization boundaries, exercised through permissions rather than plumbing.

Every test here asks the question a product owner would ask — "can this person
do this to that?" — so the suite keeps holding if the resolver is rewritten
again. What it must never allow is an answer that arrives through a special
case: an admin flag, a wildcard permission code, or a scope that quietly
widens.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator, Iterable
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bothesis.db.models import (
    Base,
    Group,
    GroupMembership,
    Item,
    Role,
    RoleAssignment,
    RolePermission,
)
from bothesis.services import (
    COLLECTION_DELETE_PERMISSION,
    COLLECTION_EDITOR_ROLE,
    COLLECTION_OWNER_ROLE,
    COLLECTION_READ_PERMISSION,
    COLLECTION_SHARE_PERMISSION,
    COLLECTION_UPDATE_PERMISSION,
    COLLECTION_VIEWER_ROLE,
    PLATFORM_ADMIN_ROLE,
    TENANT_ADMIN_ROLE,
    TENANT_MEMBER_ROLE,
    AuthContext,
    AuthorizationError,
    DocumentNotFoundError,
)
from bothesis.services.identity_access.authorization import AuthorizationService
from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services.identity_access.role_assignments import RoleAssignmentService
from bothesis.services.item import ItemService

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL authorization tests",
)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert TEST_DATABASE_URL is not None
    schema = f"test_authz_{uuid4().hex}"
    admin_engine = create_async_engine(TEST_DATABASE_URL)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        await IdentityStoreService(session).sync_system_roles()

    try:
        yield factory
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


async def _system_role_id(session: AsyncSession, code: str) -> UUID:
    role_id = await session.scalar(
        select(Role.id).where(Role.code == code, Role.is_system)
    )
    assert role_id is not None
    return role_id


async def _member(
    session: AsyncSession,
    tenant_id: UUID,
    email: str,
    *,
    tenant_role: str = TENANT_MEMBER_ROLE,
) -> UUID:
    """Add one member holding one system tenant role."""

    identity = IdentityStoreService(session)
    user = await identity.create_user(email)
    await identity.assign_membership(user.id, tenant_id)
    await RoleAssignmentService(session).replace_tenant_roles(
        user_id=user.id,
        tenant_id=tenant_id,
        role_ids=[await _system_role_id(session, tenant_role)],
    )
    return user.id


async def _grant(
    session: AsyncSession,
    item_id: UUID,
    *,
    role_code: str,
    user_id: UUID | None = None,
    group_id: UUID | None = None,
) -> None:
    await RoleAssignmentService(session).grant_collection_role(
        item_id,
        principal_type="user" if user_id is not None else "group",
        principal_id=user_id if user_id is not None else group_id,
        role_code=role_code,
    )


async def _context(
    session: AsyncSession, user_id: UUID, tenant_id: UUID
) -> AuthContext:
    return await IdentityStoreService(session).get_context(user_id, tenant_id=tenant_id)


async def _may(
    session: AsyncSession,
    actor: AuthContext,
    item_id: UUID,
    permissions: Iterable[str],
) -> set[str]:
    """Return which of the named permissions the actor holds on the Item."""

    effective = await AuthorizationService(session).permissions_for_item(
        item_id, access=actor
    )
    return {permission for permission in permissions if permission in effective}


@pytest.mark.asyncio
async def test_a_member_without_a_grant_cannot_reach_a_collection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A private Collection stays private, and says nothing about existing."""

    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        owner_id = await _member(session, tenant.id, "owner@example.com")
        stranger_id = await _member(session, tenant.id, "stranger@example.com")
        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id, title="Board minutes", created_by_user_id=owner_id
        )
        await _grant(session, collection.id, role_code=COLLECTION_OWNER_ROLE, user_id=owner_id)

        owner = await _context(session, owner_id, tenant.id)
        stranger = await _context(session, stranger_id, tenant.id)
        authorization = AuthorizationService(session)

        assert await authorization.require_item(collection.id, access=owner)
        # Not "forbidden": an unreachable Collection must not be confirmed to exist.
        with pytest.raises(DocumentNotFoundError):
            await authorization.require_item(collection.id, access=stranger)
        assert await authorization.allowed_collection_ids(stranger) == ()


@pytest.mark.asyncio
async def test_collection_roles_separate_reading_editing_and_owning(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        owner_id = await _member(session, tenant.id, "owner@example.com")
        editor_id = await _member(session, tenant.id, "editor@example.com")
        viewer_id = await _member(session, tenant.id, "viewer@example.com")
        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id, title="Handbook", created_by_user_id=owner_id
        )
        for user_id, role_code in (
            (owner_id, COLLECTION_OWNER_ROLE),
            (editor_id, COLLECTION_EDITOR_ROLE),
            (viewer_id, COLLECTION_VIEWER_ROLE),
        ):
            await _grant(session, collection.id, role_code=role_code, user_id=user_id)

        every = (
            COLLECTION_READ_PERMISSION,
            COLLECTION_UPDATE_PERMISSION,
            COLLECTION_DELETE_PERMISSION,
            COLLECTION_SHARE_PERMISSION,
        )
        viewer = await _context(session, viewer_id, tenant.id)
        editor = await _context(session, editor_id, tenant.id)
        owner = await _context(session, owner_id, tenant.id)

        assert await _may(session, viewer, collection.id, every) == {
            COLLECTION_READ_PERMISSION
        }
        assert await _may(session, editor, collection.id, every) == {
            COLLECTION_READ_PERMISSION,
            COLLECTION_UPDATE_PERMISSION,
        }
        assert await _may(session, owner, collection.id, every) == set(every)

        authorization = AuthorizationService(session)
        # A viewer sees the Collection, so being refused an edit is an explicit
        # refusal rather than a claim that it is not there.
        with pytest.raises(AuthorizationError, match=COLLECTION_UPDATE_PERMISSION):
            await authorization.require_item(
                collection.id, access=viewer, permission=COLLECTION_UPDATE_PERMISSION
            )
        with pytest.raises(AuthorizationError, match=COLLECTION_SHARE_PERMISSION):
            await authorization.require_item(
                collection.id, access=editor, permission=COLLECTION_SHARE_PERMISSION
            )


@pytest.mark.asyncio
async def test_access_reaches_documents_and_nested_collections_by_inheritance(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        items = ItemService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        reader_id = await _member(session, tenant.id, "reader@example.com")

        handbook = await items.create_collection(
            tenant_id=tenant.id, title="Handbook", created_by_user_id=reader_id
        )
        policies = await items.create_collection(
            tenant_id=tenant.id,
            title="Policies",
            created_by_user_id=reader_id,
            parent_item_id=handbook.id,
        )
        leave_policy = await items.create_document(
            tenant_id=tenant.id,
            parent_item_id=policies.id,
            title="Leave policy",
            document_type="pdf",
            created_by_user_id=reader_id,
        )
        await _grant(
            session, handbook.id, role_code=COLLECTION_EDITOR_ROLE, user_id=reader_id
        )

        reader = await _context(session, reader_id, tenant.id)
        authorization = AuthorizationService(session)

        # One grant at the top reaches the nested Collection and the Document.
        assert set(await authorization.allowed_collection_ids(reader)) == {
            handbook.id,
            policies.id,
        }
        assert await authorization.require_item(
            leave_policy.id, access=reader, permission=COLLECTION_UPDATE_PERMISSION
        )
        assert (
            await authorization.governing_collection_id(
                leave_policy.id, tenant_id=tenant.id
            )
            == policies.id
        )


@pytest.mark.asyncio
async def test_a_collection_that_stops_inheriting_is_its_own_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        items = ItemService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        reader_id = await _member(session, tenant.id, "reader@example.com")
        legal_id = await _member(session, tenant.id, "legal@example.com")

        handbook = await items.create_collection(
            tenant_id=tenant.id, title="Handbook", created_by_user_id=reader_id
        )
        sealed = await items.create_collection(
            tenant_id=tenant.id,
            title="Sealed",
            created_by_user_id=reader_id,
            parent_item_id=handbook.id,
            inherit_access=False,
        )
        settlement = await items.create_document(
            tenant_id=tenant.id,
            parent_item_id=sealed.id,
            title="Settlement",
            document_type="pdf",
            created_by_user_id=reader_id,
        )
        await _grant(
            session, handbook.id, role_code=COLLECTION_OWNER_ROLE, user_id=reader_id
        )
        await _grant(
            session, sealed.id, role_code=COLLECTION_VIEWER_ROLE, user_id=legal_id
        )

        reader = await _context(session, reader_id, tenant.id)
        legal = await _context(session, legal_id, tenant.id)
        authorization = AuthorizationService(session)

        # Owning the parent does not reach past a Collection that ended inheritance.
        assert await authorization.allowed_collection_ids(reader) == (handbook.id,)
        with pytest.raises(DocumentNotFoundError):
            await authorization.require_item(sealed.id, access=reader)
        with pytest.raises(DocumentNotFoundError):
            await authorization.require_item(settlement.id, access=reader)

        # The grant made on the boundary itself still governs what is inside it.
        assert await authorization.require_item(settlement.id, access=legal)
        assert await authorization.allowed_collection_ids(legal) == (sealed.id,)


@pytest.mark.asyncio
async def test_a_group_grant_reaches_its_members_and_stops_when_they_leave(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A group is a principal, not a second kind of permission."""

    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        analyst_id = await _member(session, tenant.id, "analyst@example.com")
        outsider_id = await _member(session, tenant.id, "outsider@example.com")
        group = Group(tenant_id=tenant.id, code="analysts", display_name="Analysts")
        session.add(group)
        await session.flush()
        membership = GroupMembership(group_id=group.id, user_id=analyst_id)
        session.add(membership)
        await session.flush()

        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id, title="Revenue", created_by_user_id=analyst_id
        )
        await _grant(
            session, collection.id, role_code=COLLECTION_EDITOR_ROLE, group_id=group.id
        )

        analyst = await _context(session, analyst_id, tenant.id)
        outsider = await _context(session, outsider_id, tenant.id)
        authorization = AuthorizationService(session)

        assert analyst.group_ids == (group.id,)
        assert await authorization.require_item(
            collection.id, access=analyst, permission=COLLECTION_UPDATE_PERMISSION
        )
        with pytest.raises(DocumentNotFoundError):
            await authorization.require_item(collection.id, access=outsider)

        membership.status = "inactive"
        membership.deleted_at = text("now()")
        await session.flush()
        departed = await _context(session, analyst_id, tenant.id)
        assert departed.group_ids == ()
        with pytest.raises(DocumentNotFoundError):
            await authorization.require_item(collection.id, access=departed)


@pytest.mark.asyncio
async def test_revoking_a_grant_removes_access_at_once(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        reader_id = await _member(session, tenant.id, "reader@example.com")
        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id, title="Handbook", created_by_user_id=reader_id
        )
        await _grant(
            session, collection.id, role_code=COLLECTION_VIEWER_ROLE, user_id=reader_id
        )

        reader = await _context(session, reader_id, tenant.id)
        authorization = AuthorizationService(session)
        assert await authorization.require_item(collection.id, access=reader)

        await RoleAssignmentService(session).revoke_collection_role(
            collection.id, principal_type="user", principal_id=reader_id
        )

        with pytest.raises(DocumentNotFoundError):
            await authorization.require_item(collection.id, access=reader)
        assert await authorization.allowed_collection_ids(reader) == ()


@pytest.mark.asyncio
async def test_revoking_a_permission_from_a_role_removes_it_from_its_holders(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A tombstoned role permission must stop granting, not linger in a join."""

    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        user = await identity.create_user("curator@example.com")
        role = await identity.create_role(
            tenant.id, "curator", "Curator",
            permission_codes=["knowledge.read", "source.manage"],
        )
        await identity.assign_membership(user.id, tenant.id)
        await RoleAssignmentService(session).replace_tenant_roles(
            user_id=user.id, tenant_id=tenant.id, role_ids=[role.id]
        )
        assert (await _context(session, user.id, tenant.id)).permission_codes == (
            "knowledge.read",
            "source.manage",
        )

        await identity.update_role(
            tenant.id, role.id, permission_codes=["knowledge.read"]
        )
        assert (await _context(session, user.id, tenant.id)).permission_codes == (
            "knowledge.read",
        )
        # The record of what the role could do survives as a tombstone rather
        # than vanishing from the database.
        revoked = await session.scalar(
            select(RolePermission).where(
                RolePermission.role_id == role.id,
                RolePermission.permission_code == "source.manage",
            )
        )
        assert revoked is not None and revoked.deleted_at is not None


@pytest.mark.asyncio
async def test_a_tenant_role_grants_across_that_tenant_and_no_other(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        items = ItemService(session)
        acme = await identity.create_tenant("acme", "Acme")
        labs = await identity.create_tenant("labs", "Labs")
        admin_id = await _member(
            session, acme.id, "admin@example.com", tenant_role=TENANT_ADMIN_ROLE
        )
        labs_member_id = await _member(session, labs.id, "labs@example.com")

        acme_collection = await items.create_collection(
            tenant_id=acme.id, title="Acme handbook", created_by_user_id=admin_id
        )
        labs_collection = await items.create_collection(
            tenant_id=labs.id, title="Labs handbook", created_by_user_id=labs_member_id
        )

        admin = await _context(session, admin_id, acme.id)
        authorization = AuthorizationService(session)

        # Tenant-wide capability reaches every Collection in that tenant with
        # no per-Collection grant, and that is the only reason it works.
        assert await authorization.require_item(
            acme_collection.id, access=admin, permission=COLLECTION_SHARE_PERMISSION
        )
        assert await authorization.allowed_collection_ids(admin) == (acme_collection.id,)

        # And stops dead at the tenant boundary.
        with pytest.raises(DocumentNotFoundError):
            await authorization.require_item(labs_collection.id, access=admin)
        with pytest.raises(AuthorizationError, match="not a member"):
            await identity.get_context(admin_id, tenant_id=labs.id)


@pytest.mark.asyncio
async def test_platform_capability_never_reaches_workspace_content(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        member_id = await _member(session, tenant.id, "member@example.com")
        operator_id = await _member(session, tenant.id, "operator@example.com")
        await RoleAssignmentService(session).ensure_platform_role(
            operator_id, PLATFORM_ADMIN_ROLE
        )
        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id, title="Handbook", created_by_user_id=member_id
        )
        await _grant(
            session, collection.id, role_code=COLLECTION_OWNER_ROLE, user_id=member_id
        )

        operator = await _context(session, operator_id, tenant.id)
        assert "platform.tenant.read" in operator.platform_permissions
        # Running the platform is not a way into a workspace's knowledge.
        with pytest.raises(DocumentNotFoundError):
            await AuthorizationService(session).require_item(
                collection.id, access=operator
            )


@pytest.mark.asyncio
async def test_the_database_refuses_a_cross_tenant_role_assignment(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Tenant isolation is enforced by PostgreSQL, not only by service code."""

    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        acme = await identity.create_tenant("acme", "Acme")
        labs = await identity.create_tenant("labs", "Labs")
        acme_member_id = await _member(session, acme.id, "acme@example.com")
        labs_member_id = await _member(session, labs.id, "labs@example.com")
        acme_collection = await ItemService(session).create_collection(
            tenant_id=acme.id, title="Acme handbook", created_by_user_id=acme_member_id
        )
        labs_role = await identity.create_role(labs.id, "labs-only", "Labs Only")
        collection_owner_id = await _system_role_id(session, COLLECTION_OWNER_ROLE)

    async with session_factory() as session:
        # A member of another tenant cannot be given a role on this Collection.
        session.add(
            RoleAssignment(
                user_id=labs_member_id,
                role_id=collection_owner_id,
                item_id=acme_collection.id,
            )
        )
        with pytest.raises(DBAPIError, match="must be a member of the scope tenant"):
            await session.flush()
        await session.rollback()

        # Nor can one tenant's own role be used inside another tenant.
        session.add(
            RoleAssignment(
                user_id=acme_member_id, role_id=labs_role.id, tenant_id=acme.id
            )
        )
        with pytest.raises(DBAPIError, match="cannot be assigned outside its tenant"):
            await session.flush()
        await session.rollback()

        # And a Collection role cannot be used as if it were a tenant role.
        session.add(
            RoleAssignment(
                user_id=acme_member_id,
                role_id=collection_owner_id,
                tenant_id=acme.id,
            )
        )
        with pytest.raises(DBAPIError, match="does not match"):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_the_database_refuses_a_group_member_from_another_tenant(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        acme = await identity.create_tenant("acme", "Acme")
        labs = await identity.create_tenant("labs", "Labs")
        await _member(session, acme.id, "acme@example.com")
        labs_member_id = await _member(session, labs.id, "labs@example.com")
        group = Group(tenant_id=acme.id, code="analysts", display_name="Analysts")
        session.add(group)
        await session.flush()
        group_id = group.id

    async with session_factory() as session:
        session.add(GroupMembership(group_id=group_id, user_id=labs_member_id))
        with pytest.raises(DBAPIError, match="must belong to the group tenant"):
            await session.flush()
        await session.rollback()


@pytest.mark.asyncio
async def test_a_document_cannot_become_its_own_authorization_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Only a Collection carries grants, so only a Collection may stop inheriting."""

    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        tenant = await identity.create_tenant("acme", "Acme")
        owner_id = await _member(session, tenant.id, "owner@example.com")
        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id, title="Handbook", created_by_user_id=owner_id
        )
        collection_id = collection.id

    async with session_factory() as session:
        session.add(
            Item(
                tenant_id=tenant.id,
                item_type="document",
                parent_item_id=collection_id,
                parent_relation="contains",
                document_type="pdf",
                title="Orphaned policy",
                inherit_access=False,
            )
        )
        with pytest.raises(DBAPIError, match="only_collections_end_inheritance"):
            await session.flush()
        await session.rollback()
