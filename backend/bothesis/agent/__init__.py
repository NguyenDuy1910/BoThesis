"""Provider-neutral contracts for BoThesis's single-agent turn runtime."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from time import perf_counter
from typing import TYPE_CHECKING, Any, Protocol, TypeAlias
from uuid import uuid4

from bothesis.agent.execution import ExecutionCapability
from bothesis.agent.models import (
    AgentContext,
    CitationReferences,
    ConversationMessage,
    Evidence,
)
from bothesis.agent.protocol import (
    InputImage,
    InputText,
    FunctionCallOutputItem,
    HostedExecutionResultItem,
    Item,
    Prompt,
    Tool,
    RuntimeActivityEvent,
    ResponseStreamEvent,
)


ModelContent: TypeAlias = InputText | InputImage
"""Concrete, provider-neutral content the runtime sends to a model."""


@dataclass(frozen=True, slots=True)
class ResourceRef:
    """A stable, access-checked resource identity; never a storage path."""

    id: str
    name: str
    mime_type: str
    size_bytes: int | None = None

    def __post_init__(self) -> None:
        if not self.id.strip() or not self.name.strip() or not self.mime_type.strip():
            raise ValueError("resource id, name, and mime type must not be blank")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("resource size must not be negative")

    @property
    def is_image(self) -> bool:
        return self.mime_type.casefold().startswith("image/")


@dataclass(frozen=True, slots=True)
class SandboxMaterialization:
    """A durable resource made available to the next hosted-shell step."""

    resource: ResourceRef


@dataclass(frozen=True, slots=True)
class SandboxArtifact:
    """A deliberately exported sandbox file, now a durable Item artifact."""

    id: str
    title: str
    name: str
    mime_type: str
    revision: int
    size_bytes: int
    updated_at: str | None

    def __post_init__(self) -> None:
        if not all(
            value.strip() for value in (self.id, self.title, self.name, self.mime_type)
        ):
            raise ValueError("sandbox artifact fields must not be blank")
        if self.revision < 1:
            raise ValueError("sandbox artifact revision must be positive")
        if self.size_bytes < 0:
            raise ValueError("sandbox artifact size must not be negative")


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """A current-turn attachment relationship to one accessible resource."""

    resource: ResourceRef


@dataclass(frozen=True, slots=True)
class TextInput:
    """Text entered by the user in the current turn."""

    text: str

    def __post_init__(self) -> None:
        if not self.text.strip():
            raise ValueError("text input must not be blank")


@dataclass(frozen=True, slots=True)
class ImageInput:
    """An image resource the runtime may materialize as native model input."""

    resource: ResourceRef


@dataclass(frozen=True, slots=True)
class AttachmentInput:
    """A generic current-turn attachment that remains lazy by default."""

    attachment: AttachmentRef


@dataclass(frozen=True, slots=True)
class ResourceInput:
    """An existing accessible resource explicitly referenced by the user."""

    resource: ResourceRef


UserInput: TypeAlias = TextInput | ImageInput | AttachmentInput | ResourceInput


@dataclass(frozen=True, slots=True)
class UserTurn:
    """Everything that entered one user turn, before runtime resolution."""

    inputs: tuple[UserInput, ...]

    def __post_init__(self) -> None:
        if not self.inputs:
            raise ValueError("a user turn must contain at least one input")

    @property
    def text(self) -> str:
        return "\n".join(
            input_.text.strip()
            for input_ in self.inputs
            if isinstance(input_, TextInput)
        )

    @property
    def resources(self) -> tuple[ResourceRef, ...]:
        """Current-turn resources in first-reference order."""

        resources: list[ResourceRef] = []
        seen: set[str] = set()
        for input_ in self.inputs:
            resource = (
                input_.resource
                if isinstance(input_, (ImageInput, ResourceInput))
                else input_.attachment.resource
                if isinstance(input_, AttachmentInput)
                else None
            )
            if resource is not None and resource.id not in seen:
                seen.add(resource.id)
                resources.append(resource)
        return tuple(resources)


class ResourceResolver(Protocol):
    """Resolve an accessible resource only for an explicit runtime capability."""

    async def inspect(self, resource: ResourceRef) -> dict[str, Any]: ...

    async def read(self, resource: ResourceRef, *, max_characters: int) -> str: ...

    async def materialize(self, resource: ResourceRef) -> tuple[ModelContent, ...]: ...


class ExecutionCapabilityResolver(Protocol):
    """Resolve hosted-execution support for the provider and model of one step."""

    def resolve(
        self, *, provider: str, model: str | None
    ) -> ExecutionCapability: ...


class SandboxRuntime(Protocol):
    """Request-scoped sandbox actions available to the generic agent loop."""

    async def configure_execution(
        self, capability: ExecutionCapability
    ) -> ExecutionCapability: ...

    async def observe_execution(self, items: tuple[Item, ...]) -> None: ...

    async def materialize_resource(
        self, resource: ResourceRef
    ) -> SandboxMaterialization: ...

    async def promote_file(self, file_name: str, *, summary: str) -> SandboxArtifact: ...

    @property
    def artifact_ids(self) -> tuple[str, ...]: ...


if TYPE_CHECKING:
    from bothesis.observability import Tracer


class AgentExecutionError(RuntimeError):
    """The agent could not safely complete a request."""


AgentStreamEvent: TypeAlias = ResponseStreamEvent | RuntimeActivityEvent


@dataclass(frozen=True, slots=True)
class SessionConfiguration:
    """Static configuration shared by every turn in one runtime session."""

    model: str | None = None
    temperature: float | None = None
    max_tokens: int | None = None
    max_model_turns: int = 12
    max_tool_rounds: int = 8
    max_tool_calls: int = 6
    max_history_messages: int = 24
    max_history_characters: int = 24_000
    recent_history_messages: int = 6
    max_tool_result_characters: int = 10_000
    max_tool_context_characters: int = 12_000
    max_user_message_characters: int = 4_000
    # Wraps each tool execution, so it must stay above a tool's own budget
    # (knowledge_search allows 25s) or the executor cancels before the tool can
    # report its own timeout outcome.
    tool_timeout_seconds: float = 30.0
    max_sampling_retries: int = 2
    sampling_retry_base_delay_seconds: float = 0.5

    def __post_init__(self) -> None:
        if self.max_model_turns < 1:
            raise ValueError("max_model_turns must be at least one")
        if self.max_tool_rounds < 0:
            raise ValueError("max_tool_rounds must be non-negative")
        if self.max_tool_rounds >= self.max_model_turns:
            raise ValueError("max_tool_rounds must be lower than max_model_turns")
        if self.max_tool_calls < 1:
            raise ValueError("max_tool_calls must be at least one")
        if (
            min(
                self.max_history_messages,
                self.max_history_characters,
                self.recent_history_messages,
                self.max_tool_result_characters,
                self.max_tool_context_characters,
                self.max_user_message_characters,
            )
            < 1
        ):
            raise ValueError("agent context limits must be at least one")
        if self.recent_history_messages > self.max_history_messages:
            raise ValueError("recent conversation messages exceed the history limit")
        if self.tool_timeout_seconds <= 0:
            raise ValueError("tool timeout must be greater than zero")
        if self.max_tokens is not None and self.max_tokens < 1:
            raise ValueError("max_tokens must be at least one")
        if self.max_sampling_retries < 0:
            raise ValueError("max_sampling_retries must be non-negative")
        if self.sampling_retry_base_delay_seconds <= 0:
            raise ValueError("sampling_retry_base_delay_seconds must be greater than zero")


@dataclass(frozen=True, slots=True)
class ConversationWindow:
    """A bounded history split into compressible and recent messages."""

    older_messages: tuple[ConversationMessage, ...]
    recent_messages: tuple[ConversationMessage, ...]

    @property
    def messages(self) -> tuple[ConversationMessage, ...]:
        return (*self.older_messages, *self.recent_messages)

    def older_payload(self) -> list[dict[str, str]]:
        return _message_payload(self.older_messages)

    def older_json(self) -> str:
        return _compact_json(self.older_payload())


@dataclass(slots=True)
class ConversationState:
    """The one ordered, model-visible interaction history for an active turn."""

    items: tuple[Item, ...] = ()
    initial_item_count: int = 0

    @property
    def initialized(self) -> bool:
        return self.initial_item_count > 0

    @property
    def observations(self) -> tuple[Item, ...]:
        """Tool outputs acquired during this turn, in interaction order."""

        return tuple(
            item
            for item in self.items
            if isinstance(item, (FunctionCallOutputItem, HostedExecutionResultItem))
        )

    def initialize(self, items: tuple[Item, ...]) -> None:
        if self.initialized:
            return
        self.items = items
        self.initial_item_count = len(items)

    def record(self, items: tuple[Item, ...]) -> None:
        self.items = (*self.items, *items)


@dataclass(frozen=True, slots=True)
class SessionServices:
    """Session-scoped dependencies; these never become model context."""

    model: object
    tool_registry: object
    resource_resolver: ResourceResolver | None = None
    execution_capability_resolver: ExecutionCapabilityResolver | None = None
    sandbox_runtime: SandboxRuntime | None = None
    tracer: Tracer | None = None


@dataclass(frozen=True, slots=True)
class ResolvedStepSettings:
    """Exact model and sampling settings used by one sampling request."""

    model: str | None
    temperature: float | None
    max_output_tokens: int | None
    parallel_tool_calls: bool
    provider_options: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class TurnEnvironmentSnapshot:
    """Stable request environment captured for a sampling step."""

    agent_context: AgentContext


@dataclass(slots=True)
class TurnContext:
    """Mutable runtime state for one user-initiated agent turn.

    This state is deliberately broader than a model request. ContextManager
    selects and compacts it into an immutable StepContext before every sample.
    """

    user_turn: UserTurn
    environment: TurnEnvironmentSnapshot
    initial_settings: ResolvedStepSettings
    current_settings: ResolvedStepSettings
    id: str = field(default_factory=lambda: f"turn_{uuid4().hex}")
    model_iteration: int = 0
    tool_round: int = 0
    tool_call_count: int = 0
    model_duration_ms: int = 0
    tool_duration_ms: int = 0
    resources: tuple[ResourceRef, ...] = ()
    evidence: dict[str, Evidence] = field(default_factory=dict)
    used_evidence_ids: set[str] = field(default_factory=set)
    executed_tool_signatures: set[str] = field(default_factory=set)
    references: CitationReferences = field(default_factory=CitationReferences)


@dataclass(frozen=True, slots=True)
class StepContext:
    """Immutable runtime snapshot used to build exactly one model request."""

    turn_id: str
    step_index: int
    settings: ResolvedStepSettings
    execution_capability: ExecutionCapability
    resources: tuple[ResourceRef, ...]
    tool_names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelInput:
    """The exact provider-neutral context materialized for one sampling step."""

    turn_id: str
    step_index: int
    settings: ResolvedStepSettings
    execution_capability: ExecutionCapability
    instructions: str
    input_items: tuple[Item, ...]
    tools: tuple[Tool, ...]

    def prompt(self, *, previous_response_id: str | None) -> Prompt:
        """Project the materialized agent context onto the transport contract."""

        return Prompt(
            input=self.input_items,
            model=self.settings.model,
            instructions=self.instructions,
            tools=self.tools,
            execution_capability=self.execution_capability,
            tool_choice=(
                "auto"
                if self.tools or self.execution_capability.hosted_shell
                else None
            ),
            parallel_tool_calls=(
                self.settings.parallel_tool_calls
                if self.tools or self.execution_capability.hosted_shell
                else None
            ),
            temperature=self.settings.temperature,
            max_output_tokens=self.settings.max_output_tokens,
            previous_response_id=previous_response_id,
            provider_options=self.settings.provider_options,
        )


def duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1_000)


def _compact_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _message_payload(
    messages: tuple[ConversationMessage, ...],
) -> list[dict[str, str]]:
    return [{"role": message.role, "content": message.content} for message in messages]


# Import primary runtime classes only after the shared package contracts exist.
from bothesis.agent.context_manager import ContextManager  # noqa: E402
from bothesis.agent.session import Session  # noqa: E402
from bothesis.agent.agent import Agent  # noqa: E402

__all__ = [
    "Agent",
    "AgentExecutionError",
    "AgentStreamEvent",
    "ConversationState",
    "ConversationWindow",
    "ContextManager",
    "ExecutionCapability",
    "ExecutionCapabilityResolver",
    "AttachmentInput",
    "AttachmentRef",
    "ImageInput",
    "ModelContent",
    "ModelInput",
    "ResourceInput",
    "ResourceRef",
    "ResourceResolver",
    "SandboxArtifact",
    "SandboxMaterialization",
    "SandboxRuntime",
    "ResolvedStepSettings",
    "Session",
    "SessionConfiguration",
    "SessionServices",
    "StepContext",
    "TurnContext",
    "TurnEnvironmentSnapshot",
    "TextInput",
    "UserInput",
    "UserTurn",
    "duration_ms",
]
