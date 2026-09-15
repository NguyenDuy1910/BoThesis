"""Focused contracts for the session / turn / step runtime."""

from __future__ import annotations

import asyncio
import sys
from dataclasses import fields, replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

_TESTS_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_TESTS_ROOT))
sys.path.insert(0, str(_TESTS_ROOT.parent / "backend"))

from native_responses import ScriptedResponsesTransport, completed, created, function_call, message

from bothesis.agent import (
    ContextManager,
    ConversationState,
    ExecutionCapability,
    ExecutionCapabilityResolver,
    AttachmentInput,
    AttachmentRef,
    ImageInput,
    ResourceRef,
    ResolvedStepSettings,
    Session,
    SessionConfiguration,
    SessionServices,
    TextInput,
    TurnContext,
    TurnEnvironmentSnapshot,
    UserTurn,
)
from bothesis.agent.models import AgentContext, ConversationMessage, ToolOutput
from bothesis.agent.protocol import (
    FunctionCallItem,
    FunctionCallOutputItem,
    ExecutionOutput,
    HostedExecutionCallItem,
    HostedExecutionResultItem,
    InputImage,
    InputText,
    ProviderResourceRef,
    ReasoningItem,
)
from bothesis.agent.tools import (
    ToolExecutor,
    ToolInvocation,
    ToolOrchestrator,
    ToolRegistry,
    ToolSpec,
)
from bothesis.agent.tools.read_resource import ReadResource
from bothesis.agent.transports.openrouter_execution_capability import (
    OpenRouterExecutionCapabilityResolver,
)
from bothesis.agent.turn import run_turn
from bothesis.services import (
    AuthContext,
    SandboxManifestResource,
    SandboxProviderFile,
    SandboxSessionState,
)
from bothesis.services.agent_runtime.sandbox_workspace import SandboxWorkspace
from bothesis.services.artifact import WorkspaceSource


class Lookup(ToolExecutor):
    def __init__(self) -> None:
        self.invocations: list[ToolInvocation] = []

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_search",
            description="Search knowledge.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
        )

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        self.invocations.append(invocation)
        return ToolOutput(content=f"found {invocation.payload.arguments['query']}")


class RecordingSession(Session):
    def __init__(self, *args: Any) -> None:
        super().__init__(*args)
        self.steps = []
        self.model_inputs = []

    async def capture_step_context(self, turn: TurnContext):
        step = await super().capture_step_context(turn)
        self.steps.append(step)
        return step

    def build_model_input(self, step_context):  # type: ignore[no-untyped-def]
        model_input = super().build_model_input(step_context)
        self.model_inputs.append(model_input)
        return model_input


def _context(*, allowed: tuple[str, ...] | None = ("knowledge_search",)) -> AgentContext:
    return AgentContext(user_id="user", tenant_id="tenant", roles=[], allowed_tool_names=allowed)


def _turn(context: AgentContext, user_turn: UserTurn | None = None) -> TurnContext:
    settings = ResolvedStepSettings(
        model=None,
        temperature=None,
        max_output_tokens=None,
        parallel_tool_calls=True,
    )
    captured_input = user_turn or UserTurn(
        inputs=(TextInput(text="What is the leave policy?"),)
    )
    resources = list(captured_input.resources)
    known_ids = {resource.id for resource in resources}
    for resource in context.resources:
        if resource.id not in known_ids:
            known_ids.add(resource.id)
            resources.append(resource)
    return TurnContext(
        user_turn=captured_input,
        environment=TurnEnvironmentSnapshot(agent_context=context),
        initial_settings=settings,
        current_settings=settings,
        resources=tuple(resources),
    )


def _session(
    transport: ScriptedResponsesTransport,
    registry: ToolRegistry,
    resource_resolver: RecordingResourceResolver | None = None,
    execution_capability_resolver: ExecutionCapabilityResolver | None = None,
) -> RecordingSession:
    configuration = SessionConfiguration(max_model_turns=3, max_tool_rounds=2)
    return RecordingSession(
        configuration,
        SessionServices(
            model=transport,
            tool_registry=registry,
            resource_resolver=resource_resolver,
            execution_capability_resolver=execution_capability_resolver,
        ),
        ContextManager(configuration=configuration),
    )


class RecordingResourceResolver:
    def __init__(self) -> None:
        self.materialized: list[ResourceRef] = []
        self.read_resources: list[ResourceRef] = []

    async def inspect(self, resource: ResourceRef) -> dict[str, object]:
        return {"id": resource.id}

    async def read(self, resource: ResourceRef, *, max_characters: int) -> str:
        self.read_resources.append(resource)
        return "resource text"

    async def materialize(self, resource: ResourceRef):  # type: ignore[no-untyped-def]
        self.materialized.append(resource)
        return (InputImage(image_url=f"https://resource.test/{resource.id}"),)


@pytest.mark.asyncio
async def test_generic_attachment_stays_lazy_until_a_resource_tool_reads_it() -> None:
    configuration = SessionConfiguration()
    manager = ContextManager(configuration=configuration)
    resolver = RecordingResourceResolver()
    file = ResourceRef(
        id="file-1", name="plan.pdf", mime_type="application/pdf", size_bytes=12
    )

    turn = _turn(
        _context(),
        UserTurn(
            inputs=(
                TextInput(text="Review this plan"),
                AttachmentInput(attachment=AttachmentRef(resource=file)),
            )
        ),
    )
    conversation = ConversationState()
    await manager.start_turn(conversation, turn, resolver)

    assert resolver.materialized == []
    assert conversation.items[-1].content == (InputText(text="Review this plan"),)


@pytest.mark.asyncio
async def test_image_input_materializes_as_native_model_content() -> None:
    configuration = SessionConfiguration()
    manager = ContextManager(configuration=configuration)
    resolver = RecordingResourceResolver()
    image = ResourceRef(id="image-1", name="chart.png", mime_type="image/png")

    turn = _turn(
        _context(),
        UserTurn(inputs=(TextInput(text="What does this chart show?"), ImageInput(image))),
    )
    conversation = ConversationState()
    await manager.start_turn(conversation, turn, resolver)

    assert resolver.materialized == [image]
    assert conversation.items[-1].content == (
        InputText(text="What does this chart show?"),
        InputImage(image_url="https://resource.test/image-1"),
    )


@pytest.mark.asyncio
async def test_context_manager_retains_only_relevant_older_conversation() -> None:
    configuration = SessionConfiguration(max_history_messages=8, recent_history_messages=2)
    manager = ContextManager(configuration=configuration)
    context = AgentContext(
        user_id="user",
        tenant_id="tenant",
        roles=[],
        history=(
            ConversationMessage(role="user", content="Discuss the office party."),
            ConversationMessage(role="assistant", content="The party is on Friday."),
            ConversationMessage(role="user", content="What is the leave policy?"),
            ConversationMessage(role="assistant", content="I can check the leave policy."),
            ConversationMessage(role="user", content="Thanks."),
            ConversationMessage(role="assistant", content="You're welcome."),
        ),
    )

    turn = _turn(
        context, UserTurn(inputs=(TextInput(text="Explain the leave policy"),))
    )
    conversation = ConversationState()
    await manager.start_turn(conversation, turn, RecordingResourceResolver())

    history_text = "\n".join(
        part.text
        for item in conversation.items[:-1]
        for part in item.content
        if isinstance(part, InputText)
    )
    assert "office party" not in history_text
    assert "leave policy" in history_text


@pytest.mark.asyncio
async def test_generic_resource_is_read_only_after_the_model_calls_a_tool() -> None:
    file = ResourceRef(id="file-1", name="plan.txt", mime_type="text/plain")
    resolver = RecordingResourceResolver()
    transport = ScriptedResponsesTransport(
        [
            [
                *created("resp_a"),
                *function_call(
                    item_id="fc_1",
                    output_index=0,
                    call_id="call_1",
                    name="read_resource",
                    argument_deltas=['{"resource_id":"file-1"}'],
                ),
                *completed("resp_a"),
            ],
            [
                *created("resp_b"),
                *message(item_id="msg_1", output_index=0, deltas=["Reviewed."], phase="final_answer"),
                *completed("resp_b"),
            ],
        ]
    )
    registry = ToolRegistry()
    registry.register(ReadResource())
    session = _session(transport, registry, resolver)
    turn = _turn(
        _context(allowed=("read_resource",)),
        UserTurn(
            inputs=(
                TextInput(text="Review the plan"),
                AttachmentInput(attachment=AttachmentRef(resource=file)),
            )
        ),
    )

    events = [event async for event in run_turn(session, turn)]

    assert resolver.read_resources == [file]
    assert "<resource_id>file-1</resource_id>" in transport.requests[0]["instructions"]
    assert "<current_turn_goal>" not in transport.requests[0]["instructions"]
    output = next(
        event.item
        for event in events
        if event.type == "response.output_item.done"
        and event.item.type == "function_call_output"
    )
    assert output.output == "resource text"


@pytest.mark.asyncio
async def test_turn_recaptures_step_and_returns_to_model_after_a_tool() -> None:
    transport = ScriptedResponsesTransport(
        [
            [
                *created("resp_a"),
                *function_call(
                    item_id="fc_1",
                    output_index=0,
                    call_id="call_1",
                    name="knowledge_search",
                    argument_deltas=['{"query":"leave"}'],
                ),
                *completed("resp_a"),
            ],
            [
                *created("resp_b"),
                *message(item_id="msg_1", output_index=0, deltas=["Leave is 20 days."], phase="final_answer"),
                *completed("resp_b"),
            ],
        ]
    )
    lookup = Lookup()
    registry = ToolRegistry()
    registry.register(lookup)
    session = _session(transport, registry)

    events = [event async for event in run_turn(session, _turn(_context()))]

    assert len(session.steps) == 2
    assert session.steps[0] is not session.steps[1]
    assert lookup.invocations[0].step_context is session.steps[0]
    assert transport.requests[1]["input"][-1]["type"] == "function_call_output"
    tool_output = next(
        event.item
        for event in events
        if event.type == "response.output_item.done"
        and event.item.type == "function_call_output"
    )
    assert tool_output.output == "found leave"
    activities = [
        event for event in events if event.type in {"tool_started", "tool_completed"}
    ]
    assert [event.type for event in activities] == ["tool_started", "tool_completed"]
    assert activities[0].call_id == "call_1"
    assert activities[0].tool_name == "knowledge_search"
    assert activities[1].status == "completed"
    assert events[-1].type == "response.completed"


@pytest.mark.asyncio
async def test_step_context_is_immutable_and_model_input_is_materialized_per_step() -> None:
    file = ResourceRef(id="file-1", name="plan.txt", mime_type="text/plain")
    transport = ScriptedResponsesTransport(
        [
            [
                *created("resp_a"),
                *function_call(
                    item_id="fc_1",
                    output_index=0,
                    call_id="call_1",
                    name="read_resource",
                    argument_deltas=['{"resource_id":"file-1"}'],
                ),
                *completed("resp_a"),
            ],
            [
                *created("resp_b"),
                *message(item_id="msg_1", output_index=0, deltas=["Done."], phase="final_answer"),
                *completed("resp_b"),
            ],
        ]
    )
    registry = ToolRegistry()
    registry.register(ReadResource())
    session = _session(transport, registry, RecordingResourceResolver())
    turn = _turn(
        _context(allowed=("read_resource",)),
        UserTurn(
            inputs=(
                TextInput(text="Review this plan"),
                AttachmentInput(attachment=AttachmentRef(resource=file)),
            )
        ),
    )

    _ = [event async for event in run_turn(session, turn)]

    first, second = session.steps
    assert tuple(field.name for field in fields(first)) == (
        "turn_id",
        "step_index",
        "settings",
        "execution_capability",
        "resources",
        "tool_names",
    )
    assert first.turn_id == turn.id
    assert first.step_index == 1
    assert first.resources == (file,)
    assert first.tool_names == ("read_resource",)
    assert first.execution_capability.available is False
    assert first.execution_capability.provider == transport.provider
    assert first.execution_capability.model == transport.model
    first_input, second_input = session.model_inputs
    assert first_input.input_items[-1].role == "user"
    assert "<resource_id>file-1</resource_id>" in first_input.instructions
    assert "<current_turn_goal>" not in first_input.instructions
    assert len(second_input.input_items) > len(first_input.input_items)
    assert second_input.input_items[-1].type == "function_call_output"


@pytest.mark.asyncio
async def test_step_router_is_captured_from_current_turn_visibility() -> None:
    transport = ScriptedResponsesTransport([])
    registry = ToolRegistry()
    registry.register(Lookup())
    session = _session(transport, registry)
    turn = _turn(_context())

    first = await session.capture_step_context(turn)
    turn.environment = TurnEnvironmentSnapshot(agent_context=_context(allowed=()))
    second = await session.capture_step_context(turn)

    assert first.tool_names == ("knowledge_search",)
    assert second.tool_names == ()


@pytest.mark.asyncio
async def test_step_selects_only_explicit_or_user_relevant_resources() -> None:
    relevant = ResourceRef(
        id="leave-policy", name="Leave policy.pdf", mime_type="application/pdf"
    )
    unrelated = ResourceRef(
        id="travel-policy", name="Travel policy.pdf", mime_type="application/pdf"
    )
    context = AgentContext(
        user_id="user",
        tenant_id="tenant",
        roles=[],
        resources=(relevant, unrelated),
    )
    session = _session(ScriptedResponsesTransport([]), ToolRegistry())
    turn = _turn(
        context, UserTurn(inputs=(TextInput(text="Review leave-policy"),))
    )

    step = await session.capture_step_context(turn)

    model_input = session.build_model_input(step)
    assert "<resource_id>leave-policy</resource_id>" in model_input.instructions
    assert "<resource_id>travel-policy</resource_id>" not in model_input.instructions
    assert step.resources == (relevant,)


@pytest.mark.asyncio
async def test_model_input_keeps_reasoning_required_by_a_retained_function_call() -> None:
    session = _session(ScriptedResponsesTransport([]), ToolRegistry())
    turn = _turn(_context())
    await session.capture_step_context(turn)
    reasoning = ReasoningItem(id="rs_1", encrypted_content="x" * 20_000)
    call = FunctionCallItem(
        id="fc_1",
        call_id="call_1",
        name="knowledge_search",
        arguments='{"query":"leave"}',
    )
    output = FunctionCallOutputItem(call_id="call_1", output="found leave")
    session.record((reasoning, call, output))

    step = await session.capture_step_context(turn)
    model_input = session.build_model_input(step)

    assert model_input.input_items[-3:] == (reasoning, call, output)


@pytest.mark.asyncio
async def test_model_input_keeps_reasoning_required_by_hosted_execution_replay() -> None:
    session = _session(ScriptedResponsesTransport([]), ToolRegistry())
    turn = _turn(_context())
    await session.capture_step_context(turn)
    reasoning = ReasoningItem(id="rs_1", encrypted_content="x" * 20_000)
    call = HostedExecutionCallItem(
        id="execution_1",
        call_id="call_1",
        commands=("python --version",),
    )
    output = HostedExecutionResultItem(
        id="result_1",
        call_id="call_1",
        output=(ExecutionOutput(stdout="Python 3.12\\n", exit_code=0),),
    )
    session.record((reasoning, call, output))

    step = await session.capture_step_context(turn)
    model_input = session.build_model_input(step)

    assert model_input.input_items[-3:] == (reasoning, call, output)


def test_openrouter_execution_capabilities_are_provider_and_model_gated() -> None:
    resolver = OpenRouterExecutionCapabilityResolver()

    available = resolver.resolve(provider="openrouter", model="model-with-tools")
    unavailable = resolver.resolve(provider="openai", model="model-with-tools")
    unconfigured = resolver.resolve(provider="openrouter", model=None)

    assert available.available is True
    assert available.hosted_shell is True
    assert available.provider_files is True
    assert available.persistent_environments is True
    assert unavailable.available is False
    assert unconfigured.available is False


@pytest.mark.asyncio
async def test_step_captures_execution_capability_without_exposing_a_shell_tool() -> None:
    registry = ToolRegistry()
    registry.register(Lookup())
    session = _session(
        ScriptedResponsesTransport([]),
        registry,
        execution_capability_resolver=OpenRouterExecutionCapabilityResolver(),
    )

    step = await session.capture_step_context(_turn(_context()))

    assert step.execution_capability.hosted_shell is True
    assert step.tool_names == ("knowledge_search",)


@pytest.mark.asyncio
async def test_hosted_shell_capability_reaches_the_provider_prompt_without_a_local_tool() -> None:
    session = _session(
        ScriptedResponsesTransport([]),
        ToolRegistry(),
        execution_capability_resolver=OpenRouterExecutionCapabilityResolver(),
    )

    step = await session.capture_step_context(_turn(_context()))
    prompt = session.build_model_input(step).prompt(previous_response_id=None)

    assert prompt.tools == ()
    assert prompt.execution_capability == step.execution_capability
    assert prompt.tool_choice == "auto"


@pytest.mark.asyncio
async def test_sandbox_workspace_materializes_reuses_and_exports_without_host_paths() -> None:
    class Provider:
        provider = "openrouter"

        def __init__(self) -> None:
            self.uploads: list[tuple[str, bytes]] = []
            self.downloads: list[tuple[str, str]] = []

        async def upload_file(self, *, file_name: str, mime_type: str, data: bytes):
            assert mime_type == "text/csv"
            self.uploads.append((file_name, data))
            return ProviderResourceRef(
                provider="openrouter", id="or_file_1", name=file_name
            )

        async def download_file(self, *, environment_id: str, file_id: str) -> bytes:
            self.downloads.append((environment_id, file_id))
            return b"month,total\nJan,10\n"

    class Sessions:
        def __init__(self) -> None:
            self.state: SandboxSessionState | None = None

        async def active(self, *_: Any, **__: Any) -> SandboxSessionState | None:
            return self.state

        async def recoverable(self, *_: Any, **__: Any) -> SandboxSessionState | None:
            return None

        async def ensure(self, *_: Any, **__: Any) -> SandboxSessionState:
            assert self.state is None
            self.state = SandboxSessionState(
                id=uuid4(), provider="openrouter", status="active"
            )
            return self.state

        async def record_materialization(
            self, _: AuthContext, *, resource: SandboxManifestResource,
            provider_file: SandboxProviderFile, **__: Any
        ) -> SandboxSessionState:
            assert self.state is not None
            self.state = replace(
                self.state,
                manifest=(resource,),
                materialized_files=(provider_file,),
            )
            return self.state

        async def record_execution(
            self, _: AuthContext, *, environment_id: str,
            files: tuple[SandboxProviderFile, ...], **__: Any
        ) -> SandboxSessionState:
            assert self.state is not None
            self.state = replace(
                self.state, environment_id=environment_id, observed_files=files
            )
            return self.state

        async def record_resource(
            self, _: AuthContext, *, resource: SandboxManifestResource, **__: Any
        ) -> SandboxSessionState:
            assert self.state is not None
            self.state = replace(self.state, manifest=(*self.state.manifest, resource))
            return self.state

        async def expire(self, *_: Any, **__: Any) -> None:
            raise AssertionError("the provider did not expire")

    class Artifacts:
        async def source_file(self, _: AuthContext, document_id):  # type: ignore[no-untyped-def]
            return WorkspaceSource(
                document_id=str(document_id),
                title="Revenue",
                file_name="revenue.csv",
                mime_type="text/csv",
                data=b"month,total\nJan,10\n",
            )

        async def record_generated(self, _: AuthContext, **__: Any) -> dict[str, object]:
            return {
                "id": str(UUID(int=44)),
                "title": "Analysis",
                "file_name": "analysis.csv",
                "mime_type": "text/csv",
                "size_bytes": 19,
                "revision": 1,
                "updated_at": "2026-09-10T00:00:00Z",
            }

    provider = Provider()
    sessions = Sessions()
    access = AuthContext(
        user_id=uuid4(),
        email="owner@example.com",
        display_name=None,
        tenant_id=uuid4(),
        permission_codes=("knowledge.read",),
        group_ids=(),
        role_codes=("member",),
    )
    resource = ResourceRef(
        id=str(UUID(int=33)), name="revenue.csv", mime_type="text/csv", size_bytes=19
    )
    workspace = SandboxWorkspace(
        access=access,
        conversation_id=uuid4(),
        request_id="a" * 32,
        provider=provider,
        sessions=sessions,  # type: ignore[arg-type]
        artifacts=Artifacts(),  # type: ignore[arg-type]
    )
    capability = ExecutionCapability(
        provider="openrouter", model="model", hosted_shell=True
    )

    await workspace.materialize_resource(resource)
    prepared = await workspace.configure_execution(capability)
    await workspace.observe_execution(
        (
            HostedExecutionResultItem(
                call_id="call_1",
                output=(ExecutionOutput(stdout="", exit_code=0),),
                environment={"provider": "openrouter", "id": "container_1"},
                files=(
                    ProviderResourceRef(
                        provider="openrouter", id="cfile_1", name="analysis.csv"
                    ),
                ),
            ),
        )
    )
    resumed = await workspace.configure_execution(capability)
    artifact = await workspace.promote_file(
        "analysis.csv", summary="Saved analysis"
    )

    assert provider.uploads == [("revenue.csv", b"month,total\nJan,10\n")]
    assert prepared.workspace_file_ids == ("or_file_1",)
    assert resumed.environment_id == "container_1"
    assert provider.downloads == [("container_1", "cfile_1")]
    assert artifact.id == str(UUID(int=44))
    assert workspace.artifact_ids == (str(UUID(int=44)),)


class SlowTool(Lookup):
    """A tool that outruns the session budget but declares its own."""

    def __init__(self, *, declared: float | None) -> None:
        super().__init__()
        self._declared = declared

    def spec(self) -> ToolSpec:
        return ToolSpec(
            name="knowledge_search",
            description="Search knowledge.",
            input_schema={
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"],
                "additionalProperties": False,
            },
            timeout_seconds=self._declared,
        )

    async def handle(self, invocation: ToolInvocation) -> ToolOutput:
        await asyncio.sleep(0.15)
        return await super().handle(invocation)


async def _run_slow_tool(declared: float | None) -> str:
    transport = ScriptedResponsesTransport([])
    registry = ToolRegistry()
    registry.register(SlowTool(declared=declared))
    session = _session(transport, registry)
    turn = _turn(_context())
    step = await session.capture_step_context(turn)
    batch = await ToolOrchestrator(
        timeout_seconds=0.05,
        max_output_characters=1_000,
    ).execute(
        (FunctionCallItem(call_id="call_1", name="knowledge_search", arguments='{"query":"leave"}'),),
        session=session,
        turn=turn,
        step_context=step,
        tool_router=session.tool_router(step),
        resources=step.resources,
        remaining_calls=1,
    )
    return batch.output_items[0].output


@pytest.mark.asyncio
async def test_a_tool_declaring_its_own_budget_outlives_the_session_timeout() -> None:
    """A slow tool with its own budget must not be cancelled by the shared budget."""

    assert await _run_slow_tool(declared=5.0) == "found leave"


@pytest.mark.asyncio
async def test_a_tool_without_its_own_budget_still_uses_the_session_timeout() -> None:
    assert await _run_slow_tool(declared=None) == "Tool error: Tool execution timed out."


@pytest.mark.asyncio
async def test_hidden_tool_call_is_rejected_by_the_originating_step_router() -> None:
    transport = ScriptedResponsesTransport([])
    lookup = Lookup()
    registry = ToolRegistry()
    registry.register(lookup)
    session = _session(transport, registry)
    turn = _turn(_context(allowed=()))
    step = await session.capture_step_context(turn)

    batch = await ToolOrchestrator(
        timeout_seconds=1,
        max_output_characters=1_000,
    ).execute(
        (FunctionCallItem(call_id="call_1", name="knowledge_search", arguments='{"query":"leave"}'),),
        session=session,
        turn=turn,
        step_context=step,
        tool_router=session.tool_router(step),
        resources=step.resources,
        remaining_calls=1,
    )

    assert lookup.invocations == []
    assert batch.executed_call_count == 0
    assert batch.output_items[0].output == "Tool error: Tool is not exposed for this sampling step."
