from __future__ import annotations

import asyncio
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import AgentContext
from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
from bothesis.knowledge.document_index import (
    QdrantKeywordRetriever,
    QdrantSemanticRetriever,
    RetrievedDocument,
)

CONTEXT = AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[])
DOCUMENT = RetrievedDocument(
    id="chunk-1",
    document_id="doc-1",
    title="Leave policy",
    content="Employees receive 20 days of annual leave.",
    source="confluence",
    uri="https://knowledge.example/leave-policy",
    metadata={"section_title": "Annual leave"},
    relevance_score=0.91,
)


class StubRetriever:
    def __init__(self, documents: list[RetrievedDocument]) -> None:
        self.documents = documents
        self.calls: list[tuple[str, int]] = []

    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        self.calls.append((query, limit))
        return self.documents


class ScopedStubRetriever(StubRetriever):
    def __init__(self, documents: list[RetrievedDocument]) -> None:
        super().__init__(documents)
        self.contexts: list[AgentContext] = []

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: AgentContext,
    ) -> list[RetrievedDocument]:
        self.calls.append((query, limit))
        self.contexts.append(ctx)
        return self.documents


class FailingRetriever:
    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        raise RuntimeError("Qdrant unavailable")


class BlockingRetriever:
    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        await asyncio.Event().wait()
        return []


class StubVectorStore:
    async def keyword_scroll(self, query: str, *, limit: int) -> tuple[list[object], None]:
        point = SimpleNamespace(
            id="chunk-1",
            score=0.91,
            payload={
                "document_id": "doc-1",
                "title": "Leave policy",
                "content": "Employees receive 20 days of annual leave.",
                "source": "confluence",
                "source_link": "https://knowledge.example/leave-policy",
                "section_title": "Annual leave",
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
                    "document_id": "doc-1",
                    "title": "Leave policy",
                    "content": "Employees receive 20 days of annual leave.",
                    "source": "confluence",
                    "source_link": "https://knowledge.example/leave-policy",
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
    assert document.document_id == "doc-1"
    assert document.title == "Leave policy"
    assert document.source == "confluence"
    assert document.uri == "https://knowledge.example/leave-policy"
    assert document.relevance_score == 0.91
    assert document.metadata["section_title"] == "Annual leave"
    assert "content" not in document.metadata


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
async def test_knowledge_search_returns_bounded_evidence_and_source_metadata() -> None:
    retriever = StubRetriever([DOCUMENT])
    tool = KnowledgeSearchTool(retriever, result_limit=3)

    result = await tool.execute({"query": "annual leave"}, CONTEXT)

    assert retriever.calls == [("annual leave", 3)]
    assert result.error is None
    assert result.metadata["result_count"] == 1
    assert "[chunk-1] Leave policy" in result.content
    assert len(result.evidence) == 1
    evidence = result.evidence[0]
    assert evidence.source == "confluence"
    assert evidence.uri == "https://knowledge.example/leave-policy"
    assert evidence.section == "Annual leave"


@pytest.mark.asyncio
async def test_knowledge_search_prefers_permission_scoped_retrieval() -> None:
    retriever = ScopedStubRetriever([DOCUMENT])

    result = await KnowledgeSearchTool(retriever).execute(
        {"query": "annual leave"},
        CONTEXT,
    )

    assert result.error is None
    assert retriever.contexts == [CONTEXT]


@pytest.mark.asyncio
async def test_knowledge_search_handles_empty_results() -> None:
    result = await KnowledgeSearchTool(StubRetriever([])).execute(
        {"query": "annual leave"},
        CONTEXT,
    )

    assert result.error is None
    assert result.evidence == []
    assert result.metadata["outcome"] == "empty"


@pytest.mark.asyncio
async def test_knowledge_search_handles_retrieval_failures() -> None:
    result = await KnowledgeSearchTool(FailingRetriever()).execute(
        {"query": "annual leave"},
        CONTEXT,
    )

    assert result.error == "Knowledge search is temporarily unavailable. Please try again."
    assert result.metadata["outcome"] == "retrieval_failure"


@pytest.mark.asyncio
async def test_knowledge_search_handles_timeouts() -> None:
    result = await KnowledgeSearchTool(
        BlockingRetriever(),
        timeout_seconds=0.01,
    ).execute({"query": "annual leave"}, CONTEXT)

    assert result.error == "Knowledge search timed out. Please try again."
    assert result.metadata["outcome"] == "timeout"
