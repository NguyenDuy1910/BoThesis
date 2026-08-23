"""Map Docling documents into canonical connector items."""

from __future__ import annotations

import hashlib
import re
from typing import Any

from docling_core.types.doc import (
    CodeItem,
    DescriptionAnnotation,
    DocItem,
    DoclingDocument,
    FormItem,
    FormulaItem,
    KeyValueItem,
    PictureItem,
    SectionHeaderItem,
    TableItem,
    TextItem,
    TitleItem,
)

from bothesis.connector.protocol import (
    AccessPolicy,
    BoundingBox,
    CodePart,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    ImagePart,
    SourceIdentity,
    StorageObject,
    StructuredPart,
    TablePart,
    TextPart,
)


class DocumentMapper:
    """Convert one Docling document without leaking Docling-owned models."""

    def to_item(
        self,
        document: DoclingDocument,
        *,
        item_id: str,
        title: str,
        source: SourceIdentity,
        document_kind: DocumentKind,
        access: AccessPolicy | None = None,
        hierarchy: Hierarchy | None = None,
        metadata: dict[str, str | list[str]] | None = None,
        original: StorageObject | None = None,
    ) -> DocumentItem:
        caption_refs = _caption_refs(document)
        heading_paths = _heading_paths(document)
        content = []
        for item, _ in document.iterate_items(traverse_pictures=False):
            if not isinstance(item, DocItem) or item.self_ref in caption_refs:
                continue
            part = self._part(
                document,
                item,
                section_path=heading_paths.get(item.self_ref, ()),
                caption_refs=caption_refs,
            )
            if part is not None:
                content.append(part)

        return DocumentItem(
            id=item_id,
            title=title,
            source=source,
            document_kind=document_kind,
            access=access or AccessPolicy(),
            hierarchy=hierarchy or Hierarchy(),
            metadata=metadata or {},
            content=content,
            original=original,
        )

    def _part(
        self,
        document: DoclingDocument,
        item: DocItem,
        *,
        section_path: tuple[str, ...],
        caption_refs: set[str],
    ) -> TextPart | TablePart | ImagePart | CodePart | StructuredPart | None:
        page, bounding_box = _primary_provenance(document, item)
        common = {
            "element_id": _element_id(item, page=page),
            "page": page,
            "section": section_path[-1] if section_path else None,
            "section_path": section_path,
            "bounding_box": bounding_box,
        }

        # CodeItem is also a TextItem, so concrete specializations must be
        # checked before the generic text branch.
        if isinstance(item, CodeItem):
            language = getattr(item.code_language, "value", str(item.code_language))
            return CodePart(
                code=item.text,
                language=None if language.casefold() == "unknown" else language,
                **common,
            )
        if isinstance(item, FormulaItem):
            return TextPart(text=item.text, **common)
        if isinstance(item, TextItem):
            hyperlink = str(item.hyperlink) if item.hyperlink is not None else None
            return TextPart(text=item.text, link=hyperlink, **common)
        if isinstance(item, TableItem):
            columns, rows = _table_values(item)
            return TablePart(
                columns=columns,
                rows=rows,
                caption=_clean_text(item.caption_text(document)),
                **common,
            )
        if isinstance(item, PictureItem):
            caption, ocr_text, description = _picture_values(
                document,
                item,
                caption_refs=caption_refs,
            )
            return ImagePart(
                url=_external_image_url(item),
                alt_text=caption,
                ocr_text=ocr_text,
                description=description,
                **common,
            )
        if isinstance(item, (KeyValueItem, FormItem)):
            return StructuredPart(
                data={
                    "docling_label": _item_label(item),
                    "value": item.model_dump(
                        mode="json",
                        exclude={"self_ref", "parent", "children", "prov"},
                        exclude_none=True,
                    ),
                },
                **common,
            )
        return None


def _caption_refs(document: DoclingDocument) -> set[str]:
    refs: set[str] = set()
    for item in [*document.tables, *document.pictures]:
        refs.update(ref.cref for ref in item.captions)
    return refs


def _heading_paths(document: DoclingDocument) -> dict[str, tuple[str, ...]]:
    paths: dict[str, tuple[str, ...]] = {}
    headings: list[str] = []
    for item, _ in document.iterate_items(traverse_pictures=False):
        if not isinstance(item, DocItem):
            continue
        if isinstance(item, TitleItem):
            headings = [item.text.strip()] if item.text.strip() else []
        elif isinstance(item, SectionHeaderItem):
            heading = item.text.strip()
            if heading:
                level = max(1, item.level)
                headings = headings[: level - 1]
                headings.append(heading)
        paths[item.self_ref] = tuple(headings)
    return paths


def _element_id(item: DocItem, *, page: int | None = None) -> str:
    kind = _item_kind(item)
    index_match = re.search(r"/(\d+)$", item.self_ref)
    if index_match is not None:
        sequence = f"{int(index_match.group(1)) + 1:03d}"
    else:
        sequence = hashlib.sha256(item.self_ref.encode("utf-8")).hexdigest()[:10]
    location = f"p{page:03d}" if page is not None else "doc"
    return f"{location}_{kind}_{sequence}"


def _item_kind(item: DocItem) -> str:
    if isinstance(item, CodeItem):
        return "code"
    if isinstance(item, FormulaItem):
        return "formula"
    if isinstance(item, (TitleItem, SectionHeaderItem)):
        return "heading"
    if isinstance(item, TableItem):
        return "table"
    if isinstance(item, PictureItem):
        return "image"
    if isinstance(item, (KeyValueItem, FormItem)):
        return "structured"
    return "para"


def _primary_provenance(
    document: DoclingDocument,
    item: DocItem,
) -> tuple[int | None, BoundingBox | None]:
    if not item.prov:
        return None, None
    provenance = item.prov[0]
    return provenance.page_no, _normalized_bbox(
        document,
        page=provenance.page_no,
        bbox=provenance.bbox,
    )


def _normalized_bbox(
    document: DoclingDocument,
    *,
    page: int,
    bbox: Any,
) -> BoundingBox | None:
    page_item = document.pages.get(page)
    if page_item is None or page_item.size.width <= 0 or page_item.size.height <= 0:
        return None
    top_left = bbox.to_top_left_origin(page_item.size.height)
    left = max(0.0, min(1.0, top_left.l / page_item.size.width))
    top = max(0.0, min(1.0, top_left.t / page_item.size.height))
    right = max(0.0, min(1.0, top_left.r / page_item.size.width))
    bottom = max(0.0, min(1.0, top_left.b / page_item.size.height))
    if right <= left or bottom <= top:
        return None
    return BoundingBox(
        x=left,
        y=top,
        width=right - left,
        height=bottom - top,
    )


def _table_values(item: TableItem) -> tuple[list[str], list[list[str]]]:
    grid = item.data.grid
    if not grid:
        return [], []
    values = [[cell.text for cell in row] for row in grid]
    header_rows = 0
    for row in grid:
        if row and any(cell.column_header for cell in row):
            header_rows += 1
        else:
            break
    if not header_rows:
        return [], values

    width = max(len(row) for row in values)
    columns: list[str] = []
    for column_index in range(width):
        pieces: list[str] = []
        for row in values[:header_rows]:
            value = row[column_index].strip() if column_index < len(row) else ""
            if value and (not pieces or pieces[-1] != value):
                pieces.append(value)
        columns.append(" / ".join(pieces))
    return columns, values[header_rows:]


def _picture_values(
    document: DoclingDocument,
    item: PictureItem,
    *,
    caption_refs: set[str],
) -> tuple[str | None, str | None, str | None]:
    caption = _clean_text(item.caption_text(document))
    ocr_values: list[str] = []
    for child, _ in document.iterate_items(root=item, traverse_pictures=True):
        if (
            child is not item
            and isinstance(child, TextItem)
            and child.self_ref not in caption_refs
            and child.text.strip()
        ):
            ocr_values.append(child.text.strip())
    descriptions = [
        annotation.text.strip()
        for annotation in item.__dict__.get("annotations", ())
        if isinstance(annotation, DescriptionAnnotation) and annotation.text.strip()
    ]
    return (
        caption,
        _clean_text("\n".join(dict.fromkeys(ocr_values))),
        _clean_text("\n".join(dict.fromkeys(descriptions))),
    )


def _external_image_url(item: PictureItem) -> str | None:
    if item.image is None:
        return None
    value = str(item.image.uri)
    return value if value.startswith(("https://", "http://")) else None


def _docling_item_text(document: DoclingDocument, item: DocItem) -> str:
    if isinstance(item, TableItem):
        return item.export_to_markdown(document)
    if isinstance(item, PictureItem):
        caption, ocr_text, description = _picture_values(
            document,
            item,
            caption_refs=_caption_refs(document),
        )
        return "\n".join(
            value for value in (caption, ocr_text, description) if value
        )
    if isinstance(item, TextItem):
        return item.text
    if isinstance(item, (KeyValueItem, FormItem)):
        import json

        return json.dumps(
            item.model_dump(mode="json", exclude_none=True),
            ensure_ascii=False,
            sort_keys=True,
        )
    return ""


def _item_label(item: DocItem) -> str:
    value = getattr(item, "label", type(item).__name__)
    return getattr(value, "value", str(value))


def _clean_text(value: str | None) -> str | None:
    normalized = (value or "").strip()
    return normalized or None


__all__ = ["DocumentMapper"]
