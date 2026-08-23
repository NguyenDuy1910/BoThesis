from __future__ import annotations

import os
from collections.abc import AsyncIterator
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
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
    Document,
    DocumentChunk,
    Message,
    SyncRun,
)
from bothesis.connector.base import BaseSourceConnector
from bothesis.connector.protocol import (
    AccessPolicy,
    ChangeType,
    Chunk,
    CitationInfo,
    CitationSpan,
    ConnectorCheckpoint,
    ConnectorScope as SourceScope,
    DocumentItem,
    DocumentKind,
    ItemChange,
    SourceIdentity,
    SourceProvider,
    StorageObject,
    TextPart,
)
from bothesis.api import register_admin_error_handlers
from bothesis.api.admin import admin_router
from bothesis.db.engine import get_transactional_session
from bothesis.document_index.raw_storage import PostgresBlobStorage
from bothesis.services import (
    AccessRequestService,
    AclService,
    AdminConflictError,
    AdminDocumentService,
    AdminNotFoundError,
    AuthService,
    AuthorizationError,
    ConnectorSyncService,
    DatasourceService,
    DocumentChunkInput,
    DocumentNotFoundError,
    DocumentService,
    GroupService,
    UserService,
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
        await PostgresBlobStorage(session).write(personal.id, b"private content")
        assert await documents.get_document_text(personal.id, access=actor) == (
            "private content"
        )
        assert await PostgresBlobStorage(session).read(personal.id) == b"private content"
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


@pytest.mark.asyncio
async def test_connector_worker_persists_activates_and_projects_snapshot(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("worker-acme", "Worker Acme")
        owner = await auth.create_user("worker-admin@example.com")
        role = await auth.create_role(
            tenant.id,
            "worker-admin",
            "Worker Admin",
            permission_codes=["source.manage", "knowledge.read"],
        )
        await auth.assign_membership(owner.id, tenant.id, role.id)
        configured = Connector(
            tenant_id=tenant.id,
            provider="file",
            display_name="Managed files",
            created_by_user_id=owner.id,
        )
        session.add(configured)
        await session.flush()
        stored_scope = ConnectorScope(
            connector_id=configured.id,
            scope_value="file",
            scope_type="source_provider",
            display_name="Files",
        )
        session.add(stored_scope)
        await session.flush()
        run = SyncRun(
            connector_scope_id=stored_scope.id,
            generation=1,
            trigger_type="manual",
            status="pending",
        )
        session.add(run)
        await session.flush()
        run_id = run.id
        connector_id = configured.id

    item = DocumentItem(
        id="file::report-1",
        title="Annual report",
        document_kind=DocumentKind.PDF,
        source=SourceIdentity(
            connector_id=str(connector_id),
            provider=SourceProvider.FILE,
            external_id="report-1",
            external_version="v1",
        ),
        access=AccessPolicy.from_reader_ids(["public"]),
        content=[TextPart(element_id="p1", page=1, text="Grounded report")],
        original=StorageObject(
            provider="s3",
            bucket="documents",
            key="worker-acme/report-1.pdf",
            file_name="report-1.pdf",
            size_bytes=100,
            content_type="application/pdf",
            checksum_sha256="b" * 64,
        ),
    )
    chunk = Chunk(
        id="file::report-1:0",
        item_id=item.id,
        chunk_index=0,
        chunk_text="Grounded report",
        content_type="text",
        citation=CitationInfo(
            spans=(
                CitationSpan(
                    page=1,
                    element_id="p1",
                    start_offset=0,
                    end_offset=15,
                ),
            )
        ),
    )

    class Source(BaseSourceConnector):
        source = "file"

        async def test_connection(self) -> bool:
            return True

        async def list_scopes(self) -> list[SourceScope]:
            return []

        async def discover_changes(
            self,
            checkpoint: ConnectorCheckpoint,
            scope: SourceScope,
        ) -> list[ItemChange]:
            del checkpoint, scope
            return [
                ItemChange(
                    type=ChangeType.UPSERT,
                    item_id=item.id,
                    item=item,
                )
            ]

        async def fetch_item(self, item_id: str) -> DocumentItem:
            assert item_id == item.id
            return item

        async def fetch_chunks(self, value: DocumentItem) -> tuple[Chunk, ...]:
            assert value.id == item.id
            return (chunk,)

        def next_checkpoint(self) -> ConnectorCheckpoint:
            return ConnectorCheckpoint()

    class Embedder:
        model = "embed-test"

        async def embed_query(self, query: str) -> list[float]:
            return [float(len(query))]

        async def embed_documents(self, documents: list[str]) -> list[list[float]]:
            return [[float(len(value))] for value in documents]

    class Store:
        def __init__(self) -> None:
            self.points: list[object] = []
            self.payload_updates: list[dict[str, object]] = []

        async def upsert_points(self, points: list[object]) -> None:
            self.points.extend(points)

        async def set_payload(
            self,
            *,
            payload: dict[str, object],
            points: object,
        ) -> None:
            del points
            self.payload_updates.append(dict(payload))

    store = Store()
    result = await ConnectorSyncService(
        session_factory,
        store,  # type: ignore[arg-type]
        Embedder(),  # type: ignore[arg-type]
    ).run(run_id, Source())

    assert result.processed_items == 1
    assert result.written_chunks == 1
    async with session_factory() as session:
        stored_run = await session.get(SyncRun, run_id)
        stored_document = await session.scalar(
            select(Document).where(Document.external_id == item.id)
        )
        assert stored_run is not None and stored_run.status == "completed"
        assert stored_document is not None
        assert stored_document.raw_storage_key == "worker-acme/report-1.pdf"
        assert stored_document.content_sha256 == "b" * 64
        assert (
            stored_document.metadata_["canonical_item"]["original"]["bucket"]
            == "documents"
        )
        assert stored_document.indexing_status == "indexed"
        assert stored_document.generation == 1
        assert stored_document.connector_scope.active_generation == 1
        stored_chunk = await session.scalar(
            select(DocumentChunk).where(
                DocumentChunk.document_id == stored_document.id
            )
        )
        assert stored_chunk is not None
        assert stored_chunk.content == "Grounded report"
        assert stored_chunk.metadata_["chunk_id"] == chunk.id
        assert stored_chunk.metadata_["citation_spans"][0]["element_id"] == "p1"
    assert len(store.points) == 1
    assert getattr(store.points[0], "payload")["is_deleted"] is True
    assert store.payload_updates[-1] == {"is_deleted": False}


@pytest.mark.asyncio
async def test_admin_services_enforce_tenant_isolation_and_group_permissions(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("admin-acme", "Admin Acme")
        other_tenant = await auth.create_tenant("admin-other", "Admin Other")
        admin = await auth.create_user("admin@acme.example")
        other_admin = await auth.create_user("admin@other.example")
        admin_role = await auth.create_role(
            tenant.id,
            "admin",
            "Administrator",
            permission_codes=["admin"],
        )
        other_admin_role = await auth.create_role(
            other_tenant.id,
            "admin",
            "Administrator",
            permission_codes=["admin"],
        )
        analyst_role = await auth.create_role(
            tenant.id,
            "analyst",
            "Analyst",
            permission_codes=["knowledge.read"],
        )
        await auth.assign_membership(admin.id, tenant.id, admin_role.id)
        await auth.assign_membership(
            other_admin.id, other_tenant.id, other_admin_role.id
        )
        actor = await auth.get_context(admin.id)
        outsider_actor = await auth.get_context(other_admin.id)

        group = await GroupService(session).create_group(
            actor,
            code="finance",
            display_name="Finance",
            permission_codes=["document.manage"],
        )
        created = await UserService(session).create_user(
            actor,
            email="analyst@acme.example",
            display_name="Analyst",
            role_id=analyst_role.id,
            group_ids=[UUID(group["id"])],
        )
        context = await auth.get_context(UUID(created["id"]))

        assert context.permission_codes == ("document.manage", "knowledge.read")
        assert context.principal_tokens == ("group:finance",)
        with pytest.raises(AdminNotFoundError, match="user not found"):
            await UserService(session).get_user(
                outsider_actor, UUID(created["id"])
            )


@pytest.mark.asyncio
async def test_datasource_service_persists_validation_and_sync_lifecycle(
    session_factory: async_sessionmaker[AsyncSession],
    tmp_path,
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("sources", "Sources")
        admin = await auth.create_user("sources-admin@example.com")
        role = await auth.create_role(
            tenant.id,
            "admin",
            "Administrator",
            permission_codes=["admin"],
        )
        await auth.assign_membership(admin.id, tenant.id, role.id)
        actor = await auth.get_context(admin.id)
        service = DatasourceService(session)

        datasource = await service.create_datasource(
            actor,
            provider="file",
            display_name="Files",
            settings={"base_dir": str(tmp_path)},
        )
        assert datasource["status"] == "draft"

        async def upload_content() -> AsyncIterator[bytes]:
            yield b"Enterprise "
            yield b"policy"

        uploaded = await service.upload_file(
            actor,
            int(datasource["id"]),
            file_name="policy.txt",
            content=upload_content(),
        )
        assert uploaded["file_name"] == "policy.txt"
        assert uploaded["size_bytes"] == len(b"Enterprise policy")
        assert (tmp_path / f"{uploaded['id']}.json").is_file()
        assert (await service.validate_datasource(actor, int(datasource["id"])))[
            "valid"
        ] is True
        chat_connectors = await service.list_chat_connectors(actor)
        assert chat_connectors["total"] == 1
        assert chat_connectors["items"][0]["id"] == datasource["id"]
        assert chat_connectors["items"][0]["capabilities"] == [
            "knowledge_search"
        ]

        queued = await service.trigger_sync(actor, int(datasource["id"]))
        run_id = UUID(queued["items"][0]["id"])
        assert queued["items"][0]["status"] == "pending"
        with pytest.raises(AdminConflictError, match="active ingestion"):
            await service.delete_datasource(actor, int(datasource["id"]))
        cancelled = await service.cancel_sync(actor, run_id)
        assert cancelled["status"] == "cancelled"
        retried = await service.retry_sync(actor, run_id)
        assert retried["status"] == "pending"


@pytest.mark.asyncio
async def test_access_decision_and_acl_policy_materialize_document_access(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        documents = DocumentService(session)
        tenant = await auth.create_tenant("access", "Access")
        admin = await auth.create_user("access-admin@example.com")
        reader = await auth.create_user("reader@access.example")
        admin_role = await auth.create_role(
            tenant.id,
            "admin",
            "Administrator",
            permission_codes=["admin"],
        )
        reader_role = await auth.create_role(
            tenant.id,
            "reader",
            "Reader",
            permission_codes=["knowledge.read"],
        )
        await auth.assign_membership(admin.id, tenant.id, admin_role.id)
        await auth.assign_membership(reader.id, tenant.id, reader_role.id)
        actor = await auth.get_context(admin.id)
        document = await documents.create_enterprise_document(
            tenant.id,
            origin="generated",
            created_by_user_id=admin.id,
            title="Governed plan",
            allowed_principal_tokens=["group:leaders"],
        )

        requests = AccessRequestService(session)
        request = await requests.create_request(
            actor,
            requester_user_id=reader.id,
            resource_type="document",
            resource_id=str(document.id),
            access_type="read",
        )
        approved = await requests.decide_request(
            actor, UUID(request["id"]), decision="approved"
        )
        await session.refresh(document)
        assert approved["status"] == "approved"
        assert "email:reader@access.example" in document.allowed_principal_tokens

        policy = await AclService(session).create_policy(
            actor,
            name="Leadership plan",
            resource_type="document",
            resource_id=str(document.id),
            allowed_principal_tokens=["group:leaders"],
            denied_principal_tokens=["group:contractors"],
        )
        detail = await AdminDocumentService(session).get_document(actor, document.id)
        assert detail["allowed_principal_tokens"] == ["group:leaders"]
        assert detail["denied_principal_tokens"] == ["group:contractors"]
        assert policy["resource_id"] == str(document.id)


@pytest.mark.asyncio
async def test_admin_api_uses_database_identity_and_trusted_tenant_boundary(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    async with session_factory.begin() as session:
        auth = AuthService(session)
        tenant = await auth.create_tenant("api-admin", "API Admin")
        admin = await auth.create_user("api-admin@example.com")
        role = await auth.create_role(
            tenant.id,
            "admin",
            "Administrator",
            permission_codes=["admin"],
        )
        await auth.assign_membership(admin.id, tenant.id, role.id)

    async def test_session():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except BaseException:
                await session.rollback()
                raise

    app = FastAPI()
    app.state.allow_insecure_development_identity = True
    register_admin_error_handlers(app)
    app.include_router(admin_router, prefix="/api/v1")
    app.dependency_overrides[get_transactional_session] = test_session
    headers = {
        "X-Bothesis-User-Id": str(admin.id),
        "X-Bothesis-Tenant-Id": str(tenant.id),
    }
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.get("/api/v1/admin/overview", headers=headers)
        assert response.status_code == 200
        assert response.json()["tenant"]["id"] == str(tenant.id)

        denied = await client.get(
            "/api/v1/admin/users",
            headers={**headers, "X-Bothesis-Tenant-Id": str(uuid4())},
        )
        assert denied.status_code == 403
