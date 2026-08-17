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
class StepContext:
    """One consistent view of everything a single sampling request needs.

    Captured fresh at the start of each model iteration so a provider retry
    replays the exact same request instead of racing against state that
    changed mid-turn (tool budgets, growing history, and so on).
    """

    agent_context: AgentContext
    provider: Provider
    transport: "OpenAITransport | OpenRouterTransport"
    model: str | None
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
    """Snapshot the state one sampling request will observe."""

    return StepContext(
        agent_context=agent_context,
        provider=provider,
        transport=transport,
        model=config.model or transport.model,
        history=history,
        tools=tools,
        config=config,
        turn_number=turn_number,
    )


__all__ = ["Provider", "StepContext", "capture_step_context"]
