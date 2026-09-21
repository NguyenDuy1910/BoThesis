"""Composition root: build long-lived collaborators from one configuration.

The HTTP layer never constructs infrastructure. It asks this runtime for a
service, and the runtime owns the lazily created, process-wide clients those
services share (object storage, vector index, model transports, the agent).
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from config import AppConfig, get_config

from bothesis.agent import Agent, SessionConfiguration
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearch
from bothesis.agent.tools.inspect_resource import InspectResource
from bothesis.agent.tools.materialize_resource import MaterializeResource
from bothesis.agent.tools.materialize_sandbox_resource import MaterializeSandboxResource
from bothesis.agent.tools.read_resource import ReadResource
from bothesis.agent.tools.export_sandbox_file import ExportSandboxFile
from bothesis.agent.tools.request_identity import RequestIdentity
from bothesis.agent.transports.openai import OpenAITransport
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.agent.transports.openrouter_execution_capability import (
    OpenRouterExecutionCapabilityResolver,
)
from bothesis.connector.file import FileProcessor
from bothesis.db.engine import LazySessionFactory, SessionFactory
from bothesis.document_index import ItemIndex, SemanticContextualizer
from bothesis.health import HealthService, HealthSettings
from bothesis.knowledge import ItemKnowledgeRetriever, SemanticReranker
from bothesis.observability import create_tracer
from bothesis.integrations.atlassian import AtlassianConnectionProvider
from bothesis.integrations.google import GoogleConnectionProvider
from bothesis.integrations.oauth_state import OAuthStateCodec
from bothesis.integrations.registry import ConnectionProviderRegistry
from bothesis.services.workspace_control_plane import WorkspaceControlPlaneService
from bothesis.services.integration_authorization import (
    IntegrationAuthorizationService,
)
from bothesis.services.integration_lifecycle import IntegrationLifecycleService
from bothesis.services.identity_access.auth import AuthenticationService
from bothesis.services.identity_access.google import GoogleIdentityVerifier
from bothesis.services.artifact import ArtifactService
from bothesis.services import AuthContext
from bothesis.services.chat import ChatService
from bothesis.services.conversation import ConversationService
from bothesis.services.document_presentation import DocumentPresenter
from bothesis.services.document_upload import DocumentUploadService
from bothesis.services.item_ingestion import ItemIngestionService
from bothesis.services.knowledge_query import KnowledgeQueryService
from bothesis.services.knowledge_view import KnowledgeViewService
from bothesis.services.preview import KnowledgePreview
from bothesis.services.agent_runtime.item_resource_resolver import ItemResourceResolver
from bothesis.services.agent_runtime.sandbox_workspace import SandboxWorkspace
from bothesis.services.sandbox_session import SandboxSessionService
from bothesis.services.stored_file_content import StoredFileContentService
from bothesis.services.workflow.service import TemporalWorkflowService
from bothesis.services.workspace_documents import WorkspaceDocumentService
from bothesis.services.identity_access.jwt_tokens import JwtTokenService
from bothesis.storage import S3DocumentStorage


class AppRuntime:
    """Own every shared client and hand out ready-to-use services."""

    def __init__(self, config: AppConfig | None = None) -> None:
        self._config = config or get_config()
        self._session_factory: SessionFactory | None = None
        self._storage: Any | None = None
        self._index: ItemIndex | None = None
        self._preview: KnowledgePreview | None = None
        self._presenter: DocumentPresenter | None = None
        self._workflows: TemporalWorkflowService | None = None
        self._ingestion: ItemIngestionService | None = None
        self._uploads: DocumentUploadService | None = None
        self._conversations: ConversationService | None = None
        self._artifacts: ArtifactService | None = None
        self._agent: Agent | None = None
        self._stored_file_content: StoredFileContentService | None = None
        self._sandbox_sessions: SandboxSessionService | None = None
        self._retriever: ItemKnowledgeRetriever | None = None
        self._model_transport: OpenRouterTransport | None = None
        self._agent_transport: OpenAITransport | OpenRouterTransport | None = None
        self._contextualization_transport: OpenRouterTransport | None = None
        self._jwt_tokens: JwtTokenService | None = None
        self._google_identity: GoogleIdentityVerifier | None = None
        self._connection_providers: ConnectionProviderRegistry | None = None

    @property
    def config(self) -> AppConfig:
        return self._config

    # -- Services -----------------------------------------------------------

    def chat_service(self) -> ChatService:
        return ChatService(
            self.sessions(),
            agent=self.agent(),
            conversations=self.conversation_service(),
            resource_resolver=lambda access: ItemResourceResolver(
                self.sessions(),
                access=access,
                content=self.stored_file_content(),
                max_read_characters=self._config.agent.max_resource_read_characters,
            ),
            sandbox_runtime=self._sandbox_workspace,
        )

    def knowledge_query_service(self) -> KnowledgeQueryService:
        return KnowledgeQueryService(
            self.sessions(),
            retriever=self.knowledge_retriever(),
        )

    def knowledge_view_service(self) -> KnowledgeViewService:
        return KnowledgeViewService(
            self.sessions(),
            index=self.item_index(),
            presenter=self.document_presenter(),
        )

    def workspace_document_service(self) -> WorkspaceDocumentService:
        return WorkspaceDocumentService(
            self.sessions(),
            uploads=self.upload_service(),
            presenter=self.document_presenter(),
        )

    def workspace_control_plane_service(self) -> WorkspaceControlPlaneService:
        return WorkspaceControlPlaneService(
            self.sessions(),
            vector_index=self._config.vector_index,
        )

    def integration_lifecycle_service(self) -> IntegrationLifecycleService:
        return IntegrationLifecycleService(
            self.sessions(),
            workflows=self.workflow_service(),
            integration=self._config.integration,
            providers=self.connection_providers(),
            authorization=self.integration_authorization_service(),
        )

    def integration_authorization_service(self) -> IntegrationAuthorizationService:
        oauth = self._config.integration.oauth
        return IntegrationAuthorizationService(
            self.connection_providers(),
            state=OAuthStateCodec(oauth.state_secret),
            client_origin=oauth.client_origin,
        )

    def connection_providers(self) -> ConnectionProviderRegistry:
        """Register only the providers this deployment actually configured.

        An unconfigured provider is still registered: the catalogue has to be
        able to say a connector exists but cannot be connected here, which is a
        different answer from the connector not existing at all.
        """

        if self._connection_providers is None:
            oauth = self._config.integration.oauth
            self._connection_providers = ConnectionProviderRegistry(
                (
                    GoogleConnectionProvider(
                        client_id=oauth.google.client_id,
                        client_secret=oauth.google.client_secret,
                        redirect_uri=oauth.redirect_uri,
                        timeout_seconds=oauth.timeout_seconds,
                    ),
                    AtlassianConnectionProvider(
                        client_id=oauth.atlassian.client_id,
                        client_secret=oauth.atlassian.client_secret,
                        redirect_uri=oauth.redirect_uri,
                        timeout_seconds=oauth.timeout_seconds,
                    ),
                )
            )
        return self._connection_providers

    def health_service(self) -> HealthService:
        model = self._config.model
        index = self._config.vector_index
        observability = self._config.observability
        return HealthService(
            HealthSettings(
                qdrant_url=index.url,
                qdrant_api_key=index.api_key,
                qdrant_collection=index.collection,
                openai_base_url=model.openai_base_url,
                openai_api_key=model.openai_api_key,
                openrouter_base_url=model.openrouter_base_url,
                openrouter_api_key=model.openrouter_api_key,
                chat_model=model.chat_model,
                embedding_model=model.embedding_model,
                langfuse_base_url=observability.langfuse_base_url,
                langfuse_public_key=observability.langfuse_public_key,
                langfuse_secret_key=observability.langfuse_secret_key,
            )
        )

    def authentication_service(self, session: AsyncSession) -> AuthenticationService:
        """Build a request-scoped authentication workflow from durable identity state."""

        return AuthenticationService(
            session,
            tokens=self.jwt_token_service(),
            platform_admin_emails=self._config.identity.platform_admin_emails,
            public_tenant_code=self._config.identity.public_tenant_code,
            guest_session_expires_in_seconds=(
                self._config.identity.guest_session_expires_in_seconds
            ),
        )

    # -- Shared collaborators ----------------------------------------------

    def sessions(self) -> SessionFactory:
        if self._session_factory is None:
            self._session_factory = LazySessionFactory()
        return self._session_factory

    def jwt_token_service(self) -> JwtTokenService:
        if self._jwt_tokens is None:
            identity = self._config.identity
            self._jwt_tokens = JwtTokenService(
                secret=identity.jwt_secret,
                issuer=identity.jwt_issuer,
                audience=identity.jwt_audience,
                expires_in_seconds=identity.jwt_expires_in_seconds,
            )
        return self._jwt_tokens

    def google_identity_verifier(self) -> GoogleIdentityVerifier:
        if self._google_identity is None:
            identity = self._config.identity
            self._google_identity = GoogleIdentityVerifier(
                client_id=identity.google_client_id,
                jwks_url=identity.google_jwks_url,
            )
        return self._google_identity

    def document_presenter(self) -> DocumentPresenter:
        if self._presenter is None:
            self._presenter = DocumentPresenter(
                object_storage=self.object_storage,
                preview=self.knowledge_preview(),
                citation_url_seconds=self._config.upload.citation_url_seconds,
                preview_url_seconds=self._config.preview.url_seconds,
            )
        return self._presenter

    def workflow_service(self) -> TemporalWorkflowService:
        if self._workflows is None:
            self._workflows = TemporalWorkflowService()
        return self._workflows

    def conversation_service(self) -> ConversationService:
        if self._conversations is None:
            self._conversations = ConversationService(self.sessions())
        return self._conversations

    def artifact_service(self) -> ArtifactService:
        if self._artifacts is None:
            artifact = self._config.artifact
            # Storage and uploads are resolved lazily: the agent is composed
            # at startup, while object storage is only required by a request.
            self._artifacts = ArtifactService(
                self.sessions(),
                object_storage=self.object_storage,
                uploads=self.upload_service,
                max_content_bytes=artifact.max_content_bytes,
                download_url_seconds=artifact.download_url_seconds,
            )
        return self._artifacts

    def sandbox_session_service(self) -> SandboxSessionService:
        if self._sandbox_sessions is None:
            self._sandbox_sessions = SandboxSessionService(self.sessions())
        return self._sandbox_sessions

    def object_storage(self) -> Any:
        if self._storage is None:
            self._storage = self._build_object_storage()
        return self._storage

    def item_index(self) -> ItemIndex:
        if self._index is None:
            index = self._config.vector_index
            contextualizer = None
            if self._config.model.contextualization_enabled:
                self._contextualization_transport = OpenRouterTransport(
                    base_url=self._config.model.openrouter_base_url,
                    model=self._config.model.contextualization_model,
                )
                contextualizer = SemanticContextualizer(
                    self._contextualization_transport,
                    model_name=self._config.model.contextualization_model,
                )
            self._index = ItemIndex(
                embedder=OpenRouterTransport(
                    base_url=self._config.model.openrouter_base_url
                ),
                collection_name=index.collection,
                url=index.url,
                api_key=index.api_key,
                prefer_grpc=index.prefer_grpc,
                timeout=index.timeout_seconds,
                embedding_batch_size=index.embedding_batch_size,
                semantic_contextualizer=contextualizer,
                candidate_limit=self._config.retrieval.hybrid_candidate_limit,
            )
        return self._index

    def knowledge_preview(self) -> KnowledgePreview:
        if self._preview is None:
            preview = self._config.preview
            self._preview = KnowledgePreview(
                self.object_storage(),
                max_source_bytes=preview.max_source_bytes,
                max_pages=preview.max_pages,
                max_dimension=preview.max_dimension,
                webp_quality=preview.webp_quality,
            )
        return self._preview

    def ingestion_service(self) -> ItemIngestionService:
        if self._ingestion is None:
            self._ingestion = ItemIngestionService(
                self.sessions(),
                index=self.item_index(),
                preview=self.knowledge_preview(),
            )
        return self._ingestion

    def upload_service(self) -> DocumentUploadService:
        if self._uploads is None:
            upload = self._config.upload
            self._uploads = DocumentUploadService(
                self.sessions(),
                object_storage=self.object_storage(),
                ingestion_service=self.ingestion_service(),
                document_source=self.stored_file_content(),
                workflows=self.workflow_service(),
                max_upload_bytes=upload.max_upload_bytes,
                upload_url_seconds=upload.upload_url_seconds,
            )
        return self._uploads

    def stored_file_content(self) -> StoredFileContentService:
        """The lazy source adapter used by explicit resource reads and ingestion."""

        if self._stored_file_content is None:
            upload = self._config.upload
            self._stored_file_content = StoredFileContentService(
                object_storage=self.object_storage(),
                processor=FileProcessor(max_file_bytes=upload.processing_max_bytes),
                max_processing_bytes=upload.processing_max_bytes,
            )
        return self._stored_file_content

    def model_transport(self) -> OpenRouterTransport:
        """The transport the retrieval-side models (reranking) run on."""

        if self._model_transport is None:
            self._model_transport = OpenRouterTransport(
                base_url=self._config.model.openrouter_base_url
            )
        return self._model_transport

    def agent_transport(self) -> OpenAITransport | OpenRouterTransport:
        """The transport the conversation agent runs on.

        The selected provider owns any native model capabilities. The agent
        loop stays provider-neutral; OpenRouter's hosted shell is enabled only
        when both its provider selection and the execution policy allow it.
        """

        if self._agent_transport is None:
            model = self._config.model
            if model.agent_provider == "openrouter":
                self._agent_transport = OpenRouterTransport(
                    api_key=model.openrouter_api_key,
                    base_url=model.openrouter_base_url,
                    model=model.chat_model,
                    embedding_model=model.embedding_model,
                )
            else:
                self._agent_transport = OpenAITransport(
                    api_key=model.openai_api_key,
                    base_url=model.openai_base_url,
                    model=model.chat_model,
                    embedding_model=model.embedding_model,
                )
        return self._agent_transport

    def knowledge_retriever(self) -> ItemKnowledgeRetriever:
        if self._retriever is None:
            retrieval = self._config.retrieval
            reranker = (
                SemanticReranker(
                    self.model_transport(),
                    model_name=self._config.model.reranker_model,
                )
                if retrieval.reranking_enabled
                else None
            )
            self._retriever = ItemKnowledgeRetriever(
                self.item_index(),
                reranker=reranker,
                candidate_count=retrieval.hybrid_candidate_limit,
                reranking_enabled=retrieval.reranking_enabled,
            )
        return self._retriever

    def agent(self) -> Agent:
        if self._agent is None:
            retrieval = self._config.retrieval
            agent = self._config.agent
            tracer = create_tracer(
                self._config.observability.langfuse_public_key,
                self._config.observability.langfuse_secret_key,
            )
            registry = ToolRegistry()
            registry.register(
                KnowledgeSearch(
                    self.knowledge_retriever(),
                    result_limit=retrieval.final_top_k,
                    max_context_characters=retrieval.context_characters,
                    tracer=tracer,
                )
            )
            registry.register(RequestIdentity())
            registry.register(InspectResource())
            registry.register(
                ReadResource(max_characters=agent.max_resource_read_characters)
            )
            registry.register(MaterializeResource())
            if isinstance(self.agent_transport(), OpenRouterTransport):
                registry.register(MaterializeSandboxResource())
                registry.register(ExportSandboxFile())
            self._agent = Agent(
                model=self.agent_transport(),
                tools=registry,
                configuration=SessionConfiguration(
                    max_model_turns=agent.max_model_turns,
                    max_tool_rounds=agent.max_tool_rounds,
                    max_tool_calls=agent.max_tool_calls,
                    max_history_messages=agent.max_history_messages,
                    max_history_characters=agent.max_history_characters,
                    recent_history_messages=agent.recent_history_messages,
                    tool_timeout_seconds=agent.tool_timeout_seconds,
                ),
                tracer=tracer,
                execution_capability_resolver=OpenRouterExecutionCapabilityResolver(),
            )
        return self._agent

    def _sandbox_workspace(
        self, access: AuthContext, conversation_id: UUID, request_id: str
    ) -> SandboxWorkspace | None:
        """Build a request-scoped workspace only for the selected provider."""

        transport = self.agent().model
        if not isinstance(transport, OpenRouterTransport):
            return None
        return SandboxWorkspace(
            access=access,
            conversation_id=conversation_id,
            request_id=request_id,
            provider=transport,
            sessions=self.sandbox_session_service(),
            artifacts=self.artifact_service(),
        )

    async def aclose(self) -> None:
        """Release every client this runtime opened."""

        if self._index is not None:
            await self._index.aclose()
        for transport in (
            self._contextualization_transport,
            self._model_transport,
            self._agent_transport,
        ):
            close = getattr(transport, "aclose", None)
            if close is not None:
                await close()
        if self._storage is not None:
            await self._storage.aclose()

    # -- Internals ----------------------------------------------------------

    def _build_object_storage(self) -> Any:
        storage = self._config.object_storage
        bucket = storage.require_bucket()
        if storage.uses_cloudflare_r2:
            return S3DocumentStorage.for_cloudflare_r2(
                bucket=bucket,
                account_id=storage.account_id,
                endpoint_url=storage.endpoint_url,
                access_key_id=storage.access_key_id,
                secret_access_key=storage.secret_access_key,
                timeout_seconds=storage.timeout_seconds,
                max_pool_connections=storage.max_pool_connections,
            )
        return S3DocumentStorage(
            bucket=bucket,
            region=storage.region,
            endpoint_url=storage.endpoint_url,
            addressing_style=storage.addressing_style,
            timeout_seconds=storage.timeout_seconds,
            max_pool_connections=storage.max_pool_connections,
        )


__all__ = ["AppRuntime"]
