"""LLM-backed second-stage ranking over permission-filtered candidates."""

from __future__ import annotations

import json
from collections.abc import Sequence

from bothesis import ModelResponseClient, render_prompt
from bothesis.document_index.models import ContextualChunk


class SemanticReranker:
    """Return a validated deterministic ordering selected by a model."""

    def __init__(
        self,
        transport: ModelResponseClient,
        *,
        model_name: str | None = None,
        max_output_tokens: int = 256,
        max_candidate_characters: int = 2_400,
    ) -> None:
        if max_output_tokens < 1 or max_candidate_characters < 1:
            raise ValueError("reranker limits must be greater than zero")
        self._transport = transport
        self._model_name = model_name
        self._max_output_tokens = max_output_tokens
        self._max_candidate_characters = max_candidate_characters

    async def rerank(
        self,
        chunks: Sequence[ContextualChunk],
        *,
        limit: int,
        query: str = "",
    ) -> list[ContextualChunk]:
        normalized_query = query.strip()
        if not normalized_query:
            raise ValueError("reranking query must not be empty")
        if limit < 1:
            raise ValueError("limit must be at least one")
        candidates = list(chunks)
        if not candidates:
            return []
        prompt = render_prompt(
            "retrieval_rerank",
            query=normalized_query,
            candidates=[self._candidate(chunk) for chunk in candidates],
            result_limit=min(limit, len(candidates)),
        )
        response = await self._transport.responses(
            model=self._model_name,
            input=prompt,
            max_output_tokens=self._max_output_tokens,
            temperature=0,
        )
        raw_text = getattr(response, "output_text", None)
        if not isinstance(raw_text, str):
            raise ValueError("reranker response does not contain text")
        ordered_ids = self._ordered_ids(raw_text, candidates)
        by_id = {chunk.id: chunk for chunk in candidates}
        ordered = [by_id[chunk_id] for chunk_id in ordered_ids]
        ordered.extend(chunk for chunk in candidates if chunk.id not in ordered_ids)
        selected = ordered[:limit]
        denominator = max(1, len(selected))
        return [
            chunk.model_copy(update={"rerank_score": (denominator - rank) / denominator})
            for rank, chunk in enumerate(selected)
        ]

    def _candidate(self, chunk: ContextualChunk) -> dict[str, object]:
        contextual_budget = self._max_candidate_characters * 2 // 3
        canonical_budget = self._max_candidate_characters - contextual_budget
        return {
            "chunk_id": chunk.id,
            "title": chunk.title,
            "section_path": chunk.context.section_path,
            "contextual_text": chunk.contextual_text[:contextual_budget],
            "chunk_text": chunk.chunk_text[:canonical_budget],
            "retrieval_score": chunk.relevance_score,
        }

    @staticmethod
    def _ordered_ids(
        raw_text: str,
        candidates: Sequence[ContextualChunk],
    ) -> list[str]:
        normalized = raw_text.strip()
        if normalized.startswith("```"):
            lines = normalized.splitlines()
            if len(lines) >= 3 and lines[-1].strip() == "```":
                normalized = "\n".join(lines[1:-1])
        value = json.loads(normalized)
        if not isinstance(value, dict) or set(value) != {"chunk_ids"}:
            raise ValueError("reranker response must contain only chunk_ids")
        chunk_ids = value["chunk_ids"]
        if not isinstance(chunk_ids, list) or not chunk_ids:
            raise ValueError("reranker chunk_ids must be a non-empty list")
        if any(not isinstance(chunk_id, str) for chunk_id in chunk_ids):
            raise ValueError("reranker chunk_ids must contain strings")
        if len(chunk_ids) != len(set(chunk_ids)):
            raise ValueError("reranker chunk_ids must be unique")
        allowed = {chunk.id for chunk in candidates}
        if not set(chunk_ids).issubset(allowed):
            raise ValueError("reranker returned an unknown chunk_id")
        return chunk_ids


__all__ = ["SemanticReranker"]
