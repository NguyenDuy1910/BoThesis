"""Typed contracts for normalized source resources."""

from .access import AccessEffect, AccessPolicy, AccessRule, DirectAccess, EffectiveAccess, Principal
from .changes import ChangeType, ItemChange
from .chunks import Chunk, ChunkContext, CitationInfo, CitationSpan, ContextualChunk
from .content import AnyContentPart, BoundingBox, CodePart, ImagePart, LinkPart, StructuredPart, TablePart, TextPart
from .hierarchy import Hierarchy
from .items import AnyItem, CollectionItem, CollectionKind, DocumentItem, DocumentKind, FileItem, Item
from .source import SourceIdentity, SourceProvider
from .storage import StorageObject, StorageProvider

__all__ = [
    "AccessEffect", "AccessPolicy", "AccessRule", "AnyContentPart", "AnyItem",
    "ChangeType", "Chunk", "ChunkContext", "CitationInfo", "CitationSpan", "CodePart", "CollectionItem", "CollectionKind", "ContextualChunk", "DirectAccess", "BoundingBox",
    "DocumentItem", "DocumentKind", "EffectiveAccess", "FileItem", "Hierarchy",
    "ImagePart", "Item", "ItemChange", "LinkPart", "Principal",
    "SourceIdentity", "SourceProvider", "StorageObject", "StorageProvider",
    "StructuredPart", "TablePart", "TextPart",
]
