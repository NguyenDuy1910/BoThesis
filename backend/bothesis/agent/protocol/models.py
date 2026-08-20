"""The semantic output of one Sampling Request.

The Turn Loop's decide step needs exactly two things once a Sampling Request
settles: whether the model asked for tools (so the Turn continues) and what
it said this round. ``SamplingRequestOutput`` derives both from a
:class:`~bothesis.agent.protocol.responses.Response` so call sites read them
directly instead of re-deriving ``response.function_calls`` /
``response.output_text`` at every decision point.
"""

from __future__ import annotations

from bothesis.agent.protocol import ProtocolModel, Response


class SamplingRequestOutput(ProtocolModel):
    """Whether this Sampling Request continues the Turn, and its message."""

    needs_follow_up: bool
    last_agent_message: str | None = None

    @classmethod
    def from_response(cls, response: Response) -> "SamplingRequestOutput":
        text = response.output_text.strip()
        return cls(
            needs_follow_up=bool(response.function_calls),
            last_agent_message=text or None,
        )


__all__ = ["SamplingRequestOutput"]
