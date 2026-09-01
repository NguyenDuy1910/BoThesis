"""Provider communication and normalization — the only provider-aware layer.

A raw transport (:class:`~bothesis.agent.transports.openai.OpenAITransport`,
:class:`~bothesis.agent.transports.openrouter.OpenRouterTransport`) speaks its
provider's native API and nothing else: base URL, credentials, attribution
headers, and whatever extra APIs that provider offers.

Every supported provider serves ``POST /responses`` in OpenResponses format, so
one adapter — :class:`~bothesis.agent.transports.responses_adapter.ResponsesStream`
— is the whole normalization layer. It renders a
:class:`~bothesis.agent.protocol.ResponseRequest` into the native request and
projects native events onto canonical events, one native event at a time. There
is no per-provider reconstruction and no intermediate event vocabulary.

:func:`response_stream` is the single place in the process that resolves a
provider. Above this package nothing knows which provider answered.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any, Protocol, runtime_checkable

from bothesis import ModelResponseClient
from bothesis.agent.protocol import ResponseRequest, ResponseStreamEvent


@runtime_checkable
class ResponseStream(Protocol):
    """A provider that speaks the OpenResponses streaming contract."""

    provider: str
    model: str | None

    def stream(
        self, request: ResponseRequest
    ) -> AsyncIterator[ResponseStreamEvent]:
        """Yield canonical events for one sampling request, as they arrive."""
        ...


ResponseClient = ModelResponseClient


# The adapter is imported after the contract it implements exists.
from bothesis.agent.transports.responses_adapter import (  # noqa: E402
    ResponsesStream,
)
from bothesis.agent.transports.openai import OpenAITransport  # noqa: E402
from bothesis.agent.transports.openrouter import OpenRouterTransport  # noqa: E402

RESPONSES_PROVIDERS = frozenset({"openai", "openrouter"})
"""Providers whose ``/responses`` endpoint speaks OpenResponses format."""


def response_stream(transport: Any) -> ResponseStream:
    """Wrap one native transport in the canonical streaming contract.

    The allowlist is deliberate: a transport must be known to serve
    OpenResponses before the agent streams from it, so an unconfigured or
    chat-completions-only client fails loudly here instead of producing a
    half-mapped stream.
    """

    provider = getattr(transport, "provider", None)
    if not isinstance(provider, str) or provider not in RESPONSES_PROVIDERS:
        raise ValueError(f"unsupported model transport provider: {provider!r}")
    if not callable(getattr(transport, "stream_response", None)):
        raise ValueError(f"transport does not serve /responses: {provider}")
    return ResponsesStream(transport)


__all__ = [
    "RESPONSES_PROVIDERS",
    "OpenAITransport",
    "OpenRouterTransport",
    "ResponseClient",
    "ResponseStream",
    "ResponsesStream",
    "response_stream",
]
