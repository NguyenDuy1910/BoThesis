"""Typed execution for optional structured agent capabilities."""

from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass
from time import perf_counter
from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bothesis.agent.models import AgentContext
from bothesis.agent.prompts.template_render import render_chat_base, render_prompt
from bothesis.agent.transports.base import LLMResponse, LLMTransport, LLMTransportError
from bothesis.observability import LangfuseTracing


class _CapabilityModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ConversationCompression(_CapabilityModel):
    summary: str = Field(min_length=1, max_length=4_000)


OutputModel = TypeVar("OutputModel", bound=_CapabilityModel)


class CapabilityExecutionError(RuntimeError):
    """A capability response could not be completed or validated."""


@dataclass(frozen=True, slots=True)
class CapabilityResult(Generic[OutputModel]):
    value: OutputModel
    response: LLMResponse
    duration_ms: int


class StructuredCapabilityExecutor:
    """Render an optional capability and normalize its structured response."""

    def __init__(
        self,
        transport: LLMTransport,
        *,
        tracing: LangfuseTracing | None = None,
        model: str | None = None,
        max_tokens: int = 1_200,
    ) -> None:
        if max_tokens < 1:
            raise ValueError("max_tokens must be at least one")
        self._transport = transport
        self._tracing = tracing
        self._model = model
        self._max_tokens = max_tokens

    def render(self, capability: str, /, **values: object) -> str:
        return render_prompt(capability, **values)

    def model_messages(self, capability_prompt: str) -> list[dict[str, str]]:
        """Build the common system context plus one focused capability prompt."""

        return [
            {"role": "system", "content": render_chat_base()},
            {"role": "user", "content": capability_prompt},
        ]

    async def structured(
        self,
        capability: str,
        output_model: type[OutputModel],
        *,
        values: dict[str, object],
        ctx: AgentContext,
        step: int,
        retrieval_round: int = 0,
        retrieval_query_count: int = 0,
    ) -> CapabilityResult[OutputModel]:
        prompt = self.render(capability, **values)
        messages = self.model_messages(prompt)
        started_at = perf_counter()
        trace_context = (
            self._tracing.capability(
                capability=capability,
                messages=messages,
                ctx=ctx,
                step=step,
                retrieval_round=retrieval_round,
                retrieval_query_count=retrieval_query_count,
            )
            if self._tracing is not None
            else nullcontext(None)
        )
        with trace_context as trace:
            try:
                response = await self._transport.complete(
                    messages,
                    model=self._model,
                    max_tokens=self._max_tokens,
                    response_format={"type": "json_object"},
                )
            except LLMTransportError as exc:
                if trace is not None:
                    trace.fail(
                        category="transport_error",
                        duration_ms=_duration_ms(started_at),
                    )
                raise CapabilityExecutionError(
                    f"{capability} model request failed"
                ) from exc

            duration_ms = _duration_ms(started_at)
            try:
                value = output_model.model_validate_json(
                    _json_response_text(response.content)
                )
            except (ValueError, ValidationError) as exc:
                if trace is not None:
                    trace.fail(
                        category="invalid_response",
                        duration_ms=duration_ms,
                        response=response,
                        output=response.content,
                    )
                raise CapabilityExecutionError(
                    f"{capability} returned an invalid response"
                ) from exc
            if trace is not None:
                trace.complete(
                    response=response,
                    output=value.model_dump(mode="json"),
                    duration_ms=duration_ms,
                )
            return CapabilityResult(
                value=value,
                response=response,
                duration_ms=duration_ms,
            )


def _json_response_text(content: str | None) -> str:
    if content is None:
        raise ValueError("empty model response")
    text = content.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3 and lines[-1].strip() == "```":
            text = "\n".join(lines[1:-1])
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:].lstrip()
    if not text:
        raise ValueError("empty model response")
    return text


def _duration_ms(started_at: float) -> int:
    return round((perf_counter() - started_at) * 1_000)


__all__ = [
    "CapabilityExecutionError",
    "CapabilityResult",
    "ConversationCompression",
    "StructuredCapabilityExecutor",
]
