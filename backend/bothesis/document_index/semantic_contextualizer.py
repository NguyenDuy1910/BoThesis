"""LLM-backed, chunk-specific retrieval contextualization."""

from __future__ import annotations

from collections.abc import Sequence

from bothesis.agent.prompts.template_render import render_prompt
from bothesis.agent.transports.openrouter import OpenRouterTransport
from bothesis.connector.protocol import Chunk

_DISALLOWED_PREFIXES = ("document:", "section:", "context:", "description:")


class SemanticContextualizer:
    """Generate concise context while leaving canonical evidence untouched."""

    def __init__(
        self,
        transport: OpenRouterTransport,
        *,
        model_name: str | None = None,
        max_output_tokens: int = 128,
    ) -> None:
        if max_output_tokens < 1:
            raise ValueError("max_output_tokens must be at least one")
        self._transport = transport
        self._model_name = model_name
        self._max_output_tokens = max_output_tokens

    async def describe(
        self,
        chunk: Chunk,
        *,
        document_context: str,
        title: str | None = None,
        section_path: Sequence[str] = (),
    ) -> str | None:
        normalized_document_context = document_context.strip()
        if not normalized_document_context:
            raise ValueError("document_context must not be empty")
        prompt = render_prompt(
            "contextual_rag",
            document_title=title.strip() if title and title.strip() else "(not provided)",
            section_path=(
                " > ".join(value.strip() for value in section_path if value.strip())
                or "(not provided)"
            ),
            document_context=normalized_document_context,
            chunk_text=chunk.chunk_text,
        )
        response = await self._transport.responses(
            model=self._model_name,
            input=prompt,
            max_output_tokens=self._max_output_tokens,
            temperature=0,
        )
        value = getattr(response, "output_text", None)
        if not isinstance(value, str):
            raise ValueError("contextualization response does not contain text")
        normalized = value.strip()
        if not normalized:
            return None
        if normalized.casefold().startswith(_DISALLOWED_PREFIXES):
            raise ValueError("contextualization response contains a structural prefix")
        return normalized


__all__ = ["SemanticContextualizer"]
