from __future__ import annotations

import asyncio
import json
import sys
from collections.abc import AsyncIterator, Mapping, Sequence
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

import main
import bothesis.db.engine as db_engine
from bothesis.agent import Agent, AgentConfig
from bothesis.agent.models import AgentContext, ConversationDocument, Evidence
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.tools.knowledge_search import KnowledgeSearchTool
from bothesis.knowledge.document_index import RetrievedDocument
from bothesis.services import AuthContext


def text_delta(text: str) -> dict[str, Any]:
    return {"choices": [{"delta": {"content": text}}]}


def turn_done(
    finish_reason: str,
    *,
    tool_calls: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    delta: dict[str, Any] = {}
    if tool_calls:
        delta["tool_calls"] = [
            {"index": index, **call} for index, call in enumerate(tool_calls)
        ]
    return {"choices": [{"delta": delta, "finish_reason": finish_reason}]}


class ScriptedTransport:
    provider = "openrouter"
    model = "openai/gpt-5.4-mini"

    def __init__(self) -> None:
        self.stream_requests: list[list[dict[str, Any]]] = []

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.stream_requests.append([dict(message) for message in messages])
        if len(self.stream_requests) == 1:
            yield turn_done(
                "tool_calls",
                tool_calls=[
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "knowledge_search",
                            "arguments": '{"queries":["leave policy"]}',
                        },
                    }
                ],
            )
            return
        yield text_delta("Employees receive 20 days of annual leave [[cite:chunk-1]].")
        yield turn_done("stop")


class StubRetriever:
    def __init__(self) -> None:
        self.contexts: list[Any] = []

    async def search(self, query: str, *, limit: int) -> list[RetrievedDocument]:
        assert query == "leave policy"
        assert limit == 5
        return self._documents()

    async def search_scoped(
        self,
        query: str,
        *,
        limit: int,
        ctx: Any,
    ) -> list[RetrievedDocument]:
        assert query == "leave policy"
        assert limit == 5
        self.contexts.append(ctx)
        return self._documents()

    @staticmethod
    def _documents() -> list[RetrievedDocument]:
        return [
            RetrievedDocument(
                id="chunk-1",
                document_id="doc-1",
                title="Leave policy",
                content="Employees receive 20 days of annual leave.",
                source="confluence",
                uri="https://knowledge.example/leave-policy",
                metadata={"section_title": "Annual leave"},
                relevance_score=0.9,
            )
        ]


class InterleavedTransport:
    provider = "openrouter"
    model = "openai/gpt-5.4-mini"

    def __init__(self) -> None:
        self.turn = 0

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.turn += 1
        if self.turn == 1:
            yield text_delta("I’ll check the relevant source first.")
            yield turn_done(
                "tool_calls",
                tool_calls=[
                    {
                        "id": "search-1",
                        "type": "function",
                        "function": {
                            "name": "knowledge_search",
                            "arguments": '{"queries":["leave policy"]}',
                        },
                    }
                ],
            )
            return
        yield text_delta("Employees receive 20 days ")
        yield text_delta("[[cite:chunk-1]].")
        yield turn_done("stop")


class OpenRouterReasoningSummaryTransport:
    provider = "openrouter"
    model = "openai/gpt-5.4-mini"

    def __init__(self) -> None:
        self.stream_requests: list[list[dict[str, Any]]] = []

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        self.stream_requests.append([dict(message) for message in messages])
        if len(self.stream_requests) == 1:
            yield {
                "choices": [{"delta": {"reasoning": "private raw reasoning", "reasoning_details": [
                    {
                        "type": "reasoning.summary",
                        "summary": "I should search the policy.",
                        "id": "summary-1",
                        "format": "openai-responses-v1",
                        "index": 0,
                    },
                    {
                        "type": "reasoning.encrypted",
                        "data": "opaque",
                        "id": "encrypted-1",
                        "format": "openai-responses-v1",
                        "index": 1,
                    },
                ]}}]
            }
            yield turn_done(
                "tool_calls",
                tool_calls=[{
                    "id": "search-1",
                    "type": "function",
                    "function": {
                        "name": "knowledge_search",
                        "arguments": '{"queries":["leave policy"]}',
                    },
                }],
            )
            return
        yield text_delta("Employees receive 20 days.")
        yield turn_done("stop")


class PausingTransport:
    provider = "openrouter"
    model = "openai/gpt-5.4-mini"

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        yield text_delta("first ")
        await self.release.wait()
        yield text_delta("second")
        yield turn_done("stop")


class SplitCitationTransport:
    provider = "openrouter"
    model = "openai/gpt-5.4-mini"

    def __init__(self) -> None:
        self.release = asyncio.Event()

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        yield text_delta("Policy [")
        await self.release.wait()
        yield text_delta("[cite:ev-1]] applies")
        yield turn_done("stop")


class LiteralBracketTransport:
    provider = "openrouter"
    model = "openai/gpt-5.4-mini"

    async def stream_chat(
        self,
        *,
        messages: Sequence[Mapping[str, Any]],
        **_: Any,
    ) -> AsyncIterator[dict[str, Any]]:
        yield text_delta("Array[")
        await asyncio.sleep(0)
        yield text_delta("0]")
        yield turn_done("stop")


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
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
            principal_tokens=("external_group:finance",),
        )

    monkeypatch.setattr(main, "_resolve_access", resolve_access)
    monkeypatch.setattr(db_engine, "get_session_factory", lambda: _SessionContext)
    return user_id, tenant_id


def test_chat_api_streams_agent_retrieval_and_sources(monkeypatch) -> None:
    registry = ToolRegistry()
    retriever = StubRetriever()
    registry.register(KnowledgeSearchTool(retriever))
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
    monkeypatch.setattr(main, "_agent", agent)
    user_id, tenant_id = _install_access(monkeypatch)
    conversation_id = uuid4()

    with TestClient(main.app) as client:
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
    assert annotation["type"] == "citation"
    assert annotation["citation"]["document_id"] == "doc-1"
    assert annotation["citation"]["source"] == "confluence"
    assert len(retriever.contexts) == 1
    assert retriever.contexts[0].reader_ids == (
        "email:person@example.test",
        "external_group:finance",
    )
    assert retriever.contexts[0].is_admin is True
    model_request = transport.stream_requests[0]
    assert model_request[0]["role"] == "system"
    assert model_request[1:] == [
        {"role": "user", "content": "Recent scope question"},
        {"role": "assistant", "content": "Recent scope answer"},
        {
            "role": "user",
            "content": "<user_message>What is the leave policy?</user_message>",
        },
    ]


def test_chat_api_flushes_safe_interleaved_events(monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(KnowledgeSearchTool(StubRetriever()))
    agent = Agent(InterleavedTransport(), registry)
    monkeypatch.setattr(main, "_agent", agent)
    user_id, tenant_id = _install_access(monkeypatch)

    with TestClient(main.app) as client:
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
async def test_openrouter_replays_native_reasoning_and_traces_only_summary() -> None:
    registry = ToolRegistry()
    registry.register(KnowledgeSearchTool(StubRetriever()))
    transport = OpenRouterReasoningSummaryTransport()
    events = [
        event
        async for event in Agent(transport, registry).run(
            "What is the leave policy?",
            AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[]),
        )
    ]

    assert events[-1].type == "response.completed"
    replay = transport.stream_requests[1]
    assistant = next(
        message for message in replay if message.get("role") == "assistant"
    )
    assert assistant["reasoning"] == "private raw reasoning"
    assert assistant["reasoning_details"] == [
        {
            "type": "reasoning.summary",
            "summary": "I should search the policy.",
            "id": "summary-1",
            "format": "openai-responses-v1",
            "index": 0,
        },
        {
            "type": "reasoning.encrypted",
            "data": "opaque",
            "id": "encrypted-1",
            "format": "openai-responses-v1",
            "index": 1,
        },
    ]


@pytest.mark.asyncio
async def test_agent_emits_text_before_sampling_completion() -> None:
    transport = PausingTransport()
    agent = Agent(transport, ToolRegistry())
    stream = agent.run(
        "Stream this answer",
        AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[]),
    )

    assert (await anext(stream)).type == "response.created"
    started = await asyncio.wait_for(anext(stream), timeout=0.1)
    part_added = await asyncio.wait_for(anext(stream), timeout=0.1)
    first_delta = await asyncio.wait_for(anext(stream), timeout=0.1)

    assert started.type == "response.output_item.added"
    assert started.item.type == "message"
    assert part_added.type == "response.content_part.added"
    assert first_delta.type == "response.output_text.delta"
    assert first_delta.delta == "first "

    transport.release.set()
    remaining = [event async for event in stream]
    assert [event.type for event in remaining] == [
        "response.output_text.delta",
        "response.output_text.done",
        "response.content_part.done",
        "response.output_item.done",
        "response.completed",
    ]
    assert remaining[-1].response.output_text == "first second"


@pytest.mark.asyncio
async def test_agent_keeps_only_citation_boundary_buffered() -> None:
    transport = SplitCitationTransport()
    agent = Agent(transport, ToolRegistry())
    evidence = Evidence(
        id="ev-1",
        document_id="doc-1",
        title="Policy",
        content="Grounded policy",
    )
    stream = agent.run(
        "Stream cited text",
        AgentContext(
            user_id="user-1",
            tenant_id="tenant-1",
            roles=[],
            documents=(ConversationDocument(
                id="doc-1",
                title="Policy",
                content_type="text/plain",
                mode="indexed",
                citation_id="ev-1",
                evidence=(evidence,),
            ),),
        ),
    )

    assert (await anext(stream)).type == "response.created"
    assert (await anext(stream)).type == "response.output_item.added"
    assert (await anext(stream)).type == "response.content_part.added"
    first_delta = await asyncio.wait_for(anext(stream), timeout=0.1)
    assert first_delta.type == "response.output_text.delta"
    assert first_delta.delta == "Policy "

    transport.release.set()
    remaining = [event async for event in stream]
    assert [event.delta for event in remaining if event.type == "response.output_text.delta"] == [
        " applies"
    ]
    citation = next(
        event.annotation
        for event in remaining
        if event.type == "response.output_text.annotation.added"
    )
    assert citation["citation"]["id"] == "ev-1"
    completed_part = next(
        event.part
        for event in remaining
        if event.type == "response.content_part.done"
    )
    assert completed_part.text == "Policy  applies"
    assert completed_part.annotations[0]["citation"]["id"] == "ev-1"


@pytest.mark.asyncio
async def test_agent_does_not_delay_literal_brackets_without_evidence() -> None:
    stream = Agent(LiteralBracketTransport(), ToolRegistry()).run(
        "Stream literal brackets",
        AgentContext(user_id="user-1", tenant_id="tenant-1", roles=[]),
    )
    events = [event async for event in stream]

    assert [event.delta for event in events if event.type == "response.output_text.delta"] == [
        "Array[",
        "0]",
    ]


def test_chat_api_rejects_unbounded_history() -> None:
    with TestClient(main.app) as client:
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
    with TestClient(main.app) as client:
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
