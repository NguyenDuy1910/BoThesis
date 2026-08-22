from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import AgentContext, ToolContext
from bothesis.agent.protocol import FunctionTool
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
from bothesis.knowledge.document_index import (
    QdrantKeywordRetriever,
    QdrantSemanticRetriever,
    ScopedKnowledgeRetriever,
)
from bothesis.knowledge import CitationResolver
from bothesis.knowledge.protocol import (
    CitationInfo,
    CitationSpan,
    ChunkContext,
    ContextualChunk,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)

CONTEXT = AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[])
TOOL_CONTEXT = ToolContext(agent_context=CONTEXT)
def _chunk(*, score: float = 0.91) -> ContextualChunk:
    return ContextualChunk(
        id="chunk-1",
        item_id="doc-1",
        chunk_index=0,
        content_type="text",
        chunk_text="Employees receive 20 days of annual leave.",
        contextual_text=(
            "Document: Leave policy\nSection: Annual leave\n\n"
            "Employees receive 20 days of annual leave."
        ),
        context=ChunkContext(section_path=["Annual leave"]),
        title="Leave policy",
        document_kind="document",
        source=SourceIdentity(
            connector_id="connector-1",
            provider=SourceProvider.CONFLUENCE,
            external_id="doc-1",
            url="https://knowledge.example/leave-policy",
        ),
        hierarchy=Hierarchy(),
        access=EffectiveAccess(reader_ids=["public"]),
        citation=CitationInfo(
            section="Annual leave",
            section_path=("Annual leave",),
            spans=(CitationSpan(
                element_id="paragraph_001",
                start_offset=0,
                end_offset=len("Employees receive 20 days of annual leave."),
            ),),
        ),
        relevance_score=score,
    )


DOCUMENT = _chunk()


def test_citation_resolver_builds_internal_and_native_targets() -> None:
    citation = CitationInfo(anchor="replication")
    source = DOCUMENT.source

    assert CitationResolver.internal_path("item:kafka", "item:kafka:12") == (
        "/knowledge/items/item%3Akafka?chunk=item%3Akafka%3A12"
    )
    assert CitationResolver.original_url(source, citation) == (
        "https://knowledge.example/leave-policy#replication"
    )


class StubRetriever(ScopedKnowledgeRetriever):
    def __init__(self, documents: list[ContextualChunk]) -> None:
        self.documents = documents
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, limit: int) -> list[ContextualChunk]:
        self.calls.append((query, limit))
        return self.documents

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[ContextualChunk]:
        return await self.search(query, limit=limit)


class ScopedStubRetriever(StubRetriever):
    def __init__(self, documents: list[ContextualChunk]) -> None:
        super().__init__(documents)
        self.contexts: list[AgentContext] = []

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[ContextualChunk]:
        self.calls.append((query, limit))
        self.contexts.append(ctx)
        return self.documents


class FailingRetriever(ScopedKnowledgeRetriever):
    async def search(self, query: str, *, limit: int) -> list[ContextualChunk]:
        raise RuntimeError("Qdrant unavailable")

    async def search_scoped(
        self, query: str, *, limit: int, ctx: AgentContext
    ) -> list[ContextualChunk]:
        return await self.search(query, limit=limit)


class BlockingRetriever(ScopedKnowledgeRetriever):
    async def search(self, query: str, *, limit: int) -> list[ContextualChunk]:
        await asyncio.Event().wait()
        return []

    async def search_scoped(
        self, query: str, *, limit: int, ctx: AgentContext
    ) -> list[ContextualChunk]:
        return await self.search(query, limit=limit)


class StubVectorStore:
    async def keyword_scroll(self, query: str, *, limit: int) -> tuple[list[object], None]:
        point = SimpleNamespace(
            id="chunk-1",
            score=0.91,
            payload={
                "item_id": "doc-1",
                "chunk_id": "chunk-1",
                "chunk_index": 0,
                "title": "Leave policy",
                "document_kind": "document",
                "content_type": "text",
                "chunk_text": "Employees receive 20 days of annual leave.",
                "contextual_text": "Document: Leave policy\nSection: Annual leave\n\nEmployees receive 20 days of annual leave.",
                "provider": "confluence",
                "connector_id": "connector-1",
                "external_id": "doc-1",
                "source_url": "https://knowledge.example/leave-policy",
                "context_section_path": ["Annual leave"],
                "citation_section_path": ["Annual leave"],
                "citation_section": "Annual leave",
                "reader_ids": ["public"],
            },
        )
        return [point], None


class StubEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [0.1, 0.2]


class StubSemanticVectorStore:
    def __init__(self) -> None:
        self.calls: list[tuple[list[float], object, int]] = []
        self.access_contexts: list[object] = []
        self.payload_filters: list[object] = []
        self.lifecycle_filter_calls = 0

    def build_lifecycle_filter(self) -> object:
        self.lifecycle_filter_calls += 1
        return "lifecycle-filter"

    def build_retrieval_filter(
        self,
        _search_params: object,
        *,
        access_context: object,
        payload_filters: object,
    ) -> object:
        self.access_contexts.append(access_context)
        self.payload_filters.append(payload_filters)
        return "scoped-filter"

    async def semantic_search(
        self,
        query_vector: list[float],
        *,
        query_filter: object,
        limit: int,
    ) -> list[object]:
        self.calls.append((query_vector, query_filter, limit))
        return [
            SimpleNamespace(
                id="chunk-1",
                score=0.91,
            payload={
                    "item_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "chunk_index": 0,
                    "title": "Leave policy",
                    "document_kind": "document",
                    "content_type": "text",
                    "chunk_text": "Employees receive 20 days of annual leave.",
                    "contextual_text": "Document: Leave policy\nSection: Annual leave\n\nEmployees receive 20 days of annual leave.",
                    "provider": "confluence",
                    "connector_id": "connector-1",
                    "external_id": "doc-1",
                    "source_url": "https://knowledge.example/leave-policy",
                    "context_section_path": ["Annual leave"],
                    "citation_section_path": ["Annual leave"],
                    "citation_section": "Annual leave",
                    "reader_ids": ["public"],
                },
            )
        ]


@pytest.mark.asyncio
async def test_keyword_retriever_normalizes_qdrant_payloads() -> None:
    retriever = QdrantKeywordRetriever(StubVectorStore())  # type: ignore[arg-type]

    results = await retriever.search("annual leave", limit=3)

    assert len(results) == 1
    document = results[0]
    assert document.id == "chunk-1"
    assert document.item_id == "doc-1"
    assert document.title == "Leave policy"
    assert document.source.provider.value == "confluence"
    assert document.source.url == "https://knowledge.example/leave-policy"
    assert document.relevance_score == 0.91
    assert document.citation.section == "Annual leave"
    assert document.citation.section_path == ("Annual leave",)


@pytest.mark.asyncio
async def test_semantic_retriever_embeds_the_query_and_normalizes_qdrant_payloads() -> None:
    store = StubSemanticVectorStore()
    embedder = StubEmbedder()
    retriever = QdrantSemanticRetriever(store, embedder)  # type: ignore[arg-type]

    results = await retriever.search("annual leave", limit=3)

    assert embedder.queries == ["annual leave"]
    assert store.calls == [([0.1, 0.2], None, 3)]
    assert results[0].id == "chunk-1"
    assert results[0].relevance_score == 0.91


@pytest.mark.asyncio
async def test_semantic_retriever_forwards_authenticated_acl_scope() -> None:
    store = StubSemanticVectorStore()
    embedder = StubEmbedder()
    retriever = QdrantSemanticRetriever(
        store,
        embedder,
        allow_unscoped_admin_retrieval=True,
    )  # type: ignore[arg-type]
    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=["analyst"],
        reader_ids=("email:person@example.test", "external_group:finance"),
        is_admin=False,
    )

    await retriever.search_scoped("annual leave", limit=3, ctx=context)

    access = store.access_contexts[0]
    assert getattr(access, "tenant_id") == "tenant-1"
    assert getattr(access, "reader_ids") == (
        "email:person@example.test",
        "external_group:analyst",
        "external_group:finance",
        "public",
        "user-1",
    )
    assert getattr(access, "is_admin") is False
    assert store.payload_filters == [context]
    assert store.lifecycle_filter_calls == 0
    assert store.calls == [([0.1, 0.2], "scoped-filter", 3)]


@pytest.mark.asyncio
async def test_phase1_admin_retrieval_keeps_only_the_lifecycle_filter() -> None:
    store = StubSemanticVectorStore()
    embedder = StubEmbedder()
    retriever = QdrantSemanticRetriever(
        store,
        embedder,
        allow_unscoped_admin_retrieval=True,
    )  # type: ignore[arg-type]
    context = AgentContext(
        user_id="admin-1",
        tenant_id="tenant-1",
        roles=["developer"],
        is_admin=True,
    )

    await retriever.search_scoped("annual leave", limit=3, ctx=context)

    assert store.access_contexts == []
    assert store.lifecycle_filter_calls == 1
    assert store.calls == [([0.1, 0.2], "lifecycle-filter", 3)]


@pytest.mark.asyncio
async def test_knowledge_search_returns_bounded_evidence_and_source_metadata() -> None:
    retriever = StubRetriever([DOCUMENT])
    tool = KnowledgeSearchTool(retriever, result_limit=3)

    result = await tool.execute({"queries": ["annual leave"]}, TOOL_CONTEXT)

    assert retriever.calls == [("annual leave", 3)]
    assert result.error is None
    assert result.metadata["result_count"] == 1
    assert "[chunk-1] Leave policy" in result.content
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.source is not None
    assert evidence.source.provider.value == "confluence"
    assert evidence.source.url == "https://knowledge.example/leave-policy"
    assert evidence.citation.section == "Annual leave"
    assert evidence.item_id == "doc-1"
    assert evidence.chunk_id == "chunk-1"


@pytest.mark.asyncio
async def test_knowledge_search_prefers_permission_scoped_retrieval() -> None:
    retriever = ScopedStubRetriever([DOCUMENT])

    result = await KnowledgeSearchTool(retriever).execute(
        {"queries": ["annual leave"]},
        TOOL_CONTEXT,
    )

    assert result.error is None
    assert retriever.contexts == [CONTEXT]


@pytest.mark.asyncio
async def test_knowledge_search_handles_empty_results() -> None:
    result = await KnowledgeSearchTool(StubRetriever([])).execute(
        {"queries": ["annual leave"]},
        TOOL_CONTEXT,
    )

    assert result.error is None
    assert result.evidence == []
    assert result.metadata["outcome"] == "empty"


@pytest.mark.asyncio
async def test_knowledge_search_handles_retrieval_failures() -> None:
    result = await KnowledgeSearchTool(FailingRetriever()).execute(
        {"queries": ["annual leave"]},
        TOOL_CONTEXT,
    )

    assert result.error == "Knowledge search is temporarily unavailable. Please try again."
    assert result.metadata["outcome"] == "retrieval_failure"


@pytest.mark.asyncio
async def test_knowledge_search_handles_timeouts() -> None:
    result = await KnowledgeSearchTool(
        BlockingRetriever(),
        timeout_seconds=0.01,
    ).execute({"queries": ["annual leave"]}, TOOL_CONTEXT)

    assert result.error == "Knowledge search timed out. Please try again."
    assert result.metadata["outcome"] == "timeout"


def test_knowledge_search_declares_itself_as_a_protocol_function_tool() -> None:
    declaration = KnowledgeSearchTool(StubRetriever([])).as_function_tool()

    assert isinstance(declaration, FunctionTool)
    assert declaration.name == "knowledge_search"
    assert declaration.parameters["required"] == ["queries"]
    assert "access-permitted" in declaration.description
    assert "evidence IDs for citations" in declaration.description
    assert "Do not use generic terms" in declaration.parameters["properties"][
        "queries"
    ]["description"]
    # A closed argument schema lets a provider enforce strict tool calling.
    assert declaration.strict is True


def test_tool_registry_exposes_declarations_through_the_protocol() -> None:
    registry = ToolRegistry()
    registry.register(KnowledgeSearchTool(StubRetriever([])))

    assert [tool.name for tool in registry.function_tools()] == ["knowledge_search"]
    assert registry.function_tools(()) == ()
    definition = registry.definitions()[0]
    assert definition.activity_label == "Search knowledge base"
    assert definition.activity_category == "retrieval"
