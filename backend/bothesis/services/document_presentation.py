"""Shape durable Item records into the payloads knowledge callers consume."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from typing import Any, Callable

from bothesis.connector.protocol import (
    CitationInfo,
    SourceIdentity,
    SourceProvider,
)
from bothesis.services.preview import KnowledgePreview

log = logging.getLogger(__name__)


class DocumentPresenter:
    """Turn one Item into metadata, preview, and citation-ready payloads."""

    def __init__(
        self,
        *,
        object_storage: Callable[[], Any],
        preview: KnowledgePreview,
        citation_url_seconds: int,
        preview_url_seconds: int,
    ) -> None:
        self._object_storage = object_storage
        self._preview = preview
        self._citation_url_seconds = _bounded_seconds(citation_url_seconds)
        self._preview_url_seconds = _bounded_seconds(preview_url_seconds)

    def metadata(self, document: Any) -> dict[str, Any]:
        """Describe one uploaded document for the workspace document API."""

        upload = document.upload
        processing = document.metadata_.get("processing")
        return {
            "id": str(document.id),
            "parent_item_id": (
                str(document.parent_item_id) if document.parent_item_id else None
            ),
            "file_name": str(
                document.metadata_.get("file_name") or document.title or "document"
            ),
            "content_type": document.mime_type or "application/octet-stream",
            "size_bytes": document.size_bytes or 0,
            "status": document.status,
            "indexed": isinstance(processing, Mapping)
            and processing.get("index_schema_version") is not None,
            "upload_status": upload.status if upload is not None else None,
            "created_at": document.created_at.isoformat(),
            "uploaded_at": (
                upload.uploaded_at.isoformat()
                if upload is not None and upload.uploaded_at
                else None
            ),
            "preview": self.preview_payload(document),
        }

    def presigned_url(self, document: Any) -> str | None:
        """Presign the stored original, degrading to no link on failure."""

        if not document.storage_key:
            return None
        try:
            return self._object_storage().presign_download(
                document.storage_key,
                expires_seconds=self._citation_url_seconds,
            ).url
        except Exception:
            log.exception("could not generate citation document URL")
            return None

    def preview_payload(self, document: Any) -> dict[str, Any] | None:
        """Resolve a renderable preview, degrading to none on failure."""

        upload = getattr(document, "upload", None)
        if upload is not None and getattr(upload, "status", None) != "available":
            return None
        if getattr(document, "status", None) == "deleted":
            return None
        try:
            preview = self._preview.resolve(
                document, expires_seconds=self._preview_url_seconds
            )
        except Exception:
            log.exception("could not resolve knowledge preview")
            return None
        return preview.model_dump(mode="json") if preview is not None else None

    @staticmethod
    def upload_target(target: Any | None) -> dict[str, Any] | None:
        """Describe the presigned destination a client should upload to."""

        if target is None:
            return None
        request = target.request
        return {
            "mode": target.mode,
            "url": request.url,
            "method": request.method,
            "headers": dict(request.headers),
            "expires_at": request.expires_at.isoformat(),
        }

    @staticmethod
    def source_identity(document: Any) -> SourceIdentity:
        """Recover the lineage of an Item, falling back to native upload."""

        metadata = getattr(document, "metadata_", None)
        if isinstance(metadata, Mapping):
            canonical = metadata.get("canonical_item")
            source_value = (
                canonical.get("source")
                if isinstance(canonical, Mapping)
                else metadata.get("source")
            )
            if isinstance(source_value, Mapping):
                try:
                    return SourceIdentity.model_validate(source_value)
                except ValueError:
                    pass
        return SourceIdentity(
            connector_id="upload",
            provider=SourceProvider.FILE,
            external_id=str(document.id),
            url=None,
        )


def viewer_elements(
    item_id: str,
    payloads: list[dict[str, Any]],
    citations: Mapping[str, CitationInfo],
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    """Group indexed chunks into unambiguous viewer elements."""

    groups: dict[str, dict[str, Any] | None] = {}
    chunks_by_id: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        chunk_index = int(payload.get("chunk_index") or 0)
        chunk_id = str(payload.get("chunk_id") or f"{item_id}:{chunk_index}")
        chunks_by_id[chunk_id] = payload
        chunks_by_id[f"{item_id}:{chunk_index}"] = payload
        _add_citation_content(
            groups,
            str(payload.get("chunk_text") or ""),
            citations.get(chunk_id, payload_citation(payload)),
        )
    return [value for value in groups.values() if value is not None], chunks_by_id


def payload_citation(payload: Mapping[str, Any]) -> CitationInfo:
    """Rebuild a citation from an indexed chunk payload."""

    raw_section_path = payload.get("section_path")
    section_path = tuple(
        value.strip()
        for value in raw_section_path or ()
        if isinstance(value, str) and value.strip()
    )
    return CitationInfo(
        section=section_path[-1] if section_path else None,
        section_path=section_path,
        anchor=_payload_text(payload, "citation_anchor"),
        page_start=_payload_int(payload, "page_start"),
        page_end=_payload_int(payload, "page_end"),
    )


def _add_citation_content(
    groups: dict[str, dict[str, Any] | None],
    content: str,
    citation: CitationInfo,
) -> None:
    if not content or len(citation.spans) != 1:
        return
    span = citation.spans[0]
    if (
        span.element_id is None
        or span.start_offset != 0
        or span.end_offset != len(content)
    ):
        return
    candidate = {
        "element_id": span.element_id,
        "text": content,
        "page": span.page,
        "section": citation.section,
        "section_path": list(citation.section_path),
        "anchor": citation.anchor,
        "bounding_box": span.bounding_box,
    }
    if span.element_id not in groups:
        groups[span.element_id] = candidate
    elif groups[span.element_id] != candidate:
        groups[span.element_id] = None


def _payload_text(metadata: Mapping[str, Any], key: str) -> str | None:
    value = metadata.get(key)
    return value.strip() if isinstance(value, str) and value.strip() else None


def _payload_int(payload: Mapping[str, Any], key: str) -> int | None:
    value = payload.get(key)
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.strip().isdigit():
        return int(value)
    return None


def _bounded_seconds(value: int) -> int:
    """Keep presigned lifetimes inside the range the routes always applied."""

    return max(1, min(600, value))


__all__ = [
    "DocumentPresenter",
    "payload_citation",
    "viewer_elements",
]
