"""Application orchestration used by the FastAPI boundary."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Literal
from uuid import UUID, uuid4

from qdrant_client import models as qmodels
from sqlalchemy import select
from bothesis.agent import Agent, AgentConfig
from bothesis.agent.models import AgentContext, ConversationMessage
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearch
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.connector.file import FileProcessor
from bothesis.connector.protocol import (
    BoundingBox,
    CitationInfo,
    CitationSpan,
    SourceIdentity,
    SourceProvider,
)
from bothesis.connector.provider_cache import PostgresProviderFileCache
from bothesis.db.engine import get_session_factory, session_scope
from bothesis.db.models import Item
from bothesis.document_index.indexer import (
    DEFAULT_DIRECT_MAX_BYTES,
    DEFAULT_PROCESSING_MAX_BYTES,
    DocumentPipeline,
)
from bothesis.document_index import DocumentProcessingError
from bothesis.document_index.raw_storage import S3DocumentStorage
from bothesis.document_index.search import QdrantSearchIndex
from bothesis.document_index.semantic_contextualizer import SemanticContextualizer
from bothesis.document_index.vector_store import QdrantDocumentIndex, VectorStore
from bothesis.knowledge import CitationResolver
from bothesis.knowledge.retriever import DocumentIndexRetriever
from bothesis.observability import create_langfuse_tracing
from bothesis.services.preview import KnowledgePreviewRenderer, KnowledgePreviewService
from bothesis.services import (
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_UPLOAD_URL_SECONDS,
    KNOWLEDGE_READ_PERMISSION,
    AsyncUploadStream,
    AuditService,
    AuthContext,
    ChatDocumentSourceService,
    CollectionAccessService,
    DocumentNotFoundError,
    ItemService,
    RequestIdentity,
    UploadConflictError,
    UploadService,
    require_tenant_permission,
)
from bothesis.services.request_identity import resolve_auth_context

log = logging.getLogger(__name__)


class ApiService:
    """Own chat, upload, citation, and document application workflows."""

    def __init__(
        self,
        *,
        allow_insecure_development_identity: bool,
        qdrant_prefer_grpc: bool,
        contextualization_enabled: bool = False,
        contextualization_model: str | None = None,
        hybrid_candidate_limit: int = 20,
    ) -> None:
        if hybrid_candidate_limit < 1:
            raise ValueError("hybrid_candidate_limit must be at least one")
        self._allow_insecure_development_identity = (
            allow_insecure_development_identity
        )
        self._qdrant_prefer_grpc = qdrant_prefer_grpc
        self._contextualization_enabled = contextualization_enabled
        self._contextualization_model = contextualization_model
        self._hybrid_candidate_limit = hybrid_candidate_limit
        self._session_factory: Any | None = None
        self._storage: Any | None = None
        self._storage_initialized = False
        self._uploads: UploadService | None = None
        self._previews: KnowledgePreviewService | None = None
        self._pipeline: DocumentPipeline | None = None
        self._agent: Agent | None = None
        self._contextualization_transport: OpenRouterTransport | None = None

    async def chat_events(
        self,
        identity: RequestIdentity,
        *,
        message: str,
        tenant_id: str | None,
        user_id: str | None,
        conversation_id: UUID | None,
        history: list[tuple[Literal["user", "assistant"], str]],
        knowledge_mode: Literal["auto", "selected", "off"],
        collection_item_ids: list[UUID],
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[str]:
        access = await self._resolve_access(
            identity,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with session_scope(self._sessions()) as session:
            allowed_ids = await CollectionAccessService(
                session
            ).allowed_collection_ids(access)
        allowed_set = set(allowed_ids)
        if knowledge_mode == "off":
            selected_collection_ids: tuple[UUID, ...] = ()
            allowed_tool_names: tuple[str, ...] | None = ()
        elif knowledge_mode == "selected":
            if not collection_item_ids or not set(collection_item_ids).issubset(allowed_set):
                raise PermissionError("one or more selected Collections are unavailable")
            selected_collection_ids = tuple(dict.fromkeys(collection_item_ids))
            allowed_tool_names = None
        else:
            selected_collection_ids = allowed_ids
            allowed_tool_names = None
        if access.tenant_id is None:
            raise PermissionError("an active tenant membership is required for chat")
        resolved_conversation_id = conversation_id or uuid4()
        context = AgentContext(
            user_id=str(access.user_id),
            tenant_id=str(access.tenant_id),
            roles=[access.role_code] if access.role_code else [],
            collection_item_ids=tuple(str(value) for value in selected_collection_ids),
            conversation_id=str(resolved_conversation_id),
            request_id=uuid4().hex,
            history=tuple(
                ConversationMessage(role=role, content=content)
                for role, content in history
            ),
            allowed_tool_names=allowed_tool_names,
        )
        agent = self._get_agent()

        async def event_stream() -> AsyncIterator[str]:
            stream = agent.run(message, context)
            try:
                async for event in stream:
                    if await is_disconnected():
                        break
                    yield event.model_dump_json()
            finally:
                await stream.aclose()

        return event_stream()

    async def list_chat_collections(
        self,
        identity: RequestIdentity,
    ) -> dict[str, Any]:
        async with session_scope(self._sessions()) as session:
            access = await resolve_auth_context(
                identity,
                session,
                allow_insecure_development_identity=(
                    self._allow_insecure_development_identity
                ),
            )
            ids = await CollectionAccessService(session).allowed_collection_ids(access)
            if not ids:
                return {"items": [], "total": 0}
            collections = list(
                await session.scalars(
                    select(Item)
                    .where(Item.id.in_(ids))
                    .order_by(Item.title, Item.id)
                )
            )
            return {
                "items": [
                    {
                        "id": str(item.id),
                        "title": item.title,
                        "parent_item_id": (
                            str(item.parent_item_id) if item.parent_item_id else None
                        ),
                    }
                    for item in collections
                ],
                "total": len(collections),
            }

    async def start_document_upload(
        self,
        identity: RequestIdentity,
        *,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        size_bytes: int,
    ) -> dict[str, Any]:
        access = await self._resolve_access(identity)
        result = await self._upload_service().start_upload(
            access,
            idempotency_key=idempotency_key,
            file_name=file_name,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        return {
            "upload_required": result.upload_required,
            "target": self._target_payload(result.target),
            "document": self._document_metadata(result.item),
        }

    async def complete_document_upload(
        self,
        identity: RequestIdentity,
        document_id: UUID,
    ) -> dict[str, Any]:
        access = await self._resolve_access(identity)
        document = await self._upload_service().complete_upload(access, document_id)
        return self._document_metadata(document)

    async def upload_collection_document(
        self,
        identity: RequestIdentity,
        collection_id: UUID,
        *,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        content: AsyncUploadStream,
    ) -> dict[str, Any]:
        """Store and index a native upload under one authorized collection."""

        access = await self._resolve_access(identity)
        upload = await self._upload_service().upload_to_collection(
            access,
            collection_id,
            idempotency_key=idempotency_key,
            file_name=file_name,
            content_type=content_type,
            content=content,
        )
        ingestion_status: Literal["ready", "failed"] = "ready"
        document = upload.item
        try:
            document = await self._document_pipeline().index_document(
                document.id,
                access=access,
            )
        except DocumentProcessingError:
            ingestion_status = "failed"
            document = await self._upload_service().get_document(access, document.id)
        async with session_scope(self._sessions()) as session:
            await AuditService(session).record(
                access,
                action="document.uploaded",
                resource_type="document",
                resource_id=str(document.id),
                details={
                    "collection_id": str(collection_id),
                    "created": upload.created,
                    "ingestion_status": ingestion_status,
                },
            )
        return {
            "document": self._document_metadata(document),
            "ingestion_status": ingestion_status,
            "created": upload.created,
        }

    async def retry_document_indexing(
        self,
        identity: RequestIdentity,
        document_id: UUID,
    ) -> dict[str, Any]:
        """Retry indexing from an already available native upload."""

        access = await self._resolve_access(identity)
        document = await self._upload_service().get_document(
            access,
            document_id,
            minimum_role="editor",
        )
        if document.upload is None or document.upload.status != "available":
            raise UploadConflictError(
                "the original file is unavailable; upload the file again"
            )
        ingestion_status: Literal["ready", "failed"] = "ready"
        try:
            document = await self._document_pipeline().index_document(
                document.id,
                access=access,
            )
        except DocumentProcessingError:
            ingestion_status = "failed"
            document = await self._upload_service().get_document(access, document.id)
        async with session_scope(self._sessions()) as session:
            await AuditService(session).record(
                access,
                action="document.indexing.retried",
                resource_type="document",
                resource_id=str(document.id),
                details={"ingestion_status": ingestion_status},
            )
        return {
            "document": self._document_metadata(document),
            "ingestion_status": ingestion_status,
            "created": False,
        }

    async def get_document(
        self,
        identity: RequestIdentity,
        document_id: UUID,
    ) -> dict[str, Any]:
        access = await self._resolve_access(identity)
        document = await self._upload_service().get_document(access, document_id)
        return self._document_metadata(document)

    async def delete_document(
        self,
        identity: RequestIdentity,
        document_id: UUID,
    ) -> None:
        access = await self._resolve_access(identity)
        await self._document_pipeline().soft_delete_document(
            document_id,
            access=access,
        )

    async def get_knowledge_citation(
        self,
        identity: RequestIdentity,
        *,
        item_id: str,
        chunk_id: str,
    ) -> dict[str, Any]:
        async with session_scope(self._sessions()) as session:
            access = await resolve_auth_context(
                identity,
                session,
                allow_insecure_development_identity=(
                    self._allow_insecure_development_identity
                ),
            )
            item = await ItemService(session).get_item_by_canonical_id(
                item_id, access=access
            )
            assert access.tenant_id is not None
            collection_id = await CollectionAccessService(
                session
            ).authorization_collection_id(item.id, tenant_id=access.tenant_id)
            if collection_id is None:
                raise DocumentNotFoundError("citation not found")
            payloads = await self._qdrant_item_payloads(
                item_id=str(item.id),
                collection_item_id=str(collection_id),
                access=access,
                chunk_id=chunk_id,
                limit=1,
            )
            if not payloads:
                raise DocumentNotFoundError("citation not found")
            payload = payloads[0]
            citation = self._payload_citation(payload)
            return {
                "item_id": str(item.id),
                "chunk_id": str(payload.get("chunk_id") or chunk_id),
                "title": item.title,
                "content_type": item.mime_type or "text/plain",
                "document_url": self._presigned_document_url(item),
                "preview": self._preview_payload(item),
                "external_url": CitationResolver.original_url(
                    self._file_source(item), citation
                ),
                "citation": citation,
            }

    async def get_knowledge_item(
        self,
        identity: RequestIdentity,
        *,
        item_id: str,
        chunk_id: str | None,
    ) -> dict[str, Any]:
        async with session_scope(self._sessions()) as session:
            access = await resolve_auth_context(
                identity,
                session,
                allow_insecure_development_identity=(
                    self._allow_insecure_development_identity
                ),
            )
            item = await ItemService(session).get_item_by_canonical_id(
                item_id, access=access
            )
            assert access.tenant_id is not None
            collection_id = await CollectionAccessService(
                session
            ).authorization_collection_id(item.id, tenant_id=access.tenant_id)
            if collection_id is None:
                raise DocumentNotFoundError("item not found")
            payloads = await self._qdrant_item_payloads(
                item_id=str(item.id),
                collection_item_id=str(collection_id),
                access=access,
                chunk_id=chunk_id,
                limit=1 if chunk_id else 100,
            )
            elements, chunks_by_id = self._viewer_elements(str(item.id), payloads)
            focus = None
            if chunk_id:
                payload = chunks_by_id.get(chunk_id)
                if payload is None:
                    raise DocumentNotFoundError("citation not found")
                focus = {
                    "chunk_id": chunk_id,
                    "chunk_text": str(payload.get("chunk_text") or ""),
                    "citation": self._payload_citation(payload),
                }
            focus_citation = (
                self._payload_citation(chunks_by_id[chunk_id])
                if chunk_id in chunks_by_id
                else CitationInfo()
            )
            return {
                "item_id": str(item.id),
                "title": item.title,
                "content_type": item.mime_type or "text/plain",
                "external_url": CitationResolver.original_url(
                    self._file_source(item),
                    focus_citation,
                ),
                "document_url": (
                    self._presigned_document_url(item) if chunk_id else None
                ),
                "preview": self._preview_payload(item),
                "elements": elements,
                "focus": focus,
            }

    async def _qdrant_item_payloads(
        self,
        *,
        item_id: str,
        collection_item_id: str,
        access: AuthContext,
        chunk_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        if access.tenant_id is None:
            return []
        store = VectorStore(
            collection_name=os.getenv("QDRANT_COLLECTION"),
            url=os.getenv("QDRANT_URL"),
            api_key=os.getenv("QDRANT_API_KEY") or None,
            prefer_grpc=self._qdrant_prefer_grpc,
            timeout=20,
        )
        access_filter = store.build_access_filter(
            tenant_id=str(access.tenant_id),
            collection_item_ids={collection_item_id},
        )
        must = [
            *(access_filter.must or []),
            qmodels.FieldCondition(
                key="item_id", match=qmodels.MatchValue(value=item_id)
            ),
        ]
        if chunk_id:
            must.append(
                qmodels.FieldCondition(
                    key="chunk_id", match=qmodels.MatchValue(value=chunk_id)
                )
            )
        try:
            points, _ = await store.scroll_points(
                scroll_filter=qmodels.Filter(must=must),
                limit=limit,
                with_payload=True,
                with_vectors=False,
            )
        finally:
            await store.aclose()
        payloads = [
            dict(point.payload)
            for point in points
            if isinstance(getattr(point, "payload", None), Mapping)
        ]
        return sorted(payloads, key=lambda value: int(value.get("chunk_index") or 0))

    async def aclose(self) -> None:
        if self._pipeline is not None:
            await self._pipeline.aclose()
        if self._contextualization_transport is not None:
            await self._contextualization_transport.aclose()
        if self._agent is not None:
            close = getattr(self._agent.model, "aclose", None)
            if close is not None:
                await close()
        if self._storage is not None:
            await self._storage.aclose()

    async def _resolve_access(
        self,
        identity: RequestIdentity,
        *,
        user_id: str | UUID | None = None,
        tenant_id: str | UUID | None = None,
    ) -> AuthContext:
        async with session_scope(self._sessions()) as session:
            return await resolve_auth_context(
                identity,
                session,
                claimed_user_id=user_id,
                claimed_tenant_id=tenant_id,
                allow_insecure_development_identity=(
                    self._allow_insecure_development_identity
                ),
            )

    def _sessions(self) -> Any:
        if self._session_factory is None:
            self._session_factory = get_session_factory()
        return self._session_factory

    def _upload_service(self) -> UploadService:
        if self._uploads is None:
            self._uploads = UploadService(
                self._sessions(),
                object_storage=self._object_storage(),
                preview_service=self._preview_service(),
                max_upload_bytes=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_MAX_UPLOAD_BYTES",
                        str(DEFAULT_MAX_UPLOAD_BYTES),
                    )
                ),
                upload_url_seconds=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_UPLOAD_URL_SECONDS",
                        str(DEFAULT_UPLOAD_URL_SECONDS),
                    )
                ),
            )
        return self._uploads

    def _preview_service(self) -> KnowledgePreviewService:
        if self._previews is None:
            self._previews = KnowledgePreviewService(
                self._object_storage(),
                renderer=KnowledgePreviewRenderer(
                    max_pages=int(os.getenv("BOTHESIS_PREVIEW_MAX_PAGES", "50")),
                    max_dimension=int(
                        os.getenv("BOTHESIS_PREVIEW_MAX_DIMENSION", "1600")
                    ),
                    webp_quality=int(
                        os.getenv("BOTHESIS_PREVIEW_WEBP_QUALITY", "80")
                    ),
                ),
                max_source_bytes=int(
                    os.getenv(
                        "BOTHESIS_PREVIEW_MAX_SOURCE_BYTES",
                        str(DEFAULT_MAX_UPLOAD_BYTES),
                    )
                ),
            )
        return self._previews

    def _object_storage(self) -> Any:
        if self._storage_initialized:
            return self._storage
        provider = (os.getenv("BOTHESIS_OBJECT_STORAGE_PROVIDER") or "aws_s3").strip().lower()
        if provider == "aws_s3":
            bucket = (
                os.getenv("BOTHESIS_S3_BUCKET")
                or os.getenv("BOTHESIS_OBJECT_STORAGE_BUCKET")
                or ""
            ).strip()
            endpoint_url = (
                os.getenv("BOTHESIS_S3_ENDPOINT_URL")
                or os.getenv("BOTHESIS_OBJECT_STORAGE_ENDPOINT")
                or ""
            ).strip()
            if endpoint_url and not bucket:
                raise RuntimeError(
                    "BOTHESIS_S3_BUCKET is required when AWS S3 is configured"
                )
            if not bucket:
                raise RuntimeError("BOTHESIS_OBJECT_STORAGE_BUCKET is required")
            self._storage = S3DocumentStorage(
                    bucket=bucket,
                    region=(
                        os.getenv("BOTHESIS_S3_REGION")
                        or os.getenv("AWS_REGION")
                        or os.getenv("AWS_DEFAULT_REGION")
                        or None
                    ),
                    endpoint_url=endpoint_url or None,
                    addressing_style=(
                        os.getenv("BOTHESIS_S3_ADDRESSING_STYLE") or "auto"
                    ).strip(),
                    timeout_seconds=float(
                        os.getenv("BOTHESIS_S3_TIMEOUT_SECONDS", "20")
                    ),
                    max_pool_connections=int(
                        os.getenv("BOTHESIS_S3_MAX_POOL_CONNECTIONS", "20")
                    ),
                )
        elif provider == "cloudflare_r2":
            bucket = (
                os.getenv("BOTHESIS_R2_BUCKET")
                or os.getenv("BOTHESIS_OBJECT_STORAGE_BUCKET")
                or ""
            ).strip()
            account_id = (os.getenv("BOTHESIS_R2_ACCOUNT_ID") or "").strip()
            endpoint_url = (os.getenv("BOTHESIS_R2_ENDPOINT_URL") or "").strip()
            access_key_id = (os.getenv("BOTHESIS_R2_ACCESS_KEY_ID") or "").strip()
            secret_access_key = (
                os.getenv("BOTHESIS_R2_SECRET_ACCESS_KEY") or ""
            ).strip()
            if any((account_id, endpoint_url, access_key_id, secret_access_key)) and not bucket:
                raise RuntimeError(
                    "BOTHESIS_R2_BUCKET is required when Cloudflare R2 is configured"
                )
            if bucket and not (account_id or endpoint_url):
                raise RuntimeError(
                    "BOTHESIS_R2_ACCOUNT_ID or BOTHESIS_R2_ENDPOINT_URL is required"
                )
            if bucket and not (access_key_id and secret_access_key):
                raise RuntimeError(
                    "BOTHESIS_R2_ACCESS_KEY_ID and BOTHESIS_R2_SECRET_ACCESS_KEY are required"
                )
            if not bucket:
                raise RuntimeError("BOTHESIS_OBJECT_STORAGE_BUCKET is required")
            self._storage = S3DocumentStorage.for_cloudflare_r2(
                    bucket=bucket,
                    account_id=account_id or None,
                    endpoint_url=endpoint_url or None,
                    access_key_id=access_key_id or None,
                    secret_access_key=secret_access_key or None,
                    timeout_seconds=float(
                        os.getenv("BOTHESIS_R2_TIMEOUT_SECONDS", "20")
                    ),
                    max_pool_connections=int(
                        os.getenv("BOTHESIS_R2_MAX_POOL_CONNECTIONS", "20")
                    ),
                )
        else:
            raise RuntimeError(
                "BOTHESIS_OBJECT_STORAGE_PROVIDER must be aws_s3 or cloudflare_r2"
            )
        self._storage_initialized = True
        return self._storage

    def _document_pipeline(self) -> DocumentPipeline:
        if self._pipeline is None:
            base_url = os.getenv(
                "OPEN_ROUTER_BASE_URL",
                OpenRouterTransport.DEFAULT_BASE_URL,
            )
            embedder = OpenRouterTransport(base_url=base_url)
            semantic_contextualizer = None
            if self._contextualization_enabled:
                self._contextualization_transport = OpenRouterTransport(
                    base_url=base_url,
                    model=self._contextualization_model,
                )
                semantic_contextualizer = SemanticContextualizer(
                    self._contextualization_transport,
                    model_name=self._contextualization_model,
                )
            processing_max_bytes = int(
                os.getenv(
                    "BOTHESIS_DOCUMENT_MAX_PROCESSING_BYTES",
                    str(DEFAULT_PROCESSING_MAX_BYTES),
                )
            )
            self._pipeline = DocumentPipeline(
                self._sessions(),
                document_source=ChatDocumentSourceService(
                    object_storage=self._object_storage(),
                    processor=FileProcessor(max_file_bytes=processing_max_bytes),
                    max_processing_bytes=processing_max_bytes,
                ),
                embedder=embedder,
                vector_index=QdrantDocumentIndex(
                    VectorStore(
                        collection_name=os.getenv("QDRANT_COLLECTION"),
                        url=os.getenv("QDRANT_URL"),
                        api_key=os.getenv("QDRANT_API_KEY") or None,
                        prefer_grpc=self._qdrant_prefer_grpc,
                        timeout=20,
                    ),
                    candidate_limit=self._hybrid_candidate_limit,
                ),
                provider_cache=PostgresProviderFileCache(self._sessions()),
                direct_max_bytes=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_DIRECT_MAX_BYTES",
                        str(DEFAULT_DIRECT_MAX_BYTES),
                    )
                ),
                retrieval_limit=int(
                    os.getenv("BOTHESIS_DOCUMENT_RETRIEVAL_LIMIT", "6")
                ),
                embedding_batch_size=int(
                    os.getenv("BOTHESIS_DOCUMENT_EMBEDDING_BATCH_SIZE", "32")
                ),
                download_url_seconds=int(
                    os.getenv("BOTHESIS_DOCUMENT_DOWNLOAD_URL_SECONDS", "300")
                ),
                semantic_contextualizer=semantic_contextualizer,
            )
        return self._pipeline

    def _get_agent(self) -> Agent:
        if self._agent is None:
            registry = ToolRegistry()
            base_url = os.getenv(
                "OPEN_ROUTER_BASE_URL",
                OpenRouterTransport.DEFAULT_BASE_URL,
            )
            transport = OpenRouterTransport(base_url=base_url)
            retriever = DocumentIndexRetriever(
                QdrantSearchIndex(
                    VectorStore(
                        collection_name=os.getenv("QDRANT_COLLECTION"),
                        url=os.getenv("QDRANT_URL"),
                        api_key=os.getenv("QDRANT_API_KEY") or None,
                        prefer_grpc=self._qdrant_prefer_grpc,
                        timeout=8,
                    ),
                    transport,
                    candidate_limit=self._hybrid_candidate_limit,
                )
            )
            tracing = create_langfuse_tracing()
            registry.register(KnowledgeSearch(retriever, tracing=tracing))
            self._agent = Agent(
                model=transport,
                tools=registry,
                config=AgentConfig(
                    max_model_turns=int(os.getenv("BOTHESIS_MAX_MODEL_TURNS", "3")),
                    max_tool_rounds=int(os.getenv("BOTHESIS_MAX_TOOL_ROUNDS", "2")),
                    max_tool_calls=int(os.getenv("BOTHESIS_MAX_TOOL_CALLS", "6")),
                    max_history_messages=int(
                        os.getenv("BOTHESIS_MAX_HISTORY_MESSAGES", "24")
                    ),
                    max_history_characters=int(
                        os.getenv("BOTHESIS_MAX_HISTORY_CHARACTERS", "24000")
                    ),
                    recent_history_messages=int(
                        os.getenv("BOTHESIS_RECENT_HISTORY_MESSAGES", "6")
                    ),
                    tool_timeout_seconds=float(
                        os.getenv("BOTHESIS_TOOL_TIMEOUT_SECONDS", "8")
                    ),
                ),
                tracing=tracing,
            )
        return self._agent

    def _presigned_document_url(self, document: Any) -> str | None:
        if not document.storage_key:
            return None
        try:
            storage = self._object_storage()
            return storage.presign_download(
                document.storage_key,
                expires_seconds=max(
                    1,
                    min(
                        600,
                        int(
                            os.getenv(
                                "BOTHESIS_DOCUMENT_CITATION_URL_SECONDS", "300"
                            )
                        ),
                    ),
                ),
            ).url
        except Exception:
            log.exception("could not generate citation document URL")
            return None

    def _document_metadata(self, document: Any) -> dict[str, Any]:
        upload = document.upload
        processing = document.metadata_.get("processing")
        return {
            "id": str(document.id),
            "parent_item_id": (
                str(document.parent_item_id) if document.parent_item_id else None
            ),
            "file_name": str(
                document.metadata_.get("file_name")
                or document.title
                or "document"
            ),
            "content_type": document.mime_type or "application/octet-stream",
            "size_bytes": document.size_bytes or 0,
            "status": document.status,
            "indexed": isinstance(processing, Mapping)
            and processing.get("index_schema_version") is not None,
            "upload_status": upload.status if upload is not None else None,
            "created_at": document.created_at.isoformat(),
            "uploaded_at": (
                upload.uploaded_at.isoformat()
                if upload is not None and upload.uploaded_at
                else None
            ),
            "preview": self._preview_payload(document),
        }

    def _preview_payload(self, document: Any) -> dict[str, Any] | None:
        upload = getattr(document, "upload", None)
        if upload is not None and getattr(upload, "status", None) != "available":
            return None
        if getattr(document, "status", None) == "deleted":
            return None
        try:
            preview = self._preview_service().resolve(
                document,
                expires_seconds=max(
                    1,
                    min(
                        600,
                        int(os.getenv("BOTHESIS_PREVIEW_URL_SECONDS", "300")),
                    ),
                ),
            )
        except Exception:
            log.exception("could not resolve knowledge preview")
            return None
        return preview.model_dump(mode="json") if preview is not None else None

    @staticmethod
    def _target_payload(target: Any | None) -> dict[str, Any] | None:
        if target is None:
            return None
        request = target.request
        return {
            "mode": target.mode,
            "url": request.url,
            "method": request.method,
            "headers": dict(request.headers),
            "expires_at": request.expires_at.isoformat(),
        }

    @classmethod
    def _viewer_elements(
        cls,
        item_id: str,
        payloads: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        groups: dict[str, dict[str, Any] | None] = {}
        chunks_by_id: dict[str, dict[str, Any]] = {}
        for payload in payloads:
            chunk_index = int(payload.get("chunk_index") or 0)
            chunk_id = str(payload.get("chunk_id") or f"{item_id}:{chunk_index}")
            chunks_by_id[chunk_id] = payload
            chunks_by_id[f"{item_id}:{chunk_index}"] = payload
            cls._add_citation_content(
                groups,
                str(payload.get("chunk_text") or ""),
                cls._payload_citation(payload),
            )
        return [value for value in groups.values() if value is not None], chunks_by_id

    @staticmethod
    def _viewer_text(metadata: Mapping[str, Any], key: str) -> str | None:
        value = metadata.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _viewer_bbox(value: object) -> BoundingBox | None:
        if not isinstance(value, Mapping):
            return None
        try:
            return BoundingBox.model_validate(value)
        except ValueError:
            return None

    @staticmethod
    def _payload_text(payload: Mapping[str, Any], key: str) -> str | None:
        value = payload.get(key)
        return value.strip() if isinstance(value, str) and value.strip() else None

    @staticmethod
    def _payload_int(payload: Mapping[str, Any], key: str) -> int | None:
        value = payload.get(key)
        if isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.strip().isdigit():
            return int(value)
        return None

    @classmethod
    def _payload_citation(cls, payload: Mapping[str, Any]) -> CitationInfo:
        spans = cls._citation_spans(payload.get("citation_spans"))
        raw_section_path = payload.get("citation_section_path")
        section_path = tuple(
            value.strip()
            for value in raw_section_path or ()
            if isinstance(value, str) and value.strip()
        )
        return CitationInfo(
            section=(
                cls._viewer_text(payload, "citation_section")
                or (section_path[-1] if section_path else None)
            ),
            section_path=section_path,
            anchor=cls._viewer_text(payload, "citation_anchor"),
            spans=tuple(spans),
        )

    @classmethod
    def _citation_spans(cls, value: object) -> list[CitationSpan]:
        if not isinstance(value, (list, tuple)):
            return []
        output: list[CitationSpan] = []
        for raw in value:
            if not isinstance(raw, Mapping):
                continue
            try:
                output.append(
                    CitationSpan(
                        page=cls._payload_int(raw, "page"),
                        element_id=cls._payload_text(raw, "element_id"),
                        start_offset=cls._payload_int(raw, "start_offset"),
                        end_offset=cls._payload_int(raw, "end_offset"),
                        bounding_box=cls._viewer_bbox(raw.get("bounding_box")),
                    )
                )
            except ValueError:
                continue
        return output

    @staticmethod
    def _add_citation_content(
        groups: dict[str, dict[str, Any] | None],
        content: str,
        citation: CitationInfo,
    ) -> None:
        if not content or len(citation.spans) != 1:
            return
        span = citation.spans[0]
        if (
            span.element_id is None
            or span.start_offset != 0
            or span.end_offset != len(content)
        ):
            return
        candidate = {
            "element_id": span.element_id,
            "text": content,
            "page": span.page,
            "section": citation.section,
            "section_path": list(citation.section_path),
            "anchor": citation.anchor,
            "bounding_box": span.bounding_box,
        }
        if span.element_id not in groups:
            groups[span.element_id] = candidate
        elif groups[span.element_id] != candidate:
            groups[span.element_id] = None

    @staticmethod
    def _file_source(document: Any) -> SourceIdentity:
        metadata = getattr(document, "metadata_", None)
        if isinstance(metadata, Mapping):
            canonical = metadata.get("canonical_item")
            source_value = (
                canonical.get("source")
                if isinstance(canonical, Mapping)
                else metadata.get("source")
            )
            if isinstance(source_value, Mapping):
                try:
                    return SourceIdentity.model_validate(source_value)
                except ValueError:
                    pass
        return SourceIdentity(
            connector_id="upload",
            provider=SourceProvider.FILE,
            external_id=str(document.id),
            url=None,
        )


__all__ = ["ApiService"]
