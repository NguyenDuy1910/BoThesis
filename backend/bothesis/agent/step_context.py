"""The immutable snapshot one sampling request reasons about."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from bothesis.agent import AgentConfig
from bothesis.agent.models import AgentContext
from bothesis.agent.protocol import FunctionTool

if TYPE_CHECKING:
    from bothesis.agent.transports.openai import OpenAITransport
    from bothesis.agent.transports.openrouter import OpenRouterTransport
    from bothesis.agent.turn_input import TurnInput

Provider = Literal["openai", "openrouter"]


@dataclass(frozen=True, slots=True)
class ModelInfo:
    """Which model answers this Sampling Request, and how to reach it.

    ``provider`` decides wire format — OpenAI Responses API vs OpenRouter
    chat-completions — everywhere a Sampling Request renders history or
    parses a stream; ``name`` is the model id sent to that provider.
    """

    provider: Provider
    name: str


@dataclass(frozen=True, slots=True)
class StepContext:
    """One consistent view of everything a single Sampling Request needs.

    Captured fresh at the start of each ReAct iteration (decide → act →
    observe) so a provider retry replays the exact same request instead of
    racing against state that changed mid-turn (tool budgets, growing
    history, and so on). ``transport`` is deliberately not stored here — it
    is a stateful client, not data the model reasons about, and callers
    that need it (:func:`~bothesis.agent.sampling_request.run_sampling_request`)
    already receive it as a separate argument.
    """

    agent_context: AgentContext
    model_info: ModelInfo
    history: "TurnInput"
    tools: tuple[FunctionTool, ...]
    config: AgentConfig
    turn_number: int


def capture_step_context(
    *,
    agent_context: AgentContext,
    provider: Provider,
    transport: "OpenAITransport | OpenRouterTransport",
    history: "TurnInput",
    tools: tuple[FunctionTool, ...],
    config: AgentConfig,
    turn_number: int,
) -> StepContext:
    """Snapshot the state one sampling request will observe.

    ``transport`` is only consulted here to resolve the default model name;
    it is not part of the resulting snapshot.
    """

    return StepContext(
        agent_context=agent_context,
        model_info=ModelInfo(
            provider=provider,
            name=config.model or transport.model,
        ),
        history=history,
        tools=tools,
        config=config,
        turn_number=turn_number,
    )


__all__ = ["ModelInfo", "Provider", "StepContext", "capture_step_context"]
