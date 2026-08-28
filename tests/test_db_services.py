from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from bothesis.db.models import (
    AuditLog,
    Base,
    Conversation,
    Item,
    ItemOrigin,
    ItemUpload,
    Message,
    MessageItem,
    PluginConnection,
    PluginCredential,
)
from bothesis.services import (
    AccessRequestService,
    AdminItemService,
    AuthContext,
    AuthService,
    AuthorizationError,
    CollectionAccessService,
    DocumentNotFoundError,
    ItemService,
    PluginCredentialService,
    PluginService,
    UploadService,
    UploadTooLargeError,
    UploadValidationError,
)
from bothesis.document_index.raw_storage import ObjectStorageError, StoredObject


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

        first_context = await auth.get_context(user.id, tenant_id=first_tenant.id)
        second_context = await auth.get_context(user.id, tenant_id=second_tenant.id)

        assert user.email == "user@example.com"
        assert first_context.permission_codes == ("knowledge.read",)
        assert second_context.permission_codes == ("knowledge.read", "source.manage")


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
            document_type="pdf",
        )
        repeated, repeated_created = await items.create_or_get_personal_upload(
            owner.id,
            tenant.id,
            idempotency_key="upload-1",
            file_name="report.pdf",
            mime_type="application/pdf",
            size_bytes=100,
            document_type="pdf",
        )
        assert created is True
        assert repeated_created is False
        assert repeated.id == item.id
        assert item.storage_key == f"tenants/{tenant.id}/items/{item.id}/raw"
        assert item.upload is not None and item.upload.status == "pending"

        conversation = Conversation(
            tenant_id=tenant.id, user_id=owner.id, title="Review"
        )
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
async def test_plugin_credentials_are_encrypted_and_owner_models_are_explicit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("acme", "Acme")
        owner = await auth.create_user("owner@example.com")
        role = await auth.create_role(tenant.id, "member", "Member")
        await auth.assign_membership(owner.id, tenant.id, role.id)

        personal = PluginConnection(
            tenant_id=tenant.id,
            owner_type="user",
            owner_user_id=owner.id,
            plugin_key="confluence",
            display_name="Owner Confluence",
            created_by_user_id=owner.id,
        )
        tenant_owned = PluginConnection(
            tenant_id=tenant.id,
            owner_type="tenant",
            plugin_key="google_drive",
            display_name="Company Drive",
            created_by_user_id=owner.id,
        )
        session.add_all([personal, tenant_owned])
        await session.flush()

        encryption_key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
        credentials = PluginCredentialService(session, encryption_key)
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
            select(PluginCredential).where(
                PluginCredential.connection_id == personal.id
            )
        ) is record


def test_plugin_encryption_key_accepts_unpadded_urlsafe_base64() -> None:
    expected = bytes(range(32))
    encryption_key = base64.urlsafe_b64encode(expected).decode("ascii").rstrip("=")

    assert PluginCredentialService._decode_key(encryption_key) == expected


@pytest.mark.asyncio
async def test_plugin_list_eager_loads_optional_credentials(
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
            PluginConnection(
                tenant_id=tenant.id,
                owner_type="tenant",
                plugin_key="file",
                display_name="Uploaded files",
                status="draft",
                created_by_user_id=owner.id,
            )
        )

    async with session_factory.begin() as session:
        result = await PluginService(session).list_connections(
            actor, page_size=100,
        )

    assert result["total"] == 1
    assert result["items"][0]["credential_configured"] is False


@pytest.mark.asyncio
async def test_admin_collection_creation_is_tenant_scoped_and_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("acme-knowledge", "Acme Knowledge")
        owner = await auth.create_user("knowledge-owner@example.com")
        role = await auth.create_role(
            tenant.id,
            "knowledge-admin",
            "Knowledge Admin",
            permission_codes=["access.manage", "item.manage"],
        )
        await auth.assign_membership(owner.id, tenant.id, role.id)
        actor = await auth.get_context(owner.id, tenant_id=tenant.id)

        created = await AdminItemService(session).create_collection(
            actor,
            title="Engineering handbook",
            inherit_access=True,
            metadata={"description": "Governed engineering knowledge"},
        )

        assert created["item_type"] == "collection"
        assert created["title"] == "Engineering handbook"
        assert created["inherit_access"] is True
        assert created["metadata"] == {
            "description": "Governed engineering knowledge"
        }
        assert created["created_by_user_id"] == str(owner.id)
        assert created["collection_access"] == [
            {
                "principal_type": "user",
                "principal_id": str(owner.id),
                "role": "owner",
            }
        ]
        listed = await AdminItemService(session).list_items(
            actor,
            item_type="collection",
            search="governed engineering",
            created_by_user_id=owner.id,
        )
        assert listed["total"] == 1
        assert listed["items"][0]["item_count"] == 0
        assert listed["items"][0]["source_count"] == 0
        assert listed["items"][0]["created_by_user_id"] == str(owner.id)
        audit_event = await session.scalar(
            select(AuditLog).where(
                AuditLog.resource_id == created["id"],
                AuditLog.action == "collection.created",
            )
        )
        assert audit_event is not None
        assert audit_event.tenant_id == tenant.id

        updated = await AdminItemService(session).update_collection(
            actor,
            UUID(created["id"]),
            title="Engineering playbook",
            description=None,
            description_provided=True,
        )

        assert updated["title"] == "Engineering playbook"
        assert updated["metadata"] == {}
        update_event = await session.scalar(
            select(AuditLog).where(
                AuditLog.resource_id == created["id"],
                AuditLog.action == "collection.updated",
            )
        )
        assert update_event is not None


def test_postgresql_models_have_no_raw_byte_or_chunk_columns() -> None:
    forbidden_tables = {"documents", "document_blobs", "document_chunks"}
    assert forbidden_tables.isdisjoint(Base.metadata.tables)
    assert all(
        column.type.__class__.__name__.casefold() not in {"largebinary", "bytea"}
        for table in Base.metadata.tables.values()
        for column in table.columns
    )


class _AsyncUpload:
    def __init__(self, body: bytes) -> None:
        self._body = body
        self._offset = 0
        self.read_count = 0

    async def read(self, size: int = -1) -> bytes:
        self.read_count += 1
        if self._offset >= len(self._body):
            return b""
        end = len(self._body) if size < 0 else self._offset + size
        chunk = self._body[self._offset:end]
        self._offset += len(chunk)
        return chunk


class _UploadStorage:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.uploads: list[tuple[str, bytes, str | None]] = []

    def put_path(
        self,
        path: Path,
        key: str,
        *,
        content_type: str | None = None,
    ) -> StoredObject:
        if self.fail:
            raise ObjectStorageError("storage unavailable")
        body = path.read_bytes()
        self.uploads.append((key, body, content_type))
        return StoredObject(
            size_bytes=len(body),
            content_type=content_type,
            etag="etag-upload",
            version_id="version-upload",
        )


async def _collection_upload_contexts(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, AuthContext, AuthContext, AuthContext]:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("upload-tenant", "Upload tenant")
        other_tenant = await auth.create_tenant("upload-other", "Other tenant")
        owner = await auth.create_user("upload-owner@example.com")
        editor = await auth.create_user("upload-editor@example.com")
        viewer = await auth.create_user("upload-viewer@example.com")
        outsider = await auth.create_user("upload-outsider@example.com")
        admin_role = await auth.create_role(
            tenant.id,
            "upload-admin",
            "Upload admin",
            permission_codes=["admin"],
        )
        member_role = await auth.create_role(
            tenant.id,
            "upload-member",
            "Upload member",
        )
        outsider_role = await auth.create_role(
            other_tenant.id,
            "upload-outsider",
            "Upload outsider",
        )
        await auth.assign_membership(owner.id, tenant.id, admin_role.id)
        await auth.assign_membership(editor.id, tenant.id, member_role.id)
        await auth.assign_membership(viewer.id, tenant.id, member_role.id)
        await auth.assign_membership(outsider.id, other_tenant.id, outsider_role.id)
        owner_context = await auth.get_context(owner.id, tenant_id=tenant.id)
        editor_context = await auth.get_context(editor.id, tenant_id=tenant.id)
        viewer_context = await auth.get_context(viewer.id, tenant_id=tenant.id)
        outsider_context = await auth.get_context(
            outsider.id, tenant_id=other_tenant.id
        )
        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id,
            title="Upload destination",
            created_by_user_id=owner.id,
        )
        access = CollectionAccessService(session)
        await access.grant(
            collection.id,
            principal_type="user",
            principal_id=owner.id,
            role="owner",
            actor=owner_context,
        )
        await access.grant(
            collection.id,
            principal_type="user",
            principal_id=editor.id,
            role="editor",
            actor=owner_context,
        )
        await access.grant(
            collection.id,
            principal_type="user",
            principal_id=viewer.id,
            role="viewer",
            actor=owner_context,
        )
        return (
            collection.id,
            editor_context,
            viewer_context,
            outsider_context,
        )


@pytest.mark.asyncio
async def test_collection_upload_is_authorized_parented_and_retry_safe(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection_id, editor, viewer, _ = await _collection_upload_contexts(session_factory)
    storage = _UploadStorage()
    uploads = UploadService(session_factory, object_storage=storage)

    first = await uploads.upload_to_collection(
        editor,
        collection_id,
        idempotency_key="collection-upload-1",
        file_name="policy.txt",
        content_type="text/plain",
        content=_AsyncUpload(b"governed policy"),
    )
    repeated = await uploads.upload_to_collection(
        editor,
        collection_id,
        idempotency_key="collection-upload-1",
        file_name="policy.txt",
        content_type="text/plain",
        content=_AsyncUpload(b"governed policy"),
    )
    second = await uploads.upload_to_collection(
        editor,
        collection_id,
        idempotency_key="collection-upload-2",
        file_name="controls.md",
        content_type="text/markdown",
        content=_AsyncUpload(b"# Controls"),
    )

    assert first.created is True
    assert repeated.created is False
    assert repeated.item.id == first.item.id
    assert second.item.id != first.item.id
    assert first.item.parent_item_id == collection_id
    assert first.item.upload is not None
    assert first.item.upload.owner_user_id == editor.user_id
    assert first.item.upload.status == "available"
    assert len(storage.uploads) == 2
    assert storage.uploads[0][1] == b"governed policy"
    async with session_factory() as session:
        origin = await session.scalar(
            select(ItemOrigin.id).where(ItemOrigin.item_id == first.item.id)
        )
        visible = await ItemService(session).get_upload_for_access(
            first.item.id,
            viewer,
        )
        with pytest.raises(AuthorizationError, match="editor collection access"):
            await ItemService(session).get_upload_for_access(
                first.item.id,
                viewer,
                minimum_role="editor",
            )
    assert origin is None
    assert visible.id == first.item.id


@pytest.mark.asyncio
async def test_collection_upload_rejects_tenant_permission_and_collection_states(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection_id, _, viewer, outsider = await _collection_upload_contexts(
        session_factory
    )
    uploads = UploadService(session_factory, object_storage=_UploadStorage())
    viewer_content = _AsyncUpload(b"viewer")
    outsider_content = _AsyncUpload(b"outsider")

    with pytest.raises(AuthorizationError, match="editor collection access"):
        await uploads.upload_to_collection(
            viewer,
            collection_id,
            idempotency_key="viewer-upload",
            file_name="viewer.txt",
            content_type="text/plain",
            content=viewer_content,
        )
    with pytest.raises(DocumentNotFoundError):
        await uploads.upload_to_collection(
            outsider,
            collection_id,
            idempotency_key="outsider-upload",
            file_name="outsider.txt",
            content_type="text/plain",
            content=outsider_content,
        )
    with pytest.raises(DocumentNotFoundError):
        await uploads.upload_to_collection(
            viewer,
            uuid4(),
            idempotency_key="missing-upload",
            file_name="missing.txt",
            content_type="text/plain",
            content=_AsyncUpload(b"missing"),
        )
    assert viewer_content.read_count == 0
    assert outsider_content.read_count == 0

    async with session_factory.begin() as session:
        request = await AccessRequestService(session).create_request(
            viewer,
            requester_user_id=viewer.user_id,
            collection_item_id=collection_id,
            requested_role="editor",
            reason="Upload files to this knowledge base",
        )
    assert request["status"] == "pending"
    assert request["requested_role"] == "editor"

    async with session_factory.begin() as session:
        collection = await session.get(Item, collection_id)
        assert collection is not None
        collection.status = "deleted"
        collection.deleted_at = datetime.now(UTC)
    with pytest.raises(DocumentNotFoundError):
        await uploads.upload_to_collection(
            viewer,
            collection_id,
            idempotency_key="archived-upload",
            file_name="archived.txt",
            content_type="text/plain",
            content=_AsyncUpload(b"archived"),
        )


@pytest.mark.asyncio
async def test_collection_upload_validates_type_size_and_storage_failures(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection_id, editor, _, _ = await _collection_upload_contexts(session_factory)
    uploads = UploadService(
        session_factory,
        object_storage=_UploadStorage(),
        max_upload_bytes=8,
    )

    with pytest.raises(UploadValidationError, match="unsupported file type"):
        await uploads.upload_to_collection(
            editor,
            collection_id,
            idempotency_key="unsupported-upload",
            file_name="archive.exe",
            content_type="application/octet-stream",
            content=_AsyncUpload(b"binary"),
        )
    with pytest.raises(UploadTooLargeError):
        await uploads.upload_to_collection(
            editor,
            collection_id,
            idempotency_key="oversized-upload",
            file_name="large.txt",
            content_type="text/plain",
            content=_AsyncUpload(b"123456789"),
        )

    failing_uploads = UploadService(
        session_factory,
        object_storage=_UploadStorage(fail=True),
    )
    with pytest.raises(ObjectStorageError):
        await failing_uploads.upload_to_collection(
            editor,
            collection_id,
            idempotency_key="storage-failure",
            file_name="storage.txt",
            content_type="text/plain",
            content=_AsyncUpload(b"stored later"),
        )
    async with session_factory() as session:
        failed = await session.scalar(
            select(ItemUpload).where(
                ItemUpload.idempotency_key == "storage-failure"
            )
        )
        assert failed is not None
        item = await session.get(Item, failed.item_id)
    assert failed.status == "failed"
    assert item is not None and item.status == "failed"
