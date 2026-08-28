"""Docling conversion, normalization, provenance, and chunking."""

from __future__ import annotations

from collections.abc import Callable
from math import ceil

from docling_core.transforms.chunker.tokenizer.base import BaseTokenizer


class DoclingProcessingError(ValueError):
    """Raised when a source cannot be converted into a Docling document."""


class DoclingChunkingError(ValueError):
    """Raised when a converted document has no valid Docling chunks."""


class ApproximateTokenizer(BaseTokenizer):
    """Bound chunk sizes without loading or downloading tokenizer model data."""

    max_tokens: int = 256
    utf8_bytes_per_token: int = 3

    def count_tokens(self, text: str) -> int:
        if not text:
            return 0
        return ceil(len(text.encode("utf-8")) / self.utf8_bytes_per_token)

    def get_max_tokens(self) -> int:
        return self.max_tokens

    def get_tokenizer(self) -> Callable[[str], int]:
        return self.count_tokens


from .docling import DoclingProcessor  # noqa: E402
from .mapper import DocumentMapper  # noqa: E402
from .chunking import ChunkStrategy, DoclingChunker  # noqa: E402

__all__ = [
    "ApproximateTokenizer",
    "ChunkStrategy",
    "DoclingChunker",
    "DoclingChunkingError",
    "DoclingProcessingError",
    "DoclingProcessor",
    "DocumentMapper",
]
