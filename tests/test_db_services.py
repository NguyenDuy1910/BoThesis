from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bothesis.db.models import (
    Base,
    Connector,
    ConnectorScope,
    Conversation,
    Message,
    SyncRun,
)
from bothesis.services import (
    AuthService,
    AuthorizationError,
    DocumentChunkInput,
    DocumentNotFoundError,
    DocumentService,
)

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL service integration tests",
)


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert TEST_DATABASE_URL is not None
    schema = f"test_services_{uuid4().hex}"
    admin_engine = create_async_engine(TEST_DATABASE_URL)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    try:
        yield async_sessionmaker(engine, expire_on_commit=False)
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


@pytest.mark.asyncio
async def test_auth_service_resolves_tenant_permissions_and_principals(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        service = AuthService(session)
        tenant = await service.create_tenant("Acme", "Acme Corporation")
        user = await service.create_user("USER@EXAMPLE.COM", display_name="User")
        role = await service.create_role(
            tenant.id,
            "analyst",
            "Analyst",
            permission_codes=["knowledge.read", "source.manage"],
        )
        await service.assign_membership(user.id, tenant.id, role.id)
        await service.replace_principal_tokens(
            user.id,
            ["DOMAIN:EXAMPLE.COM", "GROUP:FINANCE", "group:finance"],
        )

        context = await service.require_permissions(user.id, "knowledge.read")

        assert user.email == "user@example.com"
        assert context.tenant_id == tenant.id
        assert context.role_code == "analyst"
        assert context.permission_codes == ("knowledge.read", "source.manage")
        assert context.principal_tokens == (
            "domain:example.com",
            "group:finance",
        )
        with pytest.raises(AuthorizationError, match="missing required permissions"):
            await service.require_permissions(user.id, "user.manage")

        await service.remove_membership(user.id)
        standalone_context = await service.get_context(user.id)
        assert standalone_context.tenant_id is None
        assert standalone_context.principal_tokens == ()


@pytest.mark.asyncio
async def test_document_service_enforces_acl_and_generation_activation(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        documents = DocumentService(session)
        tenant = await auth.create_tenant("acme", "Acme")
        user = await auth.create_user("reader@example.com")
        outsider = await auth.create_user("outsider@example.com")
        role = await auth.create_role(
            tenant.id,
            "manager",
            "Manager",
            permission_codes=["knowledge.read", "source.manage"],
        )
        reader_role = await auth.create_role(
            tenant.id,
            "reader",
            "Reader",
            permission_codes=["knowledge.read"],
        )
        await auth.assign_membership(user.id, tenant.id, role.id)
        await auth.assign_membership(outsider.id, tenant.id, reader_role.id)
        await auth.replace_principal_tokens(user.id, ["group:finance"])
        actor = await auth.get_context(user.id)
        outsider_access = await auth.get_context(outsider.id)

        personal = await documents.create_personal_document(
            user.id,
            origin="upload",
            title="Private plan",
            mime_type="text/plain",
        )
        await documents.replace_chunks(
            personal.id,
            [DocumentChunkInput(content="private content", token_count=2)],
        )
        await documents.store_blob(personal.id, b"private content")
        assert await documents.get_document_text(personal.id, access=actor) == (
            "private content"
        )
        assert await documents.get_blob(personal.id, access=actor) == b"private content"
        with pytest.raises(DocumentNotFoundError):
            await documents.get_document(personal.id, access=outsider_access)

        conversation = Conversation(user_id=user.id, title="Document chat")
        session.add(conversation)
        await session.flush()
        message = Message(
            conversation_id=conversation.id,
            role="user",
            content="Review this plan",
            sequence_number=1,
        )
        session.add(message)
        await session.flush()
        link = await documents.link_message(
            message.id,
            personal.id,
            "attachment",
            access=actor,
        )
        assert link.document_id == personal.id
        with pytest.raises(DocumentNotFoundError):
            await documents.link_message(
                message.id,
                personal.id,
                "reference",
                access=outsider_access,
            )

        enterprise = await documents.create_enterprise_document(
            tenant.id,
            origin="generated",
            created_by_user_id=user.id,
            title="Finance brief",
            allowed_principal_tokens=["group:finance"],
        )
        assert await documents.get_document(enterprise.id, access=actor) is enterprise
        with pytest.raises(DocumentNotFoundError):
            await documents.get_document(enterprise.id, access=outsider_access)

        connector = Connector(
            tenant_id=tenant.id,
            provider="confluence",
            display_name="Finance Confluence",
        )
        session.add(connector)
        await session.flush()
        scope = ConnectorScope(
            connector_id=connector.id,
            scope_value="FIN",
            display_name="Finance",
        )
        session.add(scope)
        await session.flush()
        sync_run = SyncRun(
            connector_scope_id=scope.id,
            generation=1,
            trigger_type="manual",
            status="running",
        )
        session.add(sync_run)
        await session.flush()

        external = await documents.upsert_external_document(
            scope.id,
            1,
            "page-42",
            title="Quarterly plan",
            allowed_principal_tokens=["group:finance"],
        )
        await documents.replace_chunks(
            external.id,
            [DocumentChunkInput(content="grounded enterprise content")],
        )
        await documents.mark_indexed(external.id)
        with pytest.raises(DocumentNotFoundError):
            await documents.get_document(external.id, access=actor)

        sync_run.status = "completed"
        await session.flush()
        await documents.activate_generation(scope.id, 1, actor=actor)
        assert await documents.get_document(external.id, access=actor) is external

        await documents.soft_delete_document(external.id, actor=actor)
        with pytest.raises(DocumentNotFoundError):
            await documents.get_document(external.id, access=actor)
