from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bothesis.db.models import (
    Base,
    Connector,
    ConnectorCredential,
    ConnectorScope,
    Conversation,
    Item,
    ItemUpload,
    Message,
    MessageItem,
    SyncRun,
)
from bothesis.services import (
    AuthService,
    AuthorizationError,
    ConnectorCredentialService,
    DatasourceService,
    DocumentNotFoundError,
    ItemService,
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
async def test_identity_supports_multiple_tenant_memberships(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        first_tenant = await auth.create_tenant("acme", "Acme")
        second_tenant = await auth.create_tenant("labs", "Labs")
        user = await auth.create_user("USER@EXAMPLE.COM")
        first_role = await auth.create_role(
            first_tenant.id,
            "reader",
            "Reader",
            permission_codes=["knowledge.read"],
        )
        second_role = await auth.create_role(
            second_tenant.id,
            "manager",
            "Manager",
            permission_codes=["knowledge.read", "source.manage"],
        )
        await auth.assign_membership(user.id, first_tenant.id, first_role.id)
        await auth.assign_membership(user.id, second_tenant.id, second_role.id)

        with pytest.raises(AuthorizationError, match="tenant ID is required"):
            await auth.get_context(user.id)

        await auth.replace_principal_tokens(
            user.id,
            ["GROUP:FINANCE", "group:finance"],
            tenant_id=first_tenant.id,
        )
        first_context = await auth.get_context(user.id, tenant_id=first_tenant.id)
        second_context = await auth.get_context(user.id, tenant_id=second_tenant.id)

        assert user.email == "user@example.com"
        assert first_context.principal_tokens == ("group:finance",)
        assert first_context.permission_codes == ("knowledge.read",)
        assert second_context.principal_tokens == ()
        assert second_context.permission_codes == ("knowledge.read", "source.manage")


@pytest.mark.asyncio
async def test_items_are_canonical_tenant_scoped_sources(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("acme", "Acme")
        owner = await auth.create_user("owner@example.com")
        outsider = await auth.create_user("outsider@example.com")
        role = await auth.create_role(
            tenant.id,
            "reader",
            "Reader",
            permission_codes=["knowledge.read"],
        )
        await auth.assign_membership(owner.id, tenant.id, role.id)
        await auth.assign_membership(outsider.id, tenant.id, role.id)
        await auth.replace_principal_tokens(
            owner.id, ["group:finance"], tenant_id=tenant.id
        )
        owner_context = await auth.get_context(owner.id, tenant_id=tenant.id)
        outsider_context = await auth.get_context(outsider.id, tenant_id=tenant.id)

        connector = Connector(
            tenant_id=tenant.id,
            owner_type="tenant",
            provider="google_drive",
            display_name="Company Drive",
            created_by_user_id=owner.id,
        )
        session.add(connector)
        await session.flush()
        scope = ConnectorScope(
            connector_id=connector.id,
            scope_type="folder",
            scope_value="root",
            display_name="Root",
            sync_checkpoint={"page_token": "next"},
        )
        session.add(scope)
        await session.flush()

        items = ItemService(session)
        collection = await items.upsert_external_item(
            scope.id,
            "folder-1",
            item_type="collection",
            collection_kind="folder",
            title="Finance",
            allowed_principal_tokens=["group:finance"],
        )
        document = await items.upsert_external_item(
            scope.id,
            "report-1",
            item_type="document",
            document_kind="pdf",
            parent_source_id="folder-1",
            title="Quarterly report",
            mime_type="application/pdf",
            size_bytes=12,
            storage_key="tenants/acme/items/report-1/raw",
            content_sha256="a" * 64,
            allowed_principal_tokens=["group:finance"],
        )
        opaque_file = await items.upsert_external_item(
            scope.id,
            "archive-1",
            item_type="file",
            parent_source_id="report-1",
            title="Archive",
            mime_type="application/zip",
            storage_key="tenants/acme/items/archive-1/raw",
            allowed_principal_tokens=["group:finance"],
            status="unsupported",
        )

        assert collection.item_type == "collection"
        assert collection.collection_kind == "folder"
        assert document.parent_item_id == collection.id
        assert opaque_file.parent_item_id == document.id
        assert document.id == ItemService.connector_item_id(connector.id, "report-1")
        assert await items.get_item(document.id, access=owner_context) is document
        with pytest.raises(DocumentNotFoundError):
            await items.get_item(document.id, access=outsider_context)

        sync_run = SyncRun(
            connector_scope_id=scope.id,
            trigger_type="manual",
            status="completed",
            discovered_item_count=3,
            processed_item_count=3,
            written_chunk_count=5,
        )
        session.add(sync_run)
        await session.flush()
        assert scope.sync_checkpoint == {"page_token": "next"}
        assert sync_run.written_chunk_count == 5


@pytest.mark.asyncio
async def test_personal_upload_and_message_relation_store_metadata_only(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("acme", "Acme")
        owner = await auth.create_user("owner@example.com")
        role = await auth.create_role(tenant.id, "member", "Member")
        await auth.assign_membership(owner.id, tenant.id, role.id)
        context = await auth.get_context(owner.id, tenant_id=tenant.id)

        items = ItemService(session)
        item, created = await items.create_or_get_personal_upload(
            owner.id,
            tenant.id,
            idempotency_key="upload-1",
            file_name="report.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            document_kind="pdf",
        )
        repeated, repeated_created = await items.create_or_get_personal_upload(
            owner.id,
            tenant.id,
            idempotency_key="upload-1",
            file_name="report.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            document_kind="pdf",
        )
        assert created is True
        assert repeated_created is False
        assert repeated.id == item.id
        assert item.storage_key == f"tenants/{tenant.id}/items/{item.id}/raw"
        assert item.upload is not None and item.upload.status == "pending"

        conversation = Conversation(user_id=owner.id, title="Review")
        session.add(conversation)
        await session.flush()
        message = Message(
            conversation_id=conversation.id,
            role="user",
            content="Review the attachment",
            sequence_number=1,
        )
        session.add(message)
        await session.flush()
        link = await items.link_message(
            message.id,
            item.id,
            "attachment",
            access=context,
        )
        assert link.item_id == item.id
        assert link.relation_type == "attachment"

        await items.soft_delete_item(item.id, actor=context)
        assert item.status == "deleted"
        assert item.deleted_at is not None
        assert await session.scalar(
            select(ItemUpload).where(ItemUpload.item_id == item.id)
        )
        assert await session.scalar(
            select(MessageItem).where(MessageItem.item_id == item.id)
        )


@pytest.mark.asyncio
async def test_connector_credentials_are_encrypted_and_owner_models_are_explicit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("acme", "Acme")
        owner = await auth.create_user("owner@example.com")
        role = await auth.create_role(tenant.id, "member", "Member")
        await auth.assign_membership(owner.id, tenant.id, role.id)

        personal = Connector(
            tenant_id=tenant.id,
            owner_type="user",
            owner_user_id=owner.id,
            provider="confluence",
            display_name="Owner Confluence",
            created_by_user_id=owner.id,
        )
        tenant_owned = Connector(
            tenant_id=tenant.id,
            owner_type="tenant",
            provider="google_drive",
            display_name="Company Drive",
            created_by_user_id=owner.id,
        )
        session.add_all([personal, tenant_owned])
        await session.flush()

        encryption_key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
        credentials = ConnectorCredentialService(session, encryption_key)
        record = await credentials.store(
            personal.id,
            credential_type="oauth2",
            payload={"access_token": "top-secret", "refresh_token": "refresh-secret"},
            key_version="local-v1",
        )

        assert personal.owner_user_id == owner.id
        assert tenant_owned.owner_user_id is None
        assert "top-secret" not in record.encrypted_payload
        assert "refresh-secret" not in record.encrypted_payload
        assert await credentials.resolve(personal.id) == {
            "access_token": "top-secret",
            "refresh_token": "refresh-secret",
        }
        assert await session.scalar(
            select(ConnectorCredential).where(
                ConnectorCredential.connector_id == personal.id
            )
        ) is record


@pytest.mark.asyncio
async def test_datasource_list_eager_loads_optional_credentials(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("acme", "Acme")
        owner = await auth.create_user("owner@example.com")
        role = await auth.create_role(
            tenant.id,
            "source-manager",
            "Source Manager",
            permission_codes=["source.manage"],
        )
        await auth.assign_membership(owner.id, tenant.id, role.id)
        actor = await auth.get_context(owner.id, tenant_id=tenant.id)
        session.add(
            Connector(
                tenant_id=tenant.id,
                owner_type="tenant",
                provider="file",
                display_name="Uploaded files",
                status="draft",
                created_by_user_id=owner.id,
            )
        )

    async with session_factory.begin() as session:
        result = await DatasourceService(session).list_datasources(
            actor,
            page_size=100,
        )

    assert result["total"] == 1
    assert result["items"][0]["credential_configured"] is False


def test_postgresql_models_have_no_raw_byte_or_chunk_columns() -> None:
    forbidden_tables = {"documents", "document_blobs", "document_chunks"}
    assert forbidden_tables.isdisjoint(Base.metadata.tables)
    assert all(
        column.type.__class__.__name__.casefold() not in {"largebinary", "bytea"}
        for table in Base.metadata.tables.values()
        for column in table.columns
    )
