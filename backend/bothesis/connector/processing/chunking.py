"""Docling-owned structural and token-aware chunking."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, Literal

from docling.chunking import HybridChunker
from docling_core.transforms.chunker.line_chunker import LineBasedTokenChunker
from docling_core.types.doc import (
    CodeItem,
    DocItem,
    DocItemLabel,
    DoclingDocument,
    FormItem,
    KeyValueItem,
    PictureItem,
    SectionHeaderItem,
    TableCell,
    TableData,
    TableItem,
    TextItem,
    TitleItem,
)

from bothesis.connector.protocol import (
    AnyContentPart,
    BoundingBox,
    Chunk,
    CitationInfo,
    CitationSpan,
    CodePart,
    DocumentItem,
    ImagePart,
    LinkPart,
    StructuredPart,
    TablePart,
    TextPart,
)

from . import ApproximateTokenizer, DoclingChunkingError
from .mapper import (
    _caption_refs,
    _docling_item_text,
    _element_id,
    _heading_paths,
    _item_kind,
    _normalized_bbox,
)


ChunkStrategy = Literal["hybrid", "line"]


class DoclingChunker:
    """Map Docling chunk output into connector-owned evidence chunks."""

    def __init__(
        self,
        *,
        tokenizer: Any | None = None,
        hybrid_chunker: Any | None = None,
        line_chunker: Any | None = None,
    ) -> None:
        self._tokenizer = tokenizer or ApproximateTokenizer()
        self._hybrid_chunker = hybrid_chunker
        self._line_chunker = line_chunker

    def chunk(
        self,
        document: DoclingDocument,
        *,
        item_id: str,
        strategy: ChunkStrategy = "hybrid",
    ) -> list[Chunk]:
        return self._chunk_document(
            document,
            item_id=item_id,
            strategy=strategy,
            source_parts=None,
        )

    def chunk_item(
        self,
        item: DocumentItem,
        *,
        strategy: ChunkStrategy = "hybrid",
    ) -> list[Chunk]:
        """Chunk source-native canonical content through Docling's engine."""

        document, source_parts = _document_from_item(item)
        return self._chunk_document(
            document,
            item_id=item.id,
            strategy=strategy,
            source_parts=source_parts,
        )

    def _chunk_document(
        self,
        document: DoclingDocument,
        *,
        item_id: str,
        strategy: ChunkStrategy,
        source_parts: dict[str, AnyContentPart] | None,
    ) -> list[Chunk]:
        chunker = self._resolve_chunker(strategy)
        try:
            docling_chunks = (
                _line_chunks(document, chunker)
                if strategy == "line" and hasattr(chunker, "chunk_text")
                else list(chunker.chunk(document))
            )
        except Exception as exc:
            raise DoclingChunkingError(
                f"Docling {strategy} chunking failed for {item_id}"
            ) from exc

        heading_paths = _heading_paths(document)
        output: list[Chunk] = []
        for docling_chunk in docling_chunks:
            chunk_text = str(getattr(docling_chunk, "text", ""))
            if not chunk_text.strip():
                continue
            doc_items = _chunk_items(document, docling_chunk)
            spans, included_items = _citation_spans(
                document,
                doc_items,
                chunk_text=chunk_text,
                source_parts=source_parts,
            )
            section_path = _chunk_section_path(
                docling_chunk,
                included_items or doc_items,
                heading_paths=heading_paths,
                source_parts=source_parts,
            )
            index = len(output)
            output.append(
                Chunk(
                    id=f"{item_id}:{index}",
                    item_id=item_id,
                    chunk_index=index,
                    chunk_text=chunk_text,
                    content_type=_content_type(included_items or doc_items),
                    section_path=list(section_path),
                    citation=CitationInfo(
                        section=section_path[-1] if section_path else None,
                        section_path=section_path,
                        spans=tuple(spans),
                    ),
                )
            )
        if not output:
            raise DoclingChunkingError(f"Document {item_id!r} has no indexable content")
        return output

    def _resolve_chunker(self, strategy: ChunkStrategy) -> Any:
        if strategy == "hybrid":
            if self._hybrid_chunker is None:
                arguments: dict[str, Any] = {"repeat_table_header": True}
                arguments["tokenizer"] = self._tokenizer
                self._hybrid_chunker = HybridChunker(**arguments)
            return self._hybrid_chunker
        if strategy == "line":
            if self._line_chunker is None:
                arguments = {}
                arguments["tokenizer"] = self._tokenizer
                self._line_chunker = LineBasedTokenChunker(**arguments)
            return self._line_chunker
        raise ValueError(f"Unknown Docling chunk strategy: {strategy}")


def _document_from_item(
    item: DocumentItem,
) -> tuple[DoclingDocument, dict[str, AnyContentPart]]:
    document = DoclingDocument(name=item.title)
    source_parts: dict[str, AnyContentPart] = {}
    active_path: tuple[str, ...] = ()
    for part in item.content:
        path = tuple(part.section_path)
        active_path = _emit_heading_transition(document, active_path, path)
        doc_item = _add_part(document, part)
        if doc_item is not None:
            source_parts[doc_item.self_ref] = part
    return document, source_parts


def _emit_heading_transition(
    document: DoclingDocument,
    active_path: tuple[str, ...],
    target_path: tuple[str, ...],
) -> tuple[str, ...]:
    if target_path == active_path:
        return active_path
    common = 0
    for left, right in zip(active_path, target_path, strict=False):
        if left != right:
            break
        common += 1
    start = common
    if target_path and common == len(target_path) < len(active_path):
        start = len(target_path) - 1
    for index in range(start, len(target_path)):
        document.add_heading(text=target_path[index], level=index + 1)
    return target_path


def _add_part(document: DoclingDocument, part: AnyContentPart) -> DocItem | None:
    if isinstance(part, TextPart):
        return document.add_text(label=DocItemLabel.TEXT, text=part.text)
    if isinstance(part, CodePart):
        return document.add_code(text=part.code)
    if isinstance(part, TablePart):
        caption = (
            document.add_text(label=DocItemLabel.CAPTION, text=part.caption)
            if part.caption
            else None
        )
        return document.add_table(data=_table_data(part), caption=caption)
    if isinstance(part, ImagePart):
        image_text = _canonical_part_text(part)
        caption = (
            document.add_text(label=DocItemLabel.CAPTION, text=image_text)
            if image_text
            else None
        )
        return document.add_picture(caption=caption)
    if isinstance(part, StructuredPart):
        return document.add_text(
            label=DocItemLabel.TEXT,
            text=_canonical_part_text(part),
        )
    if isinstance(part, LinkPart):
        return document.add_text(
            label=DocItemLabel.TEXT,
            text=_canonical_part_text(part),
        )
    return None


def _table_data(part: TablePart) -> TableData:
    values = [part.columns, *part.rows] if part.columns else list(part.rows)
    column_count = max((len(row) for row in values), default=0)
    cells: list[TableCell] = []
    for row_index, row in enumerate(values):
        for column_index in range(column_count):
            cells.append(
                TableCell(
                    start_row_offset_idx=row_index,
                    end_row_offset_idx=row_index + 1,
                    start_col_offset_idx=column_index,
                    end_col_offset_idx=column_index + 1,
                    text=row[column_index] if column_index < len(row) else "",
                    column_header=bool(part.columns) and row_index == 0,
                )
            )
    return TableData(
        table_cells=cells,
        num_rows=len(values),
        num_cols=column_count,
    )


def _chunk_items(document: DoclingDocument, chunk: Any) -> list[DocItem]:
    meta = getattr(chunk, "meta", None)
    output: list[DocItem] = []
    seen: set[str] = set()
    for item in getattr(meta, "doc_items", None) or []:
        if not isinstance(item, DocItem) or item.self_ref in seen:
            continue
        try:
            resolved = item.get_ref().resolve(document)
        except (KeyError, IndexError, ValueError):
            resolved = item
        if isinstance(resolved, DocItem):
            seen.add(resolved.self_ref)
            output.append(resolved)
    return output


def _line_chunks(document: DoclingDocument, chunker: Any) -> list[Any]:
    """Run Docling's line splitter per stable source element.

    ``LineBasedTokenChunker.chunk`` intentionally associates every output with
    every serialized document item.  Processing one item at a time retains an
    unambiguous element reference while still delegating token-aware line
    splitting to Docling.
    """

    output: list[Any] = []
    paths = _heading_paths(document)
    excluded_refs = _caption_refs(document)
    for item, _ in document.iterate_items(traverse_pictures=False):
        if (
            not isinstance(item, DocItem)
            or isinstance(item, (TitleItem, SectionHeaderItem))
            or item.self_ref in excluded_refs
        ):
            continue
        source_text = _docling_item_text(document, item)
        if not source_text.strip():
            continue
        lines = source_text.splitlines(keepends=True) or [source_text]
        for text in chunker.chunk_text(lines=lines):
            output.append(
                SimpleNamespace(
                    text=text,
                    meta=SimpleNamespace(
                        doc_items=[item],
                        headings=list(paths.get(item.self_ref, ())) or None,
                    ),
                )
            )
    return output


def _citation_spans(
    document: DoclingDocument,
    doc_items: list[DocItem],
    *,
    chunk_text: str,
    source_parts: dict[str, AnyContentPart] | None,
) -> tuple[list[CitationSpan], list[DocItem]]:
    spans: list[CitationSpan] = []
    included_items: list[DocItem] = []
    for doc_item in doc_items:
        source_part = (
            source_parts.get(doc_item.self_ref) if source_parts is not None else None
        )
        if source_parts is not None and source_part is None:
            continue
        source_text = (
            _canonical_part_text(source_part)
            if source_part is not None
            else _docling_item_text(document, doc_item)
        )
        # Docling's chunk metadata is the authoritative item association.  A
        # local range is trustworthy only when the chunk is exactly the one
        # item's source serialization.  Split chunks, repeated table headers,
        # and repeated text deliberately retain element/page/bbox provenance
        # without a guessed offset.
        exact_item_text = len(doc_items) == 1 and chunk_text == source_text
        item_spans = (
            _canonical_spans(
                doc_item,
                source_part,
                source_text=source_text,
                exact_item_text=exact_item_text,
            )
            if source_part is not None
            else _docling_spans(
                document,
                doc_item,
                source_text=source_text,
                exact_item_text=exact_item_text,
            )
        )
        if item_spans:
            included_items.append(doc_item)
            spans.extend(item_spans)
    return _deduplicated_spans(spans), included_items


def _canonical_spans(
    doc_item: DocItem,
    part: AnyContentPart,
    *,
    source_text: str,
    exact_item_text: bool,
) -> list[CitationSpan]:
    element_id = part.element_id or _element_id(doc_item, page=part.page)
    return [
        CitationSpan(
            page=part.page,
            element_id=element_id,
            start_offset=0 if exact_item_text and source_text else None,
            end_offset=len(source_text) if exact_item_text and source_text else None,
            bounding_box=part.bounding_box,
        )
    ]


def _docling_spans(
    document: DoclingDocument,
    doc_item: DocItem,
    *,
    source_text: str,
    exact_item_text: bool,
) -> list[CitationSpan]:
    first_page = doc_item.prov[0].page_no if doc_item.prov else None
    element_id = _element_id(doc_item, page=first_page)
    if not doc_item.prov:
        return [
            CitationSpan(
                element_id=element_id,
                start_offset=0 if exact_item_text and source_text else None,
                end_offset=len(source_text) if exact_item_text and source_text else None,
            )
        ]

    output: list[CitationSpan] = []
    for provenance in doc_item.prov:
        start, end = provenance.charspan
        has_direct_range = exact_item_text and start >= 0 and end > start
        output.append(
            CitationSpan(
                page=provenance.page_no,
                element_id=element_id,
                start_offset=start if has_direct_range else None,
                end_offset=end if has_direct_range else None,
                bounding_box=_normalized_bbox(
                    document,
                    page=provenance.page_no,
                    bbox=provenance.bbox,
                ),
            )
        )
    return output


def _deduplicated_spans(spans: list[CitationSpan]) -> list[CitationSpan]:
    output: list[CitationSpan] = []
    seen: set[str] = set()
    for span in spans:
        key = span.model_dump_json()
        if key not in seen:
            seen.add(key)
            output.append(span)
    return output


def _chunk_section_path(
    chunk: Any,
    doc_items: list[DocItem],
    *,
    heading_paths: dict[str, tuple[str, ...]],
    source_parts: dict[str, AnyContentPart] | None,
) -> tuple[str, ...]:
    if source_parts is not None:
        for doc_item in doc_items:
            part = source_parts.get(doc_item.self_ref)
            if part is not None and part.section_path:
                return tuple(part.section_path)
    headings = getattr(getattr(chunk, "meta", None), "headings", None)
    if headings:
        return tuple(str(value) for value in headings if str(value).strip())
    for doc_item in doc_items:
        if path := heading_paths.get(doc_item.self_ref):
            return path
    return ()


def _content_type(doc_items: list[DocItem]) -> str:
    kinds = {
        "table"
        if isinstance(item, TableItem)
        else "image"
        if isinstance(item, PictureItem)
        else "code"
        if isinstance(item, CodeItem)
        else "structured"
        if isinstance(item, (KeyValueItem, FormItem))
        else "text"
        for item in doc_items
    }
    if not kinds:
        return "text"
    return next(iter(kinds)) if len(kinds) == 1 else "mixed"


def _canonical_part_text(part: AnyContentPart) -> str:
    if isinstance(part, TextPart):
        return part.text
    if isinstance(part, CodePart):
        return part.code
    if isinstance(part, TablePart):
        rows = [part.columns, *part.rows] if part.columns else part.rows
        table = "\n".join(" | ".join(cell for cell in row) for row in rows)
        return "\n".join(value for value in (part.caption, table) if value)
    if isinstance(part, ImagePart):
        values = (part.alt_text, part.ocr_text, part.description)
        semantic_text = "\n".join(
            value for value in dict.fromkeys(values) if value and value.strip()
        )
        return semantic_text or (part.url or "")
    if isinstance(part, StructuredPart):
        return json.dumps(
            part.data,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
    if isinstance(part, LinkPart):
        return f"{part.title}: {part.url}" if part.title else part.url
    return ""


__all__ = ["ChunkStrategy", "DoclingChunker"]
