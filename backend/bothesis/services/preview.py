"""Generation and authorized resolution of derived Item previews."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
from collections.abc import Mapping
from pathlib import Path

from bothesis.db.models import Item
from bothesis.services import (
    DEFAULT_PREVIEW_MAX_SOURCE_BYTES,
    PREVIEW_RENDERER_VERSION,
    PREVIEW_SCHEMA_VERSION,
    KnowledgePreview,
    PreviewAsset,
    PreviewGenerationError,
    PreviewManifest,
    PreviewOriginal,
    ResolvedPreviewAsset,
)
from bothesis.services.preview_renderer import KnowledgePreviewRenderer
from bothesis.storage import DocumentStorage, StoredObject

log = logging.getLogger(__name__)


class KnowledgePreviewService:
    """Generate, store, and permission-neutrally resolve preview renditions.

    Callers remain responsible for authorizing the Item and persisting the
    returned manifest in ``Item.metadata_["preview"]``. Keeping those concerns
    outside this service lets connector ingestion and native uploads reuse the
    same presentation layer without crossing permission or indexing boundaries.
    """

    def __init__(
        self,
        object_storage: DocumentStorage,
        *,
        renderer: KnowledgePreviewRenderer | None = None,
        max_source_bytes: int = DEFAULT_PREVIEW_MAX_SOURCE_BYTES,
    ) -> None:
        if max_source_bytes < 1:
            raise ValueError("preview source limit must be greater than zero")
        self._object_storage = object_storage
        self._renderer = renderer or KnowledgePreviewRenderer()
        self._max_source_bytes = max_source_bytes

    async def generate(
        self,
        document: Item,
        *,
        source_path: Path | None = None,
    ) -> PreviewManifest | None:
        """Build an idempotent manifest while leaving the original untouched."""

        storage_key = _text(getattr(document, "storage_key", None))
        if storage_key is None:
            return None
        stored = await self._object_storage.head(storage_key)
        expected_size = getattr(document, "size_bytes", None)
        if expected_size is not None and stored.size_bytes != expected_size:
            raise PreviewGenerationError(
                "stored preview source size does not match Item metadata"
            )
        source_version = _source_version(document, stored, storage_key=storage_key)
        current = _manifest(document)
        if (
            current is not None
            and current.schema_version == PREVIEW_SCHEMA_VERSION
            and current.renderer_version == PREVIEW_RENDERER_VERSION
            and current.source_version == source_version
        ):
            return current
        if stored.size_bytes > self._max_source_bytes:
            return PreviewManifest(
                source_version=source_version,
                representation="original",
            )
        content_type = _text(getattr(document, "mime_type", None)) or stored.content_type
        if not self._renderer.supports(
            file_name=_file_name(document),
            content_type=content_type,
        ):
            return PreviewManifest(
                source_version=source_version,
                representation="original",
            )

        if source_path is not None:
            source = Path(source_path)
            if not source.is_file() or source.stat().st_size != stored.size_bytes:
                raise PreviewGenerationError(
                    "local preview source does not match the stored original"
                )
            return await self._render_and_store(
                document,
                source,
                stored=stored,
                source_version=source_version,
            )

        suffix = Path(_file_name(document)).suffix
        with tempfile.TemporaryDirectory(prefix="bothesis-preview-") as directory:
            source = Path(directory) / f"source{suffix}"
            downloaded = await self._object_storage.download_to_path(
                storage_key,
                source,
                max_bytes=self._max_source_bytes,
            )
            if downloaded.size_bytes != stored.size_bytes:
                raise PreviewGenerationError(
                    "downloaded preview source no longer matches object metadata"
                )
            return await self._render_and_store(
                document,
                source,
                stored=stored,
                source_version=source_version,
            )

    def resolve(
        self,
        document: Item,
        *,
        expires_seconds: int,
    ) -> KnowledgePreview | None:
        """Resolve short-lived URLs after the caller has authorized the Item."""

        if expires_seconds < 1:
            raise ValueError("preview URL lifetime must be greater than zero")
        storage_key = _text(getattr(document, "storage_key", None))
        if storage_key is None:
            return None
        original_request = self._object_storage.presign_download(
            storage_key,
            expires_seconds=expires_seconds,
        )
        manifest = _manifest(document)
        representation = manifest.representation if manifest is not None else "original"
        assets: list[ResolvedPreviewAsset] = []
        if manifest is not None:
            expected_prefix = _preview_prefix(document)
            for asset in manifest.assets:
                if not asset.key.startswith(expected_prefix):
                    log.warning("ignored preview object outside its Item prefix")
                    continue
                try:
                    request = self._object_storage.presign_download(
                        asset.key,
                        expires_seconds=expires_seconds,
                    )
                except Exception:
                    log.exception("could not resolve derived preview object")
                    continue
                assets.append(
                    ResolvedPreviewAsset(
                        url=request.url,
                        content_type=asset.content_type,
                        size_bytes=asset.size_bytes,
                        width=asset.width,
                        height=asset.height,
                        page=asset.page,
                    )
                )
        if representation != "original" and not assets:
            representation = "original"
        return KnowledgePreview(
            representation=representation,
            original=PreviewOriginal(
                url=original_request.url,
                file_name=_file_name(document),
                content_type=(
                    _text(getattr(document, "mime_type", None))
                    or "application/octet-stream"
                ),
                size_bytes=max(0, int(getattr(document, "size_bytes", None) or 0)),
            ),
            assets=tuple(assets),
            page_count=manifest.page_count if manifest is not None else None,
            truncated=manifest.truncated if manifest is not None else False,
        )

    async def _render_and_store(
        self,
        document: Item,
        source: Path,
        *,
        stored: StoredObject,
        source_version: str,
    ) -> PreviewManifest:
        rendered = await asyncio.to_thread(
            self._renderer.render,
            source,
            file_name=_file_name(document),
            content_type=(
                _text(getattr(document, "mime_type", None)) or stored.content_type
            ),
        )
        assets: list[PreviewAsset] = []
        for position, rendered_asset in enumerate(rendered.assets, start=1):
            key = _preview_key(
                document,
                source_version=source_version,
                page=rendered_asset.page,
                position=position,
            )
            persisted = await asyncio.to_thread(
                self._object_storage.put_bytes,
                rendered_asset.data,
                key,
                content_type=rendered_asset.content_type,
            )
            assets.append(
                PreviewAsset(
                    key=key,
                    content_type=rendered_asset.content_type,
                    size_bytes=persisted.size_bytes,
                    width=rendered_asset.width,
                    height=rendered_asset.height,
                    page=rendered_asset.page,
                )
            )
        return PreviewManifest(
            source_version=source_version,
            representation=rendered.representation,
            assets=tuple(assets),
            page_count=rendered.page_count,
            truncated=rendered.truncated,
        )


def _manifest(document: Item) -> PreviewManifest | None:
    metadata = getattr(document, "metadata_", None)
    if not isinstance(metadata, Mapping):
        return None
    value = metadata.get("preview")
    if value is None:
        return None
    try:
        manifest = PreviewManifest.model_validate(value)
    except ValueError:
        return None
    return manifest if manifest.schema_version == PREVIEW_SCHEMA_VERSION else None


def _source_version(
    document: Item,
    stored: StoredObject,
    *,
    storage_key: str,
) -> str:
    metadata = getattr(document, "metadata_", None)
    storage_metadata = metadata.get("storage") if isinstance(metadata, Mapping) else None
    candidates: list[object] = [stored.version_id, stored.etag]
    if isinstance(storage_metadata, Mapping):
        candidates.extend(
            [storage_metadata.get("version_id"), storage_metadata.get("etag")]
        )
    if isinstance(metadata, Mapping):
        source = metadata.get("source")
        if isinstance(source, Mapping):
            candidates.extend(
                [source.get("external_version"), source.get("etag")]
            )
    version = next(
        (normalized for value in candidates if (normalized := _text(value))),
        None,
    )
    identity = f"{storage_key}\0{version or 'unversioned'}\0{stored.size_bytes}"
    return hashlib.sha256(identity.encode("utf-8")).hexdigest()


def _preview_key(
    document: Item,
    *,
    source_version: str,
    page: int | None,
    position: int,
) -> str:
    name = (
        f"page-{page:04d}.webp"
        if page is not None
        else f"asset-{position:04d}.webp"
    )
    return (
        f"{_preview_prefix(document)}{PREVIEW_RENDERER_VERSION}/"
        f"{source_version}/{name}"
    )


def _preview_prefix(document: Item) -> str:
    tenant_id = _text(getattr(document, "tenant_id", None)) or "unscoped"
    item_id = _text(getattr(document, "id", None))
    if item_id is None:
        raise PreviewGenerationError("preview Item has no durable ID")
    return f"tenants/{tenant_id}/items/{item_id}/previews/"


def _file_name(document: Item) -> str:
    metadata = getattr(document, "metadata_", None)
    value = metadata.get("file_name") if isinstance(metadata, Mapping) else None
    return _text(value) or _text(getattr(document, "title", None)) or "document"


def _text(value: object) -> str | None:
    normalized = str(value).strip() if value is not None else ""
    return normalized or None


__all__ = ["KnowledgePreviewService"]
