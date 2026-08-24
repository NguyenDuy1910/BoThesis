from __future__ import annotations

import asyncio
from collections.abc import Sequence
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import AgentContext, ToolContext
from bothesis.agent.protocol import FunctionTool
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearch
from bothesis.document_index.search import QdrantSearchIndex
from bothesis.knowledge import (
    CitationResolver,
    Evidence,
    EvidenceBuilder,
    KnowledgeRetriever,
)
from bothesis.knowledge.retriever import DocumentIndexRetriever
from bothesis.knowledge.reranker import ScoreReranker
from bothesis.connector.protocol import (
    CitationInfo,
    CitationSpan,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index.models import ChunkContext, ContextualChunk

CONTEXT = AgentContext(
    user_id="user-1",
    tenant_id="tenant-1",
    roles=[],
    collection_item_ids=("collection-1",),
)
TOOL_CONTEXT = ToolContext(agent_context=CONTEXT)


def _chunk(
    *,
    chunk_id: str = "chunk-1",
    connection_id: str = "connection-1",
    collection_item_id: str = "collection-1",
    score: float = 0.91,
) -> ContextualChunk:
    return ContextualChunk(
        id=chunk_id,
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
        document_type="plain_text",
        collection_item_id=collection_item_id,
        source=SourceIdentity(
            connector_id=connection_id,
            provider=SourceProvider.CONFLUENCE,
            external_id="doc-1",
            url="https://knowledge.example/leave-policy",
        ),
        hierarchy=Hierarchy(),
        access=EffectiveAccess(),
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
EVIDENCE = EvidenceBuilder().build(DOCUMENT)


def test_citation_resolver_builds_internal_and_native_targets() -> None:
    citation = CitationInfo(anchor="replication")
    source = DOCUMENT.source

    assert CitationResolver.internal_path("item:kafka", "item:kafka:12") == (
        "/knowledge/items/item%3Akafka?chunk=item%3Akafka%3A12"
    )
    assert CitationResolver.original_url(source, citation) == (
        "https://knowledge.example/leave-policy#replication"
    )


def test_evidence_builder_preserves_original_chunk_text_and_citation() -> None:
    evidence = EvidenceBuilder().build(DOCUMENT)

    assert evidence.content == DOCUMENT.chunk_text
    assert evidence.content != DOCUMENT.contextual_text
    assert evidence.citation is DOCUMENT.citation
    assert evidence.chunk_id == DOCUMENT.id


def test_score_reranker_orders_filtered_chunks_and_applies_limit() -> None:
    lower = _chunk(chunk_id="lower", score=0.3)
    higher = _chunk(chunk_id="higher", score=0.9)

    assert ScoreReranker().rerank([lower, higher], limit=1) == [higher]
    with pytest.raises(ValueError, match="limit must be at least one"):
        ScoreReranker().rerank([higher], limit=0)


class StubRetriever(KnowledgeRetriever):
    def __init__(self, evidence: list[Evidence]) -> None:
        self.evidence = evidence
        self.calls: list[tuple[str, int]] = []
        self.contexts: list[AgentContext] = []

    async def search(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[Evidence]:
        self.calls.append((query, limit))
        self.contexts.append(ctx)
        return self.evidence


class FailingRetriever(KnowledgeRetriever):
    async def search(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[Evidence]:
        raise RuntimeError("Qdrant unavailable")


class BlockingRetriever(KnowledgeRetriever):
    async def search(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[Evidence]:
        await asyncio.Event().wait()
        return []


class StubDocumentIndex:
    def __init__(
        self,
        documents: list[ContextualChunk],
        *,
        events: list[str] | None = None,
    ) -> None:
        self.documents = documents
        self.events = events
        self.calls: list[dict[str, object]] = []

    async def search(
        self,
        query: str,
        *,
        limit: int,
        tenant_id: str,
        collection_item_ids: tuple[str, ...],
    ) -> list[ContextualChunk]:
        if self.events is not None:
            self.events.append("index")
        self.calls.append(
            {
                "query": query,
                "limit": limit,
                "tenant_id": tenant_id,
                "collection_item_ids": collection_item_ids,
            }
        )
        return self.documents


class RecordingReranker:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[list[ContextualChunk]] = []

    def rerank(
        self,
        chunks: Sequence[ContextualChunk],
        *,
        limit: int,
    ) -> list[ContextualChunk]:
        self.events.append("rerank")
        self.calls.append(list(chunks))
        return ScoreReranker().rerank(chunks, limit=limit)


class RecordingEvidenceBuilder(EvidenceBuilder):
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.calls: list[ContextualChunk] = []

    def build(self, chunk: ContextualChunk) -> Evidence:
        self.events.append("evidence")
        self.calls.append(chunk)
        return super().build(chunk)


class StubEmbedder:
    def __init__(self) -> None:
        self.queries: list[str] = []

    async def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [0.1, 0.2]


class StubSemanticVectorStore:
    def __init__(self) -> None:
        self.calls: list[tuple[list[float], str, object, int, int]] = []
        self.access_contexts: list[object] = []
        self.payload_filters: list[object] = []

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
        query_text: str,
        query_filter: object,
        limit: int,
        candidate_limit: int,
    ) -> list[object]:
        self.calls.append(
            (query_vector, query_text, query_filter, limit, candidate_limit)
        )
        return [
            SimpleNamespace(
                id="chunk-1",
                score=0.91,
                payload={
                    "item_id": "doc-1",
                    "chunk_id": "chunk-1",
                    "chunk_index": 0,
                    "title": "Leave policy",
                    "document_type": "plain_text",
                    "collection_item_id": "collection-1",
                    "content_type": "text",
                    "chunk_text": " Employees receive 20 days of annual leave.\n",
                    "contextual_text": "Document: Leave policy\nSection: Annual leave\n\n Employees receive 20 days of annual leave.\n",
                    "plugin_key": "confluence",
                    "connection_id": "connection-1",
                    "external_id": "doc-1",
                    "source_url": "https://knowledge.example/leave-policy",
                    "context_section_path": ["Annual leave"],
                    "citation_section_path": ["Annual leave"],
                    "citation_section": "Annual leave",
                },
            )
        ]


@pytest.mark.asyncio
async def test_qdrant_search_index_embeds_and_rebuilds_contextual_chunks() -> None:
    store = StubSemanticVectorStore()
    embedder = StubEmbedder()
    index = QdrantSearchIndex(store, embedder)  # type: ignore[arg-type]

    results = await index.search(
        " annual leave ",
        limit=3,
        tenant_id="tenant-1",
        collection_item_ids=("collection-1",),
    )

    assert embedder.queries == ["annual leave"]
    assert store.calls == [
        ([0.1, 0.2], "annual leave", "scoped-filter", 3, 20)
    ]
    access = store.access_contexts[0]
    assert getattr(access, "tenant_id") == "tenant-1"
    assert getattr(access, "collection_item_ids") == ("collection-1",)
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
    assert document.chunk_text == " Employees receive 20 days of annual leave.\n"
    assert document.contextual_text.endswith(" annual leave.\n")


@pytest.mark.asyncio
async def test_collection_scoped_retrieval_filters_before_reranking() -> None:
    events: list[str] = []
    visible = _chunk(chunk_id="visible", collection_item_id="collection-7", score=0.5)
    wrong_collection = _chunk(
        chunk_id="wrong-collection",
        collection_item_id="collection-8",
        score=0.99,
    )
    index = StubDocumentIndex(
        [wrong_collection, visible],
        events=events,
    )
    reranker = RecordingReranker(events)
    evidence_builder = RecordingEvidenceBuilder(events)
    retriever = DocumentIndexRetriever(
        index,
        reranker=reranker,
        evidence_builder=evidence_builder,
    )
    context = AgentContext(
        user_id="person@example.test",
        tenant_id="tenant-1",
        roles=["analyst"],
        collection_item_ids=("collection-7",),
    )

    results = await retriever.search(" annual leave ", limit=3, ctx=context)

    assert index.calls == [
        {
            "query": "annual leave",
            "limit": 3,
            "tenant_id": "tenant-1",
            "collection_item_ids": ("collection-7",),
        }
    ]
    assert events == ["index", "rerank", "evidence"]
    assert reranker.calls == [[visible]]
    assert evidence_builder.calls == [visible]
    assert results == [EvidenceBuilder().build(visible)]
    assert isinstance(results[0], Evidence)


@pytest.mark.asyncio
@pytest.mark.parametrize(("query", "limit"), [("   ", 3), ("annual leave", 0)])
async def test_document_index_retriever_validates_before_search_or_reranking(
    query: str,
    limit: int,
) -> None:
    events: list[str] = []
    index = StubDocumentIndex([DOCUMENT], events=events)
    retriever = DocumentIndexRetriever(index, reranker=RecordingReranker(events))
    context = AgentContext(
        user_id="user-1",
        tenant_id="tenant-1",
        roles=[],
        collection_item_ids=(),
    )

    with pytest.raises(ValueError):
        await retriever.search(query, limit=limit, ctx=context)

    assert index.calls == []
    assert events == []


@pytest.mark.asyncio
async def test_document_index_retriever_requires_a_tenant_even_for_empty_scope() -> None:
    index = StubDocumentIndex([DOCUMENT])
    retriever = DocumentIndexRetriever(index)
    context = AgentContext(
        user_id="user-1",
        tenant_id="   ",
        roles=[],
        collection_item_ids=("collection-1",),
    )

    with pytest.raises(ValueError, match="tenant_id must not be empty"):
        await retriever.search("annual leave", limit=3, ctx=context)

    assert index.calls == []


@pytest.mark.asyncio
async def test_collection_retrieval_remains_tenant_scoped() -> None:
    index = StubDocumentIndex([DOCUMENT])
    retriever = DocumentIndexRetriever(index)
    context = AgentContext(
        user_id="admin-1",
        tenant_id="tenant-1",
        roles=["developer"],
        collection_item_ids=("collection-1",),
    )

    results = await retriever.search("annual leave", limit=3, ctx=context)

    assert index.calls[0]["tenant_id"] == "tenant-1"
    assert index.calls[0]["collection_item_ids"] == ("collection-1",)
    assert results == [EVIDENCE]


@pytest.mark.asyncio
async def test_qdrant_search_index_rejects_a_missing_tenant_scope() -> None:
    store = StubSemanticVectorStore()
    embedder = StubEmbedder()
    index = QdrantSearchIndex(store, embedder)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="tenant_id must not be empty"):
        await index.search(
            "annual leave",
            limit=3,
            tenant_id="",
            collection_item_ids=("collection-1",),
        )

    assert store.access_contexts == []
    assert store.calls == []
    assert embedder.queries == []


@pytest.mark.asyncio
async def test_knowledge_search_returns_bounded_evidence_and_source_metadata() -> None:
    retriever = StubRetriever([EVIDENCE])
    tool = KnowledgeSearch(retriever, result_limit=3)

    result = await tool.execute({"queries": ["annual leave"]}, TOOL_CONTEXT)

    assert retriever.calls == [("annual leave", 3)]
    assert result.error is None
    assert result.metadata["result_count"] == 1
    assert "[chunk-1] Leave policy" in result.content
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence is EVIDENCE
    assert evidence.source is not None
    assert evidence.source.provider.value == "confluence"
    assert evidence.source.url == "https://knowledge.example/leave-policy"
    assert evidence.citation.section == "Annual leave"
    assert evidence.item_id == "doc-1"
    assert evidence.chunk_id == "chunk-1"


@pytest.mark.asyncio
async def test_knowledge_search_passes_the_authenticated_context() -> None:
    retriever = StubRetriever([EVIDENCE])

    result = await KnowledgeSearch(retriever).execute(
        {"queries": ["annual leave"]},
        TOOL_CONTEXT,
    )

    assert result.error is None
    assert retriever.contexts == [CONTEXT]


@pytest.mark.asyncio
async def test_knowledge_search_handles_empty_results() -> None:
    result = await KnowledgeSearch(StubRetriever([])).execute(
        {"queries": ["annual leave"]},
        TOOL_CONTEXT,
    )

    assert result.error is None
    assert result.evidence == []
    assert result.metadata["outcome"] == "empty"


@pytest.mark.asyncio
async def test_knowledge_search_handles_retrieval_failures() -> None:
    result = await KnowledgeSearch(FailingRetriever()).execute(
        {"queries": ["annual leave"]},
        TOOL_CONTEXT,
    )

    assert result.error == "Knowledge search is temporarily unavailable. Please try again."
    assert result.metadata["outcome"] == "retrieval_failure"


@pytest.mark.asyncio
async def test_knowledge_search_handles_timeouts() -> None:
    result = await KnowledgeSearch(
        BlockingRetriever(),
        timeout_seconds=0.01,
    ).execute({"queries": ["annual leave"]}, TOOL_CONTEXT)

    assert result.error == "Knowledge search timed out. Please try again."
    assert result.metadata["outcome"] == "timeout"


def test_knowledge_search_declares_itself_as_a_protocol_function_tool() -> None:
    declaration = KnowledgeSearch(StubRetriever([])).as_function_tool()

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
    registry.register(KnowledgeSearch(StubRetriever([])))

    assert [tool.name for tool in registry.function_tools()] == ["knowledge_search"]
    assert registry.function_tools(()) == ()
    definition = registry.definitions()[0]
    assert definition.activity_label == "Search knowledge base"
    assert definition.activity_category == "retrieval"
