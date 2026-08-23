"""Docling conversion, normalization, provenance, and chunking."""


class DoclingProcessingError(ValueError):
    """Raised when a source cannot be converted into a Docling document."""


class DoclingChunkingError(ValueError):
    """Raised when a converted document has no valid Docling chunks."""


from .docling import DoclingProcessor  # noqa: E402
from .mapper import DocumentMapper  # noqa: E402
from .chunking import ChunkStrategy, DoclingChunker  # noqa: E402

__all__ = [
    "ChunkStrategy",
    "DoclingChunker",
    "DoclingChunkingError",
    "DoclingProcessingError",
    "DoclingProcessor",
    "DocumentMapper",
]
