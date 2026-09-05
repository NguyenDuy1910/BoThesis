from __future__ import annotations

import json
import sys
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import quote
from uuid import UUID, uuid4

import httpx
import pytest
from openai import PermissionDeniedError
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import native_responses as native

import api.app as api_app
import api.workspace as workspace_api_module
from bothesis.agent import Agent, AgentConfig
from bothesis.agent.models import AgentContext
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearch
from bothesis.connector.protocol import (
    CitationInfo,
    CitationSpan,
    EffectiveAccess,
    Hierarchy,
    SourceIdentity,
    SourceProvider,
)
from bothesis.document_index import ContextualChunk
from bothesis.knowledge import Evidence, ItemKnowledgeRetriever, source_reference
from api.identity import RequestIdentity
from bothesis.services import AuthContext


def search_call(output_index: int = 0) -> list[Any]:
    return native.function_call(
        item_id="fc_1",
        output_index=output_index,
        call_id="search-1",
        name="knowledge_search",
        argument_deltas=['{"queries":["leave policy"]}'],
    )


class ScriptedTransport(native.ScriptedResponsesTransport):
    """Retrieve once, then answer with a citation marker."""

    def __init__(self) -> None:
        super().__init__(
            [
                [*native.created("resp_a"), *search_call(), *native.completed("resp_a")],
                [
                    *native.created("resp_b"),
                    *native.message(
                        item_id="msg_1",
                        output_index=0,
                        deltas=[
                            "Employees receive 20 days of annual leave "
                            "[[cite:ref_1]]."
                        ],
                        phase="final_answer",
                    ),
                    *native.completed("resp_b"),
                ],
            ]
        )

    @property
    def stream_requests(self) -> list[list[dict[str, Any]]]:
        """The canonical input items of each sampling request."""

        return [request["input"] for request in self.requests]


def test_default_agent_composes_the_openrouter_transport(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from bothesis.agent.transports import openrouter as openrouter_transport

    class TestOpenRouterTransport:
        DEFAULT_BASE_URL = "https://openrouter.test/v1"
        provider = "openrouter"
        model = "gpt-test"

        def __init__(self, **_: Any) -> None:
            pass

        async def stream_response(
            self,
            *_: Any,
            **__: Any,
        ) -> AsyncIterator[Any]:
            if False:
                yield None

    monkeypatch.setattr(openrouter_transport, "OpenRouterTransport", TestOpenRouterTransport)
    monkeypatch.setattr(workspace_api_module, "OpenRouterTransport", TestOpenRouterTransport)
    monkeypatch.setattr(api_app._workspace_api, "_agent", None)

    agent = api_app._workspace_api._get_agent()

    assert isinstance(agent.model, TestOpenRouterTransport)
    assert agent.tools.has("knowledge_search")


class PermissionDeniedTransport:
    provider = "openai"
    model = "gpt-test"

    async def stream_response(self, **_: Any) -> Any:
        request = httpx.Request("POST", "https://api.openai.test/v1/responses")
        response = httpx.Response(403, request=request)
        raise PermissionDeniedError(
            "Your request was blocked.",
            response=response,
            body=None,
        )


@pytest.mark.asyncio
async def test_agent_returns_a_safe_model_access_error_for_openai_denials() -> None:
    events = [
        event
        async for event in Agent(PermissionDeniedTransport(), ToolRegistry()).run(  # type: ignore[arg-type]
            "Hello",
            AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[]),
        )
    ]

    assert [event.type for event in events] == ["response.failed"]
    assert events[0].response.error is not None
    assert events[0].response.error.code == "model_access_denied"
    assert "configured model" in events[0].response.error.message


class StubRetriever:
    def __init__(self) -> None:
        self.contexts: list[Any] = []

    async def search(
        self,
        query: str,
        *,
        limit: int,
        ctx: Any,
    ) -> list[Evidence]:
        assert query == "leave policy"
        assert limit == 5
        self.contexts.append(ctx)
        return self._evidence()

    @staticmethod
    def _evidence() -> list[Evidence]:
        return [
            Evidence(
                id="chunk-1",
                item_id="doc-1",
                chunk_id="chunk-1",
                title="Leave policy",
                content="Employees receive 20 days of annual leave.",
                source=SourceIdentity(
                    connector_id="connector-1",
                    provider=SourceProvider.CONFLUENCE,
                    external_id="doc-1",
                    url="https://knowledge.example/leave-policy",
                ),
                citation=CitationInfo(
                    section="Annual leave",
                    section_path=("Annual leave",),
                    spans=(CitationSpan(
                        element_id="paragraph_001",
                        start_offset=0,
                        end_offset=len("Employees receive 20 days of annual leave."),
                    ),),
                ),
                relevance_score=0.9,
            )
        ]


class InterleavedTransport(native.ScriptedResponsesTransport):
    """Emit user-visible commentary before retrieving, then answer."""

    def __init__(self) -> None:
        super().__init__(
            [
                [
                    *native.created("resp_a"),
                    *native.message(
                        item_id="msg_1",
                        output_index=0,
                        deltas=["I’ll check the relevant source first."],
                        phase="commentary",
                    ),
                    *search_call(output_index=1),
                    *native.completed("resp_a"),
                ],
                [
                    *native.created("resp_b"),
                    *native.message(
                        item_id="msg_2",
                        output_index=0,
                        deltas=["Employees receive 20 days ", "[[cite:ref_1]]."],
                        phase="final_answer",
                    ),
                    *native.completed("resp_b"),
                ],
            ]
        )


class ReasoningTransport(native.ScriptedResponsesTransport):
    """Emit a reasoning item, retrieve, then answer."""

    def __init__(self) -> None:
        super().__init__(
            [
                [
                    *native.created("resp_a"),
                    *native.reasoning(
                        item_id="rs_1",
                        output_index=0,
                        summary="I should search the policy.",
                        text="private raw reasoning",
                        encrypted_content="opaque",
                    ),
                    *search_call(output_index=1),
                    *native.completed("resp_a"),
                ],
                [
                    *native.created("resp_b"),
                    *native.message(
                        item_id="msg_1",
                        output_index=0,
                        deltas=["Employees receive 20 days."],
                        phase="final_answer",
                    ),
                    *native.completed("resp_b"),
                ],
            ]
        )


class _SessionContext:
    async def __aenter__(self) -> _SessionContext:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def commit(self) -> None:
        return None

    async def rollback(self) -> None:
        return None


def _install_access(monkeypatch: Any) -> tuple[UUID, UUID]:
    user_id = uuid4()
    tenant_id = uuid4()

    async def resolve_access(*args: Any, **kwargs: Any) -> AuthContext:
        return AuthContext(
            user_id=user_id,
            email="person@example.test",
            display_name="Person",
            tenant_id=tenant_id,
            role_id=uuid4(),
            role_code="analyst",
            permission_codes=("admin", "knowledge.read"),
            group_ids=(),
        )

    monkeypatch.setattr(api_app._workspace_api, "_resolve_access", resolve_access)
    monkeypatch.setattr(api_app._workspace_api, "_session_factory", _SessionContext)

    class ConversationRecorder:
        def __init__(self) -> None:
            self.started: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
            self.finished: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

        async def start_turn(self, *_: Any, **__: Any) -> None:
            self.started.append((_, __))
            return None

        async def finish_turn(self, *_: Any, **__: Any) -> None:
            self.finished.append((_, __))
            return None

    monkeypatch.setattr(api_app._workspace_api, "_conversations", ConversationRecorder())
    async def allowed_collections(*_: Any, **__: Any) -> tuple[UUID, ...]:
        return (UUID(int=12), UUID(int=14))

    monkeypatch.setattr(
        "api.workspace.CollectionAccessService.allowed_collection_ids",
        allowed_collections,
    )
    return user_id, tenant_id


def test_collection_upload_route_accepts_multipart_without_a_connector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_id = uuid4()
    tenant_id = uuid4()
    user_id = uuid4()
    now = datetime.now(UTC).isoformat()

    async def upload_collection_document(
        identity: RequestIdentity,
        requested_collection_id: UUID,
        **values: Any,
    ) -> dict[str, Any]:
        assert identity.tenant_id == str(tenant_id)
        assert identity.user_id == str(user_id)
        assert requested_collection_id == collection_id
        assert values["idempotency_key"] == "upload-contract-1"
        assert values["file_name"] == "policy.txt"
        assert values["content_type"] == "text/plain"
        assert await values["content"].read() == b"governed policy"
        return {
            "document": {
                "id": str(uuid4()),
                "parent_item_id": str(collection_id),
                "file_name": "policy.txt",
                "content_type": "text/plain",
                "size_bytes": 15,
                "status": "ready",
                "indexed": True,
                "upload_status": "available",
                "created_at": now,
                "uploaded_at": now,
            },
            "ingestion_status": "ready",
            "created": True,
        }

    monkeypatch.setattr(
        api_app._workspace_api,
        "upload_collection_document",
        upload_collection_document,
    )
    with TestClient(api_app.app) as client:
        response = client.post(
            f"/api/v1/collections/{collection_id}/documents/upload",
            headers={
                "Idempotency-Key": "upload-contract-1",
                "X-Bothesis-Tenant-Id": str(tenant_id),
                "X-Bothesis-User-Id": str(user_id),
            },
            files={"file": ("policy.txt", b"governed policy", "text/plain")},
        )

    assert response.status_code == 201
    assert response.json()["document"]["parent_item_id"] == str(collection_id)
    assert response.json()["ingestion_status"] == "ready"


@pytest.mark.asyncio
async def test_collection_upload_reports_ingestion_dispatch_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    service = workspace_api_module.WorkspaceApi(
        allow_insecure_development_identity=True,
        qdrant_prefer_grpc=False,
    )
    user_id = uuid4()
    tenant_id = uuid4()
    collection_id = uuid4()
    now = datetime.now(UTC)
    upload_record = SimpleNamespace(status="available", uploaded_at=now)
    document = SimpleNamespace(
        id=uuid4(),
        parent_item_id=collection_id,
        title="policy.txt",
        mime_type="text/plain",
        size_bytes=15,
        status="ready",
        metadata_={"file_name": "policy.txt"},
        upload=upload_record,
        created_at=now,
    )
    access = AuthContext(
        user_id=user_id,
        email="editor@example.test",
        display_name="Editor",
        tenant_id=tenant_id,
        role_id=uuid4(),
        role_code="editor",
        permission_codes=(),
        group_ids=(),
    )

    class Uploads:
        attempts = 0

        async def upload_to_collection(self, *_: Any, **__: Any) -> Any:
            self.attempts += 1
            document.status = "failed"
            return SimpleNamespace(item=document, created=True)

        async def retry_indexing(self, *_: Any, **__: Any) -> Any:
            self.attempts += 1
            document.status = "ready"
            document.metadata_["processing"] = {"index_schema_version": "test"}
            return document

    async def resolve_access(*_: Any, **__: Any) -> AuthContext:
        return access

    async def record_audit(*_: Any, **__: Any) -> None:
        return None

    monkeypatch.setattr(service, "_resolve_access", resolve_access)
    monkeypatch.setattr(service, "_uploads", Uploads())
    monkeypatch.setattr(service, "_session_factory", _SessionContext)
    monkeypatch.setattr(workspace_api_module.AuditService, "record", record_audit)

    result = await service.upload_collection_document(
        RequestIdentity(user_id=user_id, tenant_id=tenant_id),
        collection_id,
        idempotency_key="dispatch-failure",
        file_name="policy.txt",
        content_type="text/plain",
        content=SimpleNamespace(read=lambda *_: b""),
    )

    assert result["created"] is True
    assert result["ingestion_status"] == "failed"
    assert result["document"]["status"] == "failed"
    assert result["document"]["parent_item_id"] == str(collection_id)

    retried = await service.retry_document_indexing(
        RequestIdentity(user_id=user_id, tenant_id=tenant_id),
        document.id,
    )

    assert retried["created"] is False
    assert retried["ingestion_status"] == "ready"
    assert retried["document"]["status"] == "ready"
    assert retried["document"]["indexed"] is True


def test_qdrant_citation_does_not_synthesize_element_ranges() -> None:
    payload = {
        "chunk_index": 4,
        "chunk_text": "Projected chunk evidence",
        "section_path": ["Policy", "Canonical section"],
        "citation_anchor": "canonical-section",
        "page_start": 3,
        "page_end": 4,
    }

    citation = api_app._workspace_api._payload_citation(payload)

    assert citation.spans == ()
    assert citation.section == "Canonical section"
    assert citation.section_path == ("Policy", "Canonical section")
    assert citation.anchor == "canonical-section"
    assert citation.page_start == 3
    assert citation.page_end == 4


def test_viewer_uses_canonical_multispan_citation_geometry() -> None:
    payload = {
        "chunk_id": "chunk-multi",
        "chunk_index": 0,
        "chunk_text": "First element\n\nSecond element",
        "section_path": ["Policy"],
    }
    citation = CitationInfo(
        section="Policy",
        section_path=("Policy",),
        page_start=1,
        page_end=2,
        spans=(
            CitationSpan(page=1, element_id="p001_para_001"),
            CitationSpan(page=2, element_id="p002_para_001"),
        ),
    )

    elements, chunks_by_id = api_app._workspace_api._viewer_elements(
        "doc-1",
        [payload],
        {"chunk-multi": citation},
    )

    assert elements == []
    assert chunks_by_id["chunk-multi"] is payload
    assert citation.spans[0].element_id == "p001_para_001"
    assert api_app._workspace_api._payload_citation(payload).spans == ()


def test_chat_api_streams_agent_retrieval_and_sources(monkeypatch) -> None:
    registry = ToolRegistry()
    retriever = StubRetriever()
    registry.register(KnowledgeSearch(retriever))
    transport = ScriptedTransport()
    agent = Agent(
        transport,
        registry,
        config=AgentConfig(
            max_model_turns=3,
            max_tool_rounds=2,
            recent_history_messages=2,
        ),
    )
    monkeypatch.setattr(api_app._workspace_api, "_agent", agent)
    user_id, tenant_id = _install_access(monkeypatch)
    conversation_id = uuid4()

    with TestClient(api_app.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "What is the leave policy?",
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "roles": [],
                "conversation_id": str(conversation_id),
                "history": [
                    {"role": "user", "content": "Recent scope question"},
                    {"role": "assistant", "content": "Recent scope answer"},
                ],
                "knowledge_mode": "selected",
                "collection_item_ids": [str(UUID(int=12))],
            },
        )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    event_types = [event["type"] for event in events]
    assert event_types[0] == "response.created"
    assert event_types[-1] == "response.completed"
    assert [event["sequence_number"] for event in events] == list(
        range(1, len(events) + 1)
    )
    assert event_types.count("response.created") == 2
    assert event_types.count("response.completed") == 2
    function_call = next(
        event["item"]
        for event in events
        if event["type"] == "response.output_item.done"
        and event.get("item", {}).get("type") == "function_call"
    )
    assert function_call["call_id"] == "search-1"
    assert function_call["name"] == "knowledge_search"
    annotation = next(
        event["annotation"]
        for event in events
        if event["type"] == "response.output_text.annotation.added"
    )
    assert annotation["type"] == "bothesis:document_citation"
    assert annotation["citation"]["item_id"] == "doc-1"
    assert annotation["citation"]["chunk_id"] == "chunk-1"
    assert annotation["citation"]["reference"] == "ref_1"
    assert annotation["citation"]["number"] == 1
    assert annotation["citation"]["source"]["provider"] == "confluence"
    conversations = api_app._workspace_api._conversations
    assert conversations is not None
    assert len(conversations.started) == 1
    assert conversations.started[0][1]["content"] == "What is the leave policy?"
    assert len(conversations.finished) == 1
    assert conversations.finished[0][1]["content"] == "Employees receive 20 days of annual leave [1]."
    assert len(retriever.contexts) == 1
    assert len(retriever.contexts[0].collection_item_ids) == 1
    # ``/responses`` takes instructions as a request parameter, so the input is
    # items only — there is no synthetic leading system message.
    assert "<agent_instructions>" in transport.requests[0]["instructions"]
    assert [tool["name"] for tool in transport.requests[0]["tools"]] == [
        "knowledge_search"
    ]
    assert transport.stream_requests[0] == [
        {"type": "message", "role": "user", "content": "Recent scope question"},
        {"type": "message", "role": "assistant", "content": "Recent scope answer"},
        {
            "type": "message",
            "role": "user",
            "content": "<user_message>What is the leave policy?</user_message>",
        },
    ]


class IndexedChunkIndex:
    """One indexed chunk, as the vector index returns it to knowledge."""

    def __init__(self, chunk: ContextualChunk) -> None:
        self._chunk = chunk

    async def search_item_content(
        self,
        query: str,
        *,
        limit: int,
        tenant_id: str,
        collection_item_ids: tuple[str, ...],
    ) -> list[ContextualChunk]:
        return [self._chunk]


def _indexed_chunk() -> ContextualChunk:
    return ContextualChunk(
        id="9f1c2d34-0000-4000-8000-000000000001:12",
        item_id="9f1c2d34-0000-4000-8000-000000000001",
        chunk_index=12,
        content_type="text",
        chunk_text="Employees receive 20 days of annual leave.",
        contextual_text="Leave policy: employees receive 20 days of annual leave.",
        title="Leave policy",
        document_type="pdf",
        collection_item_id=str(UUID(int=12)),
        source=SourceIdentity(
            connector_id="upload",
            provider=SourceProvider.FILE,
            external_id="9f1c2d34-0000-4000-8000-000000000001",
        ),
        hierarchy=Hierarchy(),
        access=EffectiveAccess(),
        citation=CitationInfo(page_start=7, page_end=7, section="Annual leave"),
        relevance_score=0.92,
    )


def test_chat_api_resolves_a_cited_source_reference_to_canonical_metadata(
    monkeypatch,
) -> None:
    """The whole grounding chain, from indexed chunk to client citation.

    Retrieval assigns the reference, the model cites only that reference, and
    the backend — not the model — produces the citation the client receives.
    """

    chunk = _indexed_chunk()
    reference = "ref_1"
    captured_context: list[str] = []

    class ContextCapturingSearch(KnowledgeSearch):
        async def execute(self, arguments, ctx):  # type: ignore[no-untyped-def]
            output = await super().execute(arguments, ctx)
            captured_context.append(output.content)
            return output

    registry = ToolRegistry()
    registry.register(
        ContextCapturingSearch(ItemKnowledgeRetriever(IndexedChunkIndex(chunk)))  # type: ignore[arg-type]
    )
    transport = native.ScriptedResponsesTransport(
        [
            [*native.created("resp_a"), *search_call(), *native.completed("resp_a")],
            [
                *native.created("resp_b"),
                *native.message(
                    item_id="msg_1",
                    output_index=0,
                    deltas=[f"Employees receive 20 days [[cite:{reference}]]."],
                    phase="final_answer",
                ),
                *native.completed("resp_b"),
            ],
        ]
    )
    agent = Agent(
        transport,
        registry,
        config=AgentConfig(max_model_turns=3, max_tool_rounds=2),
    )
    monkeypatch.setattr(api_app._workspace_api, "_agent", agent)
    user_id, tenant_id = _install_access(monkeypatch)

    with TestClient(api_app.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "How much annual leave is there?",
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "knowledge_mode": "selected",
                "collection_item_ids": [str(UUID(int=12))],
            },
        )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]

    # The model context offers the reference and withholds internal identifiers.
    assert f"Source reference: {reference}" in captured_context[0]
    assert chunk.id not in captured_context[0]
    assert chunk.item_id not in captured_context[0]

    # The internal marker never reaches the reader; the chip stands where the
    # model put it, inline with the claim it supports.
    answer = "".join(
        event["delta"]
        for event in events
        if event["type"] == "response.output_text.delta"
    )
    assert answer == "Employees receive 20 days [1]."
    assert "[[cite:" not in answer

    # The citation the client receives is built from canonical metadata.
    annotation = next(
        event["annotation"]
        for event in events
        if event["type"] == "response.output_text.annotation.added"
    )
    citation = annotation["citation"]
    assert annotation["type"] == "bothesis:document_citation"
    # The index range brackets the marker, so position survives serialization.
    assert answer[annotation["start_index"] : annotation["end_index"]] == "[1]"
    assert citation["number"] == 1
    assert citation["reference"] == reference
    assert citation["id"] == reference
    assert citation["item_id"] == chunk.item_id
    assert citation["chunk_id"] == chunk.id
    assert citation["title"] == "Leave policy"
    assert citation["page_start"] == 7
    assert citation["internal_url"] == (
        f"/knowledge/items/{chunk.item_id}?chunk={quote(chunk.id, safe='')}"
    )
    # No infrastructure detail reaches the client.
    assert not {"collection_name", "point_id", "storage_key", "vector"} & set(citation)


class TwoChunkIndex:
    """Two indexed chunks of the same document, as the index returns them."""

    def __init__(self, chunks: list[ContextualChunk]) -> None:
        self._chunks = chunks

    async def search_item_content(
        self,
        query: str,
        *,
        limit: int,
        tenant_id: str,
        collection_item_ids: tuple[str, ...],
    ) -> list[ContextualChunk]:
        return self._chunks


def test_chat_api_places_repeated_and_multiple_citations_inline(monkeypatch) -> None:
    """The acceptance case: a chip after each supported claim.

    The same source cited twice keeps one number, a second source gets the
    next, and two markers may sit together on one claim.
    """

    first = _indexed_chunk()
    second = first.model_copy(
        update={
            "id": "9f1c2d34-0000-4000-8000-000000000001:13",
            "chunk_index": 13,
            "chunk_text": "Four endpoints serve the streaming API.",
            "relevance_score": 0.81,
        }
    )
    registry = ToolRegistry()
    registry.register(
        KnowledgeSearch(ItemKnowledgeRetriever(TwoChunkIndex([first, second])))  # type: ignore[arg-type]
    )
    transport = native.ScriptedResponsesTransport(
        [
            [*native.created("resp_a"), *search_call(), *native.completed("resp_a")],
            [
                *native.created("resp_b"),
                *native.message(
                    item_id="msg_1",
                    output_index=0,
                    deltas=[
                        "You must create one VPC endpoint for each service name.",
                        " [[cite:ref_1]] One endpoint is used for the REST API",
                        " and four are used for the streaming API. [[cite:ref_1]]",
                        "[[cite:ref_2]]",
                    ],
                    phase="final_answer",
                ),
                *native.completed("resp_b"),
            ],
        ]
    )
    monkeypatch.setattr(
        api_app._workspace_api,
        "_agent",
        Agent(
            transport,
            registry,
            config=AgentConfig(max_model_turns=3, max_tool_rounds=2),
        ),
    )
    user_id, tenant_id = _install_access(monkeypatch)

    with TestClient(api_app.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "How many VPC endpoints do I need?",
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "knowledge_mode": "selected",
                "collection_item_ids": [str(UUID(int=12))],
            },
        )

    assert response.status_code == 200
    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    answer = "".join(
        event["delta"]
        for event in events
        if event["type"] == "response.output_text.delta"
    )
    annotations = [
        event["annotation"]
        for event in events
        if event["type"] == "response.output_text.annotation.added"
    ]

    assert answer == (
        "You must create one VPC endpoint for each service name. [1] "
        "One endpoint is used for the REST API and four are used for the "
        "streaming API. [1][2]"
    )
    # Three occurrences, two distinct sources; the repeat reuses its number.
    assert [annotation["citation"]["number"] for annotation in annotations] == [1, 1, 2]
    assert [annotation["citation"]["reference"] for annotation in annotations] == [
        "ref_1",
        "ref_1",
        "ref_2",
    ]
    # Every annotation brackets its own marker, in order of appearance.
    assert [
        answer[annotation["start_index"] : annotation["end_index"]]
        for annotation in annotations
    ] == ["[1]", "[1]", "[2]"]
    assert [annotation["start_index"] for annotation in annotations] == sorted(
        annotation["start_index"] for annotation in annotations
    )
    # The repeat resolves to the same chunk, the new number to the other.
    assert annotations[0]["citation"]["chunk_id"] == first.id
    assert annotations[1]["citation"]["chunk_id"] == first.id
    assert annotations[2]["citation"]["chunk_id"] == second.id


def test_document_search_api_uses_authorized_retrieval_scope(monkeypatch) -> None:
    user_id, tenant_id = _install_access(monkeypatch)
    item_id = uuid4()
    collection_id = UUID(int=12)

    class SearchRetriever:
        def __init__(self) -> None:
            self.contexts: list[AgentContext] = []

        async def search(
            self,
            query: str,
            *,
            limit: int,
            ctx: AgentContext,
        ) -> list[Evidence]:
            assert query == "annual leave"
            assert limit == 4
            self.contexts.append(ctx)
            return [
                Evidence(
                    id="chunk-1",
                    item_id=str(item_id),
                    chunk_id="chunk-1",
                    collection_item_id=str(collection_id),
                    title="Leave policy",
                    content="Employees receive 20 days of annual leave.",
                    source=SourceIdentity(
                        connector_id="connection-1",
                        provider=SourceProvider.CONFLUENCE,
                        external_id="leave-policy",
                        url="https://knowledge.example/leave-policy",
                    ),
                    citation=CitationInfo(
                        section="Annual leave",
                        section_path=("Policy", "Annual leave"),
                        page_start=2,
                        page_end=2,
                    ),
                    section_path=("Policy", "Annual leave"),
                    relevance_score=0.8,
                    rerank_score=1.0,
                )
            ]

    retriever = SearchRetriever()
    monkeypatch.setattr(api_app._workspace_api, "_retriever", retriever)

    with TestClient(api_app.app) as client:
        response = client.post(
            "/api/v1/documents/search",
            headers={
                "X-Bothesis-Tenant-Id": str(tenant_id),
                "X-Bothesis-User-Id": str(user_id),
            },
            json={
                "query": "annual leave",
                "top_k": 4,
                "collection_item_ids": [str(collection_id)],
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["results"][0]["id"] == str(item_id)
    assert payload["results"][0]["metadata"]["chunk_id"] == "chunk-1"
    assert payload["results"][0]["metadata"]["citation"]["page_start"] == 2
    assert retriever.contexts[0].tenant_id == str(tenant_id)
    assert retriever.contexts[0].collection_item_ids == (str(collection_id),)


def test_chat_api_flushes_safe_interleaved_events(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(KnowledgeSearch(StubRetriever()))
    agent = Agent(InterleavedTransport(), registry)
    monkeypatch.setattr(api_app._workspace_api, "_agent", agent)
    user_id, tenant_id = _install_access(monkeypatch)

    with TestClient(api_app.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "What is the internal leave policy?",
                "tenant_id": str(tenant_id),
                "user_id": str(user_id),
                "roles": [],
                "history": [],
            },
        )

    events = [
        json.loads(line.removeprefix("data: "))
        for line in response.text.splitlines()
        if line.startswith("data: ")
    ]
    assert response.headers["cache-control"] == "no-cache, no-transform"
    assert response.headers["x-accel-buffering"] == "no"
    event_types = [event["type"] for event in events]
    assert event_types[0] == "response.created"
    assert event_types[-1] == "response.completed"
    assert event_types.count("response.completed") == 2
    call = next(
        event["item"]
        for event in events
        if event["type"] == "response.output_item.done"
        and event.get("item", {}).get("type") == "function_call"
    )
    assert call["call_id"] == "search-1"
    message = next(
        event["item"]
        for event in events
        if event["type"] == "response.output_item.done"
        and event.get("item", {}).get("type") == "message"
        and event["item"]["content"][0]["text"] == "I’ll check the relevant source first."
    )
    assert message["status"] == "completed"


@pytest.mark.asyncio
async def test_a_reasoning_item_replays_as_a_canonical_input_item() -> None:
    """Reasoning continues through the specified fields, not a provider blob."""

    registry = ToolRegistry()
    registry.register(KnowledgeSearch(StubRetriever()))
    transport = ReasoningTransport()
    events = [
        event
        async for event in Agent(transport, registry).run(
            "What is the leave policy?",
            AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[]),
        )
    ]

    assert events[-1].type == "response.completed"
    replayed = transport.requests[1]["input"]
    reasoning = next(item for item in replayed if item.get("type") == "reasoning")
    assert reasoning == {
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": "I should search the policy."}],
        "id": "rs_1",
        "encrypted_content": "opaque",
    }
    # Raw reasoning text is never replayed: the specification's input item
    # carries the summary and the opaque continuation blob only.
    assert "private raw reasoning" not in json.dumps(replayed)


# Incremental delta forwarding, citation-boundary buffering and literal-bracket
# handling are covered by tests/bothesis/agent/test_conversation_loop.py, which
# exercises the same paths without going through the HTTP layer.


def test_chat_api_rejects_unbounded_history() -> None:
    with TestClient(api_app.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "hello",
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "roles": [],
                "history": [
                    {"role": "user", "content": "previous turn"} for _ in range(25)
                ],
            },
        )

    assert response.status_code == 422


def test_chat_api_rejects_history_message_over_context_budget() -> None:
    with TestClient(api_app.app) as client:
        response = client.post(
            "/api/v1/agent/chat",
            json={
                "message": "hello",
                "tenant_id": "tenant-1",
                "user_id": "user-1",
                "roles": [],
                "history": [{"role": "assistant", "content": "A" * 8_001}],
            },
        )

    assert response.status_code == 422


def test_chat_request_requires_a_bounded_explicit_collection_selection() -> None:
    with pytest.raises(ValueError, match="requires at least one Collection"):
        api_app.ChatRequest(message="hello", knowledge_mode="selected")

    request = api_app.ChatRequest(
        message="hello",
        knowledge_mode="selected",
        collection_item_ids=[UUID(int=12), UUID(int=14)],
    )

    assert request.collection_item_ids == [UUID(int=12), UUID(int=14)]
