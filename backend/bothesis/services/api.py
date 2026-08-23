"""Application orchestration used by the FastAPI boundary."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterable, AsyncIterator, Awaitable, Callable, Mapping
from typing import Any, Literal
from uuid import UUID, uuid4

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
from bothesis.document_index.indexer import (
    DEFAULT_DIRECT_MAX_BYTES,
    DEFAULT_PROCESSING_MAX_BYTES,
    DocumentPipeline,
)
from bothesis.document_index.openrouter_embedding import OpenRouterEmbeddingService
from bothesis.document_index.raw_storage import S3DocumentStorage
from bothesis.document_index.search import QdrantSearchIndex
from bothesis.document_index.vector_store import QdrantDocumentIndex, VectorStore
from bothesis.knowledge import CitationResolver
from bothesis.knowledge.retriever import DocumentIndexRetriever
from bothesis.observability import create_langfuse_tracing
from bothesis.services import (
    DEFAULT_MAX_DATABASE_BLOB_BYTES,
    DEFAULT_MAX_UPLOAD_BYTES,
    DEFAULT_UPLOAD_URL_SECONDS,
    KNOWLEDGE_READ_PERMISSION,
    AuthContext,
    ChatDocumentSourceService,
    DatasourceService,
    DocumentNotFoundError,
    DocumentService,
    RequestIdentity,
    UploadService,
    UploadTooLargeError,
    UploadValidationError,
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
    ) -> None:
        self._allow_insecure_development_identity = (
            allow_insecure_development_identity
        )
        self._qdrant_prefer_grpc = qdrant_prefer_grpc
        self._session_factory: Any | None = None
        self._storage: Any | None = None
        self._storage_initialized = False
        self._uploads: UploadService | None = None
        self._pipeline: DocumentPipeline | None = None
        self._agent: Agent | None = None

    async def start_attachment_upload(
        self,
        identity: RequestIdentity,
        *,
        tenant_id: UUID,
        user_id: UUID,
        idempotency_key: str,
        file_name: str,
        content_type: str,
        size_bytes: int,
        base_url: str,
    ) -> dict[str, Any]:
        access = await self._resolve_access(
            identity,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        result = await self._upload_service().start_upload(
            access,
            idempotency_key=idempotency_key,
            file_name=file_name,
            content_type=content_type,
            size_bytes=size_bytes,
        )
        target = self._target_payload(result.target)
        if target and target["mode"] == "api" and str(target["url"]).startswith("/"):
            target["url"] = (
                f"{base_url.rstrip('/')}{target['url']}"
                f"?tenant_id={tenant_id}&user_id={user_id}"
            )
        metadata = self._document_metadata(result.document)
        return {
            "upload_id": str(result.document.id),
            "upload_required": result.upload_required,
            "upload": target,
            "attachment": self._legacy_document_metadata(metadata),
        }

    async def complete_attachment_upload(
        self,
        identity: RequestIdentity,
        *,
        upload_id: UUID,
        tenant_id: UUID,
        user_id: UUID,
    ) -> dict[str, Any]:
        access = await self._resolve_access(
            identity,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        document = await self._upload_service().complete_upload(access, upload_id)
        return self._legacy_document_metadata(self._document_metadata(document))

    async def release_attachment(
        self,
        identity: RequestIdentity,
        *,
        attachment_id: UUID,
        tenant_id: str,
        user_id: str,
    ) -> None:
        access = await self._resolve_access(
            identity,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        await self._document_pipeline().soft_delete_document(
            attachment_id,
            access=access,
        )

    async def chat_events(
        self,
        identity: RequestIdentity,
        *,
        message: str,
        tenant_id: str | None,
        user_id: str | None,
        conversation_id: UUID | None,
        history: list[tuple[Literal["user", "assistant"], str]],
        connector_mode: Literal["auto", "selected", "off"],
        connector_ids: list[int],
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[str]:
        access = await self._resolve_access(
            identity,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        selected_connector_ids: tuple[int, ...] | None = None
        allowed_tool_names: tuple[str, ...] | None = (
            () if connector_mode == "off" else None
        )
        if connector_mode == "selected":
            async with session_scope(self._sessions()) as session:
                authorized = await DatasourceService(session).list_chat_connectors(
                    access,
                    connector_ids=connector_ids,
                )
            selected_connector_ids = tuple(
                int(item["id"]) for item in authorized["items"]
            )
            allowed_tool_names = tuple(
                sorted(
                    {
                        capability
                        for item in authorized["items"]
                        for capability in item["capabilities"]
                    }
                )
            )
        if access.tenant_id is None:
            raise PermissionError("an active tenant membership is required for chat")
        resolved_conversation_id = conversation_id or uuid4()
        context = AgentContext(
            user_id=str(access.user_id),
            tenant_id=str(access.tenant_id),
            roles=[access.role_code] if access.role_code else [],
            reader_ids=tuple(
                sorted(
                    {
                        f"email:{access.email.strip().lower()}",
                        *(
                            token.strip().lower()
                            for token in access.principal_tokens
                            if token.strip()
                        ),
                    }
                )
            ),
            is_admin=access.is_admin,
            conversation_id=str(resolved_conversation_id),
            request_id=uuid4().hex,
            history=tuple(
                ConversationMessage(role=role, content=content)
                for role, content in history
            ),
            connector_ids=selected_connector_ids,
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

    async def list_chat_connectors(
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
            return await DatasourceService(session).list_chat_connectors(access)

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
            "document": self._document_metadata(result.document),
        }

    async def store_document_content(
        self,
        identity: RequestIdentity,
        *,
        document_id: UUID,
        content_type: str,
        content: AsyncIterable[bytes],
        tenant_id: str | None = None,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        access = await self._resolve_access(
            identity,
            user_id=user_id,
            tenant_id=tenant_id,
        )
        uploads = self._upload_service()
        document = await uploads.get_document(access, document_id)
        request_type = content_type.split(";", 1)[0].casefold()
        if request_type and request_type != (document.mime_type or "").casefold():
            raise UploadValidationError(
                "uploaded content type does not match document metadata"
            )
        stored_content = bytearray()
        async for chunk in content:
            if len(stored_content) + len(chunk) > uploads.max_database_blob_bytes:
                raise UploadTooLargeError(
                    "API upload exceeds the PostgreSQL fallback limit"
                )
            stored_content.extend(chunk)
        stored = await uploads.store_fallback_content(
            access,
            document_id,
            bytes(stored_content),
        )
        return self._document_metadata(stored)

    async def complete_document_upload(
        self,
        identity: RequestIdentity,
        document_id: UUID,
    ) -> dict[str, Any]:
        access = await self._resolve_access(identity)
        document = await self._upload_service().complete_upload(access, document_id)
        return self._document_metadata(document)

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
            document, record = await DocumentService(
                session
            ).get_document_and_chunk_by_item_id(
                item_id,
                chunk_id,
                access=access,
            )
            if record is None:
                raise DocumentNotFoundError("citation not found")
            citation = self._record_citation(record)
            return {
                "item_id": item_id,
                "chunk_id": chunk_id,
                "title": document.title or str(document.id),
                "content_type": document.mime_type or "text/plain",
                "document_url": self._presigned_document_url(document),
                "external_url": CitationResolver.original_url(
                    self._file_source(document), citation
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
            documents = DocumentService(session)
            if chunk_id:
                document, targeted_chunk = (
                    await documents.get_document_and_chunk_by_item_id(
                        item_id,
                        chunk_id,
                        access=access,
                    )
                )
            else:
                document = await documents.get_document_by_item_id(
                    item_id,
                    access=access,
                )
                targeted_chunk = None
            if targeted_chunk is not None:
                records = [targeted_chunk]
            elif chunk_id is None:
                records = await documents.get_chunks(
                    document.id,
                    access=access,
                    limit=100,
                )
            else:
                records = []
            elements, chunks_by_id = self._viewer_elements(document, records)
            focus = None
            if chunk_id:
                record = chunks_by_id.get(chunk_id)
                if record is None:
                    raise DocumentNotFoundError("citation not found")
                focus = {
                    "chunk_id": chunk_id,
                    "chunk_text": record.content,
                    "citation": self._record_citation(record),
                }
            focus_citation = (
                self._record_citation(chunks_by_id[chunk_id])
                if chunk_id in chunks_by_id
                else CitationInfo()
            )
            return {
                "item_id": item_id,
                "title": document.title or str(document.id),
                "content_type": document.mime_type or "text/plain",
                "external_url": CitationResolver.original_url(
                    self._file_source(document),
                    focus_citation,
                ),
                "document_url": (
                    self._presigned_document_url(document) if chunk_id else None
                ),
                "elements": elements,
                "focus": focus,
            }

    async def aclose(self) -> None:
        if self._pipeline is not None:
            await self._pipeline.aclose()
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
                max_upload_bytes=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_MAX_UPLOAD_BYTES",
                        str(DEFAULT_MAX_UPLOAD_BYTES),
                    )
                ),
                max_database_blob_bytes=int(
                    os.getenv(
                        "BOTHESIS_DOCUMENT_MAX_DATABASE_BLOB_BYTES",
                        str(DEFAULT_MAX_DATABASE_BLOB_BYTES),
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

    def _object_storage(self) -> Any | None:
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
            self._storage = (
                S3DocumentStorage(
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
                if bucket
                else None
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
            self._storage = (
                S3DocumentStorage.for_cloudflare_r2(
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
                if bucket
                else None
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
            embedder = OpenRouterEmbeddingService(base_url=base_url)
            processing_max_bytes = int(
                os.getenv(
                    "BOTHESIS_DOCUMENT_MAX_PROCESSING_BYTES",
                    str(DEFAULT_PROCESSING_MAX_BYTES),
                )
            )
            self._pipeline = DocumentPipeline(
                self._sessions(),
                document_source=ChatDocumentSourceService(
                    self._sessions(),
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
                    )
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
            )
        return self._pipeline

    def _get_agent(self) -> Agent:
        if self._agent is None:
            registry = ToolRegistry()
            base_url = os.getenv(
                "OPEN_ROUTER_BASE_URL",
                OpenRouterTransport.DEFAULT_BASE_URL,
            )
            retriever = DocumentIndexRetriever(
                QdrantSearchIndex(
                    VectorStore(
                        collection_name=os.getenv("QDRANT_COLLECTION"),
                        url=os.getenv("QDRANT_URL"),
                        api_key=os.getenv("QDRANT_API_KEY") or None,
                        prefer_grpc=self._qdrant_prefer_grpc,
                        timeout=8,
                    ),
                    OpenRouterEmbeddingService(base_url=base_url),
                )
            )
            tracing = create_langfuse_tracing()
            registry.register(KnowledgeSearch(retriever, tracing=tracing))
            self._agent = Agent(
                model=OpenRouterTransport(base_url=base_url),
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
        if not document.raw_storage_key:
            return None
        try:
            storage = self._object_storage()
            if storage is None:
                return None
            return storage.presign_download(
                document.raw_storage_key,
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

    @staticmethod
    def _document_metadata(document: Any) -> dict[str, Any]:
        return {
            "id": str(document.id),
            "file_name": str(
                document.metadata_.get("file_name")
                or document.title
                or "document"
            ),
            "content_type": document.mime_type or "application/octet-stream",
            "size_bytes": document.size_bytes or 0,
            "upload_status": document.upload_status,
            "indexing_status": document.indexing_status,
            "created_at": document.created_at.isoformat(),
            "uploaded_at": (
                document.uploaded_at.isoformat() if document.uploaded_at else None
            ),
        }

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

    @staticmethod
    def _legacy_document_metadata(document: Mapping[str, Any]) -> dict[str, Any]:
        direct = document["content_type"] in {
            "image/png",
            "image/jpeg",
            "image/webp",
            "image/gif",
            "application/pdf",
        }
        return {
            "id": document["id"],
            "file_name": document["file_name"],
            "content_type": document["content_type"],
            "size_bytes": document["size_bytes"],
            "mode": "direct" if direct else "indexed",
            "status": document["upload_status"],
            "created_at": document["created_at"],
        }

    @classmethod
    def _viewer_elements(
        cls,
        document: Any,
        records: list[Any],
    ) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        groups: dict[str, dict[str, Any] | None] = {}
        chunks_by_id: dict[str, Any] = {}
        item_id = str(document.id)
        for record in sorted(records, key=lambda value: value.chunk_index):
            chunk_id = (
                cls._viewer_text(record.metadata_, "chunk_id")
                or f"{item_id}:{record.chunk_index}"
            )
            chunks_by_id[chunk_id] = record
            chunks_by_id[f"{item_id}:{record.chunk_index}"] = record
            chunks_by_id[str(record.id)] = record
            cls._add_citation_content(
                groups,
                record.content,
                cls._record_citation(record),
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
    def _record_citation(cls, record: Any) -> CitationInfo:
        metadata = dict(record.metadata_)
        spans = cls._citation_spans(metadata.get("citation_spans"))
        raw_section_path = metadata.get("citation_section_path")
        if isinstance(raw_section_path, (list, tuple)):
            section_path = tuple(
                value.strip()
                for value in raw_section_path
                if isinstance(value, str) and value.strip()
            )
        else:
            section_path = tuple(record.heading_path or ())
        return CitationInfo(
            section=(
                cls._viewer_text(metadata, "citation_section")
                or (section_path[-1] if section_path else None)
            ),
            section_path=section_path,
            anchor=cls._viewer_text(metadata, "citation_anchor"),
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
            url=document.source_url,
        )


__all__ = ["ApiService"]
