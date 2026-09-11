from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from bothesis.connector.protocol import BoundingBox, Chunk, CitationInfo, CitationSpan
from bothesis.db.models import (
    ArtifactRevision,
    AuditLog,
    Base,
    Citation,
    Conversation,
    ExternalResource,
    IngestionSource,
    IntegrationConnection,
    IntegrationCredential,
    Item,
    ItemUpload,
    Message,
    MessageItem,
    SandboxSession,
)
from bothesis.agent.models import AgentContext
from bothesis.agent.protocol import ExtensionItem, Response
from bothesis.storage import (
    ObjectNotFoundError,
    ObjectStorageError,
    PresignedRequest,
    StoredObject,
)
from bothesis.services import (
    ArtifactValidationError,
    AuthContext,
    AuthorizationError,
    DocumentNotFoundError,
    DocumentProcessingError,
    UploadTooLargeError,
    UploadValidationError,
    SandboxManifestResource,
    SandboxProviderFile,
)
from bothesis.services.identity_access.access_requests import AccessRequestService
from bothesis.services.artifact import ArtifactService
from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services.citation import CitationService
from bothesis.services.identity_access.collection_access import CollectionAccessService
from bothesis.services.conversation import ConversationService
from bothesis.services.integration_connections import IntegrationConnectionService
from bothesis.services.integration_credential import IntegrationCredentialService
from bothesis.services.item import ItemService
from bothesis.services.item_catalog import ItemCatalogService
from bothesis.services.sandbox_session import SandboxSessionService
from bothesis.services.document_upload import DocumentUploadService
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

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
        auth = IdentityStoreService(session)
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
        auth = IdentityStoreService(session)
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
async def test_sandbox_recovery_state_is_private_to_its_conversation_owner(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        identity = IdentityStoreService(session)
        first_tenant = await identity.create_tenant("sandbox-one", "Sandbox one")
        second_tenant = await identity.create_tenant("sandbox-two", "Sandbox two")
        owner = await identity.create_user("owner@sandbox.test")
        other = await identity.create_user("other@sandbox.test")
        owner_role = await identity.create_role(first_tenant.id, "member", "Member")
        other_role = await identity.create_role(second_tenant.id, "member", "Member")
        await identity.assign_membership(owner.id, first_tenant.id, owner_role.id)
        await identity.assign_membership(other.id, second_tenant.id, other_role.id)
        owner_access = await identity.get_context(owner.id, tenant_id=first_tenant.id)
        other_access = await identity.get_context(other.id, tenant_id=second_tenant.id)
        conversation = Conversation(
            tenant_id=first_tenant.id, user_id=owner.id, title="Sandbox work"
        )
        session.add(conversation)
        await session.flush()
        conversation_id = conversation.id

    sandboxes = SandboxSessionService(session_factory)
    created = await sandboxes.ensure(
        owner_access, conversation_id=conversation_id, provider="openrouter"
    )
    recorded = await sandboxes.record_materialization(
        owner_access,
        session_id=created.id,
        resource=SandboxManifestResource(
            resource_id=str(UUID(int=19)),
            name="revenue.csv",
            mime_type="text/csv",
            size_bytes=12,
        ),
        provider_file=SandboxProviderFile(
            id="or_file_1", name="revenue.csv", resource_id=str(UUID(int=19))
        ),
    )

    assert recorded.manifest[0].resource_id == str(UUID(int=19))
    async with session_factory() as session:
        row = await session.get(SandboxSession, created.id)
        assert row is not None
        assert row.provider_state["materialized_files"] == [
            {"id": "or_file_1", "name": "revenue.csv", "resource_id": str(UUID(int=19))}
        ]
    with pytest.raises(DocumentNotFoundError):
        await sandboxes.active(
            other_access, conversation_id=conversation_id, provider="openrouter"
        )


@pytest.mark.asyncio
async def test_referenced_resources_resolve_prior_turns_under_current_access(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A follow-up like "fill that form" resolves earlier Document IDs.

    Only "attachment"/"reference" links come back — artifact "output" links
    travel as working documents — newest reference first, and only while the
    caller can still read the document's Collection.
    """

    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
        tenant = await auth.create_tenant("provenance", "Provenance")
        owner = await auth.create_user("owner@example.com")
        other = await auth.create_user("other@example.com")
        role = await auth.create_role(
            tenant.id,
            "member",
            "Member",
            permission_codes=["knowledge.read", "access.manage"],
        )
        await auth.assign_membership(owner.id, tenant.id, role.id)
        await auth.assign_membership(other.id, tenant.id, role.id)
        actor = await auth.get_context(owner.id, tenant_id=tenant.id)
        other_actor = await auth.get_context(other.id, tenant_id=tenant.id)

        items = ItemService(session)
        access = CollectionAccessService(session)
        forms = await items.create_collection(
            tenant_id=tenant.id, title="Forms", created_by_user_id=owner.id
        )
        restricted = await items.create_collection(
            tenant_id=tenant.id, title="Restricted", created_by_user_id=owner.id
        )
        for collection in (forms, restricted):
            await access.grant(
                collection.id,
                principal_type="user",
                principal_id=owner.id,
                role="owner",
                actor=actor,
            )
        expense_form = await items.create_document(
            tenant_id=tenant.id,
            parent_item_id=forms.id,
            title="Expense report form",
            document_type="file",
            created_by_user_id=owner.id,
        )
        leave_policy = await items.create_document(
            tenant_id=tenant.id,
            parent_item_id=forms.id,
            title="Leave policy",
            document_type="file",
            created_by_user_id=owner.id,
        )
        secret = await items.create_document(
            tenant_id=tenant.id,
            parent_item_id=restricted.id,
            title="Restricted budget",
            document_type="file",
            created_by_user_id=owner.id,
        )
        draft = await items.create_document(
            tenant_id=tenant.id,
            parent_item_id=forms.id,
            title="Filled expense report",
            document_type="file",
            created_by_user_id=owner.id,
        )

        conversation = Conversation(
            tenant_id=tenant.id, user_id=owner.id, title="Expenses"
        )
        session.add(conversation)
        await session.flush()
        messages = []
        for sequence, message_role in enumerate(
            ("user", "assistant", "assistant"), start=1
        ):
            message = Message(
                conversation_id=conversation.id,
                role=message_role,
                content=f"turn {sequence}",
                sequence_number=sequence,
            )
            session.add(message)
            messages.append(message)
        await session.flush()
        await items.link_message(
            messages[0].id, expense_form.id, "attachment", access=actor
        )
        await items.link_message(messages[1].id, secret.id, "reference", access=actor)
        await items.link_message(
            messages[1].id, leave_policy.id, "reference", access=actor
        )
        await items.link_message(
            messages[2].id, expense_form.id, "reference", access=actor
        )
        # The answer's produced document is an output, not a reference.
        await items.link_message(messages[2].id, draft.id, "output", access=actor)
        # Access revoked between turns must remove the document from context.
        await access.revoke(
            restricted.id, principal_type="user", principal_id=owner.id, actor=actor
        )
        conversation_id = conversation.id

    conversations = ConversationService(session_factory)
    references = await conversations.referenced_resources(
        conversation_id, access=actor
    )
    assert [reference.title for reference in references] == [
        "Expense report form",
        "Leave policy",
    ]
    assert references[0].id == str(expense_form.id)
    assert references[0].mime_type == "application/octet-stream"
    # A conversation is private to its user: another member resolves nothing.
    assert (
        await conversations.referenced_resources(conversation_id, access=other_actor)
        == ()
    )


@pytest.mark.asyncio
async def test_citations_replace_geometry_by_stable_chunk_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
        tenant = await auth.create_tenant("citations", "Citations")
        owner = await auth.create_user("citations@example.com")
        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id,
            title="Policies",
            created_by_user_id=owner.id,
        )
        document = await ItemService(session).create_document(
            tenant_id=tenant.id,
            parent_item_id=collection.id,
            title="Policy",
            document_type="pdf",
            created_by_user_id=owner.id,
        )
        chunks = (
            Chunk(
                id=f"{document.id}:0",
                item_id=str(document.id),
                chunk_index=0,
                chunk_text="First policy paragraph",
                content_type="text",
                section_path=["Policy", "Eligibility"],
                citation=CitationInfo(
                    anchor="eligibility",
                    spans=(
                        CitationSpan(
                            page=2,
                            element_id="p002_para_001",
                            start_offset=0,
                            end_offset=22,
                            bounding_box=BoundingBox(
                                x=0.1,
                                y=0.2,
                                width=0.3,
                                height=0.1,
                            ),
                        ),
                    ),
                ),
            ),
            Chunk(
                id=f"{document.id}:1",
                item_id=str(document.id),
                chunk_index=1,
                chunk_text="Second policy paragraph",
                content_type="text",
                citation=CitationInfo(spans=(CitationSpan(page=4),)),
            ),
        )

        citations = CitationService(session)
        await citations.replace_for_item(document.id, chunks)
        first = await citations.get(document.id, chunks[0].id)
        assert first is not None
        assert first.section_path == ("Policy", "Eligibility")
        assert first.section == "Eligibility"
        assert first.page_start == 2
        assert first.page_end == 2
        assert first.spans[0].bounding_box == BoundingBox(
            x=0.1,
            y=0.2,
            width=0.3,
            height=0.1,
        )

        await citations.replace_for_item(document.id, chunks[:1])
        assert await citations.get(document.id, chunks[1].id) is None
        stale = await session.scalar(
            select(Citation).where(
                Citation.item_id == document.id,
                Citation.chunk_id == chunks[1].id,
            )
        )
        assert stale is not None and stale.deleted_at is not None


@pytest.mark.asyncio
async def test_integration_credentials_are_encrypted_and_owner_models_are_explicit(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
        tenant = await auth.create_tenant("acme", "Acme")
        owner = await auth.create_user("owner@example.com")
        role = await auth.create_role(tenant.id, "member", "Member")
        await auth.assign_membership(owner.id, tenant.id, role.id)

        personal = IntegrationConnection(
            tenant_id=tenant.id,
            owner_type="user",
            owner_user_id=owner.id,
            connector_key="confluence",
            display_name="Owner Confluence",
            created_by_user_id=owner.id,
        )
        tenant_owned = IntegrationConnection(
            tenant_id=tenant.id,
            owner_type="tenant",
            connector_key="google_drive",
            display_name="Company Drive",
            created_by_user_id=owner.id,
        )
        session.add_all([personal, tenant_owned])
        await session.flush()

        encryption_key = base64.urlsafe_b64encode(bytes(range(32))).decode("ascii")
        credentials = IntegrationCredentialService(session, encryption_key)
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
        assert (
            await session.scalar(
                select(IntegrationCredential).where(
                    IntegrationCredential.integration_connection_id == personal.id
                )
            )
            is record
        )


def test_integration_encryption_key_accepts_unpadded_urlsafe_base64() -> None:
    expected = bytes(range(32))
    encryption_key = base64.urlsafe_b64encode(expected).decode("ascii").rstrip("=")

    assert IntegrationCredentialService._decode_key(encryption_key) == expected


@pytest.mark.asyncio
async def test_integration_list_eager_loads_optional_credentials(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
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
            IntegrationConnection(
                tenant_id=tenant.id,
                owner_type="tenant",
                connector_key="file",
                display_name="Uploaded files",
                status="draft",
                created_by_user_id=owner.id,
            )
        )

    async with session_factory.begin() as session:
        result = await IntegrationConnectionService(session).list_connections(
            actor,
            page_size=100,
        )

    assert result["total"] == 1
    assert result["items"][0]["credential_configured"] is False


@pytest.mark.asyncio
async def test_authorized_item_is_projectable_without_further_database_io(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """The knowledge viewer reads an authorized Item outside the await chain.

    Its upload lifecycle must already be loaded: a lazy load would run asyncpg
    I/O from synchronous code and fail the request with MissingGreenlet.
    """

    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
        tenant = await auth.create_tenant("viewer", "Viewer")
        owner = await auth.create_user("viewer@example.com")
        role = await auth.create_role(
            tenant.id,
            "reader",
            "Reader",
            permission_codes=["knowledge.read", "access.manage"],
        )
        await auth.assign_membership(owner.id, tenant.id, role.id)
        actor = await auth.get_context(owner.id, tenant_id=tenant.id)
        items = ItemService(session)
        collection = await items.create_collection(
            tenant_id=tenant.id,
            title="Policies",
            created_by_user_id=owner.id,
        )
        await CollectionAccessService(session).grant(
            collection.id,
            principal_type="user",
            principal_id=owner.id,
            role="owner",
            actor=actor,
        )
        # A connector-ingested document has no upload row at all.
        ingested = await items.create_document(
            tenant_id=tenant.id,
            parent_item_id=collection.id,
            title="Ingested policy",
            document_type="pdf",
            created_by_user_id=owner.id,
        )
        ingested_id = ingested.id

    async with session_factory.begin() as session:
        item = await ItemService(session).get_item_by_canonical_id(
            str(ingested_id), access=actor
        )
        loaded = item

    # Outside the session, reading the relationship must not touch the database.
    assert loaded.upload is None
    assert loaded.status == "pending"


@pytest.mark.asyncio
async def test_external_resource_mapping_preserves_canonical_item_identity(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
        tenant = await auth.create_tenant("source-map", "Source mapping")
        owner = await auth.create_user("source-map@example.com")
        role = await auth.create_role(tenant.id, "source-manager", "Source Manager")
        await auth.assign_membership(owner.id, tenant.id, role.id)
        collection = await ItemService(session).create_collection(
            tenant_id=tenant.id,
            title="External knowledge",
            created_by_user_id=owner.id,
        )
        connection = IntegrationConnection(
            tenant_id=tenant.id,
            connector_key="confluence",
            owner_type="tenant",
            display_name="Company wiki",
            status="active",
            created_by_user_id=owner.id,
        )
        session.add(connection)
        await session.flush()
        source = IngestionSource(
            integration_connection_id=connection.id,
            target_item_id=collection.id,
            checkpoint={},
            status="active",
            created_by_user_id=owner.id,
        )
        session.add(source)
        await session.flush()

        existing_item = Item(
            id=uuid4(),
            tenant_id=tenant.id,
            item_type="document",
            parent_item_id=collection.id,
            parent_relation="child",
            document_type="confluence_page",
            title="Existing title",
            status="ready",
        )
        session.add(existing_item)
        await session.flush()
        resource = ExternalResource(
            item_id=existing_item.id,
            ingestion_source_id=source.id,
            external_id="page-42",
            external_version="v1",
        )
        session.add(resource)
        await session.flush()

        updated = await ItemService(session).upsert_ingested_item(
            source.id,
            "page-42",
            canonical_external_id="confluence:page-42",
            item_type="document",
            title="Updated title",
            document_type="confluence_page",
            external_version="v2",
            etag="etag-v2",
        )

        assert updated.id == existing_item.id
        assert updated.title == "Updated title"
        stored_resources = list(
            await session.scalars(
                select(ExternalResource).where(
                    ExternalResource.ingestion_source_id == source.id,
                    ExternalResource.external_id == "page-42",
                )
            )
        )
        assert len(stored_resources) == 1
        assert stored_resources[0].item_id == existing_item.id
        assert stored_resources[0].external_version == "v2"
        assert stored_resources[0].etag == "etag-v2"


@pytest.mark.asyncio
async def test_admin_collection_creation_is_tenant_scoped_and_audited(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
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

        created = await ItemCatalogService(session).create_collection(
            actor,
            title="Engineering handbook",
            inherit_access=True,
            metadata={"description": "Governed engineering knowledge"},
        )

        assert created["item_type"] == "collection"
        assert created["title"] == "Engineering handbook"
        assert created["inherit_access"] is True
        assert created["metadata"] == {"description": "Governed engineering knowledge"}
        assert created["created_by_user_id"] == str(owner.id)
        assert created["collection_access"] == [
            {
                "principal_type": "user",
                "principal_id": str(owner.id),
                "role": "owner",
            }
        ]
        listed = await ItemCatalogService(session).list_items(
            actor,
            item_type="collection",
            search="governed engineering",
            created_by_user_id=owner.id,
        )
        assert listed["total"] == 1

        nested = await ItemCatalogService(session).create_collection(
            actor,
            title="Engineering runbooks",
            parent_item_id=UUID(created["id"]),
            inherit_access=True,
        )
        scoped = await ItemCatalogService(session).list_items(
            actor,
            item_type="collection",
            parent_item_id=UUID(created["id"]),
        )
        assert scoped["total"] == 1
        assert scoped["items"][0]["id"] == nested["id"]
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

        updated = await ItemCatalogService(session).update_collection(
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
        chunk = self._body[self._offset : end]
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


class _UnavailableIngestion:
    async def index_upload(self, *_: object, **__: object) -> Item:
        raise DocumentProcessingError("indexing is outside this integration test")


def _uploads(
    session_factory: async_sessionmaker[AsyncSession],
    storage: _UploadStorage,
    **kwargs: object,
) -> DocumentUploadService:
    return DocumentUploadService(
        session_factory,
        object_storage=storage,
        ingestion_service=_UnavailableIngestion(),  # type: ignore[arg-type]
        document_source=object(),  # type: ignore[arg-type]
        **kwargs,
    )


async def _collection_upload_contexts(
    session_factory: async_sessionmaker[AsyncSession],
) -> tuple[UUID, AuthContext, AuthContext, AuthContext]:
    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
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
    collection_id, editor, viewer, _ = await _collection_upload_contexts(
        session_factory
    )
    storage = _UploadStorage()
    uploads = _uploads(session_factory, storage)

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
        external_resource = await session.scalar(
            select(ExternalResource.id).where(ExternalResource.item_id == first.item.id)
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
    assert external_resource is None
    assert visible.id == first.item.id


@pytest.mark.asyncio
async def test_collection_upload_rejects_tenant_permission_and_collection_states(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    collection_id, _, viewer, outsider = await _collection_upload_contexts(
        session_factory
    )
    uploads = _uploads(session_factory, _UploadStorage())
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
    uploads = _uploads(
        session_factory,
        _UploadStorage(),
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

    failing_uploads = _uploads(session_factory, _UploadStorage(fail=True))
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
            select(ItemUpload).where(ItemUpload.idempotency_key == "storage-failure")
        )
        assert failed is not None
        item = await session.get(Item, failed.item_id)
    assert failed.status == "failed"
    assert item is not None and item.status == "failed"


class InMemoryObjectStorage:
    def __init__(self) -> None:
        self.objects: dict[str, tuple[bytes, str | None]] = {}

    def put_bytes(self, data: bytes, key: str, *, content_type: str | None = None) -> StoredObject:
        self.objects[key] = (data, content_type)
        return StoredObject(size_bytes=len(data), content_type=content_type)

    def presign_download(self, key: str, *, expires_seconds: int) -> PresignedRequest:
        return PresignedRequest(
            url=f"https://storage.test/{key}", method="GET", headers={}, expires_at=datetime.now(UTC)
        )

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        if key not in self.objects:
            raise ObjectNotFoundError(f"object not found: {key}")
        return self.objects[key][0]


class StubUploads:
    """Stand in for ``DocumentUploadService.upload_to_collection``.

    ``ArtifactService.publish`` only needs the shape of the result
    (``item.id``/``item.title``/``item.status`` and ``created``); the real
    upload/ingestion path is exercised by its own tests.
    """

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    async def upload_to_collection(
        self,
        access: AuthContext,
        collection_id: UUID,
        *,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        content: Any,
    ) -> Any:
        data = await content.read()
        self.calls.append(
            {
                "access": access,
                "collection_id": collection_id,
                "idempotency_key": idempotency_key,
                "file_name": file_name,
                "content_type": content_type,
                "data": data,
            }
        )
        return SimpleNamespace(
            item=SimpleNamespace(id=uuid4(), title=file_name, status="ready"),
            created=True,
        )


@pytest.mark.asyncio
async def test_conversation_files_keep_every_revision_under_a_private_collection(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """A produced file becomes a private, revisioned, downloadable document.

    Writing the same file name again is a new revision of the same document,
    reading a knowledge document back out is access-checked, and publishing
    into the Knowledge Base stays an explicit, separately authorized step.
    """

    storage = InMemoryObjectStorage()
    async with session_factory.begin() as session:
        auth = IdentityStoreService(session)
        tenant = await auth.create_tenant("artifacts", "Artifacts")
        writer = await auth.create_user("writer@example.com")
        reader = await auth.create_user("reader@example.com")
        role = await auth.create_role(
            tenant.id, "member", "Member", permission_codes=["knowledge.read", "access.manage"]
        )
        await auth.assign_membership(writer.id, tenant.id, role.id)
        await auth.assign_membership(reader.id, tenant.id, role.id)
        writer_context = await auth.get_context(writer.id, tenant_id=tenant.id)
        reader_context = await auth.get_context(reader.id, tenant_id=tenant.id)

        items = ItemService(session)
        # An ordinary Collection: no "template library" flag exists any more.
        # It is a valid publish destination
        # purely because the writer has editor access to it.
        library = await items.create_collection(
            tenant_id=tenant.id,
            title="Legal documents",
            created_by_user_id=writer.id,
        )
        await CollectionAccessService(session).grant(
            library.id, principal_type="user", principal_id=writer.id, role="editor", actor=writer_context
        )
        source_document = await items.create_document(
            tenant_id=tenant.id,
            parent_item_id=library.id,
            title="NDA template",
            document_type="markdown",
            created_by_user_id=writer.id,
            mime_type="text/markdown",
            size_bytes=30,
            storage_key=f"tenants/{tenant.id}/items/source-document/raw",
            metadata={"file_name": "nda-template.md"},
            status="ready",
        )
        # A Collection the writer can only view, not edit — the real guard
        # publish() has left once the "template library" flag is gone.
        viewer_only = await items.create_collection(
            tenant_id=tenant.id,
            title="Reader's private notes",
            created_by_user_id=reader.id,
        )
        await CollectionAccessService(session).grant(
            viewer_only.id, principal_type="user", principal_id=writer.id, role="viewer", actor=reader_context
        )
        conversation = Conversation(tenant_id=tenant.id, user_id=writer.id, title="Draft")
        session.add(conversation)
        await session.flush()
    storage.objects[source_document.storage_key] = (b"# NDA\n\nBetween [A] and [B].\n", "text/markdown")

    uploads = StubUploads()
    service = ArtifactService(
        session_factory,
        object_storage=lambda: storage,
        uploads=lambda: uploads,
        max_content_bytes=1_000_000,
        download_url_seconds=60,
    )

    created = await service.record_generated(
        writer_context,
        conversation_id=conversation.id,
        request_id="req-1",
        file_name="Q3-memo.md",
        mime_type="text/markdown",
        data=b"# Q3 memo\n\nDate: 2026-09-01\n",
        summary="Produced Q3-memo.md",
    )
    artifact_id = UUID(created["id"])
    first_key = f"tenants/{tenant.id}/items/{artifact_id}/revisions/1/Q3-memo.md"
    assert created["revision"] == 1
    assert created["file_name"] == "Q3-memo.md"
    assert created["download_url"] == f"https://storage.test/{first_key}"
    assert storage.objects[first_key][0] == b"# Q3 memo\n\nDate: 2026-09-01\n"

    # The same file name again is the next revision of the same document, so
    # the user keeps one card with a history rather than two near-identical
    # files.
    edited = await service.record_generated(
        writer_context,
        conversation_id=conversation.id,
        request_id="req-2",
        file_name="/mnt/data/Q3-memo.md",
        mime_type="",
        data=b"# Q3 memo\n\nDate: 2026-09-06\n",
        summary="Produced Q3-memo.md",
    )
    second_key = f"tenants/{tenant.id}/items/{artifact_id}/revisions/2/Q3-memo.md"
    assert edited["id"] == created["id"]
    assert edited["revision"] == 2
    # A workspace path never becomes part of the document's identity.
    assert edited["file_name"] == "Q3-memo.md"
    # The content type is recovered from the extension when none was reported.
    assert edited["mime_type"] == "text/markdown"
    # A revision never overwrites the previous object.
    assert storage.objects[first_key][0] == b"# Q3 memo\n\nDate: 2026-09-01\n"
    assert storage.objects[second_key][0] == b"# Q3 memo\n\nDate: 2026-09-06\n"

    # A different file name is a different document in the same conversation.
    chart = await service.record_generated(
        writer_context,
        conversation_id=conversation.id,
        request_id="req-3",
        file_name="revenue.png",
        mime_type="",
        data=b"\x89PNG fake",
        summary="Produced revenue.png",
    )
    assert chart["id"] != created["id"]
    assert chart["mime_type"] == "image/png"

    with pytest.raises(ArtifactValidationError, match="empty"):
        await service.record_generated(
            writer_context,
            conversation_id=conversation.id,
            request_id="req-4",
            file_name="empty.txt",
            mime_type="text/plain",
            data=b"",
            summary="Produced empty.txt",
        )

    detail = await service.get(writer_context, artifact_id)
    assert [revision["revision"] for revision in detail["revisions"]] == [1, 2]
    assert detail["conversation_id"] == str(conversation.id)
    first_content = await service.content(writer_context, artifact_id, revision=1)
    assert "2026-09-01" in first_content["content"]
    # A binary revision is named, never decoded as text.
    binary = await service.content(writer_context, UUID(chart["id"]))
    assert binary["content"].startswith("(binary document: image/png")

    working = await service.conversation_artifacts(
        writer_context, conversation.id, content_characters=12
    )
    assert [artifact.file_name for artifact in working] == ["Q3-memo.md", "revenue.png"]
    assert working[0].revision == 2
    assert working[0].content_truncated is True
    assert working[0].content.startswith("# Q3 memo")

    # Rebuilding a workspace reads the current revision of each file back out.
    files = await service.conversation_files(writer_context, conversation.id)
    assert {(source.file_name, source.data) for source in files} == {
        ("Q3-memo.md", b"# Q3 memo\n\nDate: 2026-09-06\n"),
        ("revenue.png", b"\x89PNG fake"),
    }

    # Any readable document is a valid source to open into a workspace.
    opened = await service.source_file(writer_context, source_document.id)
    assert opened.title == "NDA template"
    assert opened.file_name == "nda-template.md"
    assert opened.data.startswith(b"# NDA")
    # A document outside the caller's Collections is not a source they can
    # open — and it is reported as missing, never as "exists but denied".
    with pytest.raises(DocumentNotFoundError):
        await service.source_file(reader_context, source_document.id)

    resolved = await service.resolve_access(
        AgentContext(user_id=str(writer.id), tenant_id=str(tenant.id), roles=[])
    )
    assert resolved.user_id == writer.id and resolved.tenant_id == tenant.id

    # The reader shares the tenant but not the writer's private collection.
    with pytest.raises(DocumentNotFoundError):
        await service.get(reader_context, artifact_id)

    # Publishing into the Knowledge Base is explicit and separately authorized;
    # nothing above wrote a conversation file into a Collection on its own.
    published = await service.publish(writer_context, artifact_id, collection_id=library.id)
    assert published["collection_id"] == str(library.id)
    assert published["created"] is True
    assert uploads.calls[0]["collection_id"] == library.id
    assert uploads.calls[0]["content_type"] == "text/markdown"
    assert uploads.calls[0]["data"] == storage.objects[second_key][0]

    # The real remaining guard is authorization: a Collection the caller can
    # only view, not edit, is not a valid publish destination.
    with pytest.raises(AuthorizationError):
        await service.publish(writer_context, artifact_id, collection_id=viewer_only.id)

    # Publishing into a document (not a Collection) is rejected too.
    with pytest.raises(ArtifactValidationError, match="must be a Collection"):
        await service.publish(writer_context, artifact_id, collection_id=source_document.id)

    async with session_factory() as session:
        item = await session.get(Item, artifact_id)
        assert item is not None
        assert item.parent_item_id == ItemService.artifact_collection_id(tenant.id, writer.id)
        assert item.storage_key == second_key
        assert item.metadata_["artifact"]["current_revision"] == 2
        revisions = list(
            await session.scalars(
                select(ArtifactRevision.revision_number)
                .where(ArtifactRevision.item_id == artifact_id)
                .order_by(ArtifactRevision.revision_number)
            )
        )
        assert revisions == [1, 2]
        actions = set(
            await session.scalars(
                select(AuditLog.action).where(AuditLog.resource_id == str(artifact_id))
            )
        )
        assert {"artifact.created", "artifact.revised", "artifact.published"} <= actions
