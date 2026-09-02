"""Derived knowledge-asset preview service and rendering contracts.

Preview objects are durable, permission-neutral presentation assets. Access
URLs are resolved only after the owning Item has passed normal authorization;
the original object remains authoritative and is never replaced by a preview.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import tempfile
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from bothesis.db.models import Item
from bothesis.document_index.raw_storage import DocumentStorage, StoredObject
from bothesis.services import (
    DEFAULT_PREVIEW_MAX_DIMENSION,
    DEFAULT_PREVIEW_MAX_PAGES,
    DEFAULT_PREVIEW_MAX_SOURCE_BYTES,
    DEFAULT_PREVIEW_WEBP_QUALITY,
    PREVIEW_RENDERER_VERSION,
    PREVIEW_SCHEMA_VERSION,
    KnowledgePreview,
    PreviewAsset,
    PreviewGenerationError,
    PreviewManifest,
    PreviewOriginal,
    RenderedPreview,
    RenderedPreviewAsset,
    ResolvedPreviewAsset,
)

_PDF_CONTENT_TYPES = frozenset({"application/pdf"})
_PDF_EXTENSIONS = frozenset({".pdf"})
_IMAGE_CONTENT_TYPES = frozenset(
    {
        "image/avif",
        "image/bmp",
        "image/gif",
        "image/jpeg",
        "image/png",
        "image/tiff",
        "image/webp",
    }
)
_IMAGE_EXTENSIONS = frozenset(
    {".avif", ".bmp", ".gif", ".jpeg", ".jpg", ".png", ".tif", ".tiff", ".webp"}
)

log = logging.getLogger(__name__)


class KnowledgePreviewRenderer:
    """Render bounded image and PDF previews as WebP presentation assets.

    Office documents and unknown future formats intentionally retain an
    original-only representation until a format-specific renderer is added.
    This keeps the public preview contract stable without coupling rendering
    libraries to connector extraction.
    """

    def __init__(
        self,
        *,
        max_pages: int = DEFAULT_PREVIEW_MAX_PAGES,
        max_dimension: int = DEFAULT_PREVIEW_MAX_DIMENSION,
        webp_quality: int = DEFAULT_PREVIEW_WEBP_QUALITY,
        max_image_pixels: int = 40_000_000,
    ) -> None:
        if min(max_pages, max_dimension, max_image_pixels) < 1:
            raise ValueError("preview rendering limits must be greater than zero")
        if not 1 <= webp_quality <= 100:
            raise ValueError("webp_quality must be between 1 and 100")
        self.max_pages = max_pages
        self.max_dimension = max_dimension
        self.webp_quality = webp_quality
        self.max_image_pixels = max_image_pixels

    def render(
        self,
        source_path: Path,
        *,
        file_name: str,
        content_type: str | None,
    ) -> RenderedPreview:
        source = Path(source_path)
        if not source.is_file():
            raise PreviewGenerationError(f"preview source is not a file: {source}")
        normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
        extension = Path(file_name).suffix.casefold() or source.suffix.casefold()
        if normalized_type in _PDF_CONTENT_TYPES or extension in _PDF_EXTENSIONS:
            return self._render_pdf(source)
        if normalized_type in _IMAGE_CONTENT_TYPES or extension in _IMAGE_EXTENSIONS:
            return self._render_image(source)
        return RenderedPreview(representation="original")

    @staticmethod
    def supports(*, file_name: str, content_type: str | None) -> bool:
        normalized_type = (content_type or "").split(";", 1)[0].strip().casefold()
        extension = Path(file_name).suffix.casefold()
        return (
            normalized_type in _PDF_CONTENT_TYPES
            or normalized_type in _IMAGE_CONTENT_TYPES
            or extension in _PDF_EXTENSIONS
            or extension in _IMAGE_EXTENSIONS
        )

    def _render_image(self, source: Path) -> RenderedPreview:
        try:
            with Image.open(source) as opened:
                width, height = opened.size
                self._validate_dimensions(width, height)
                opened.seek(0)
                image = ImageOps.exif_transpose(opened).copy()
        except (OSError, UnidentifiedImageError, ValueError) as exc:
            raise PreviewGenerationError("image preview rendering failed") from exc
        try:
            asset = self._webp_asset(image, page=1)
        finally:
            image.close()
        return RenderedPreview(
            representation="image",
            assets=(asset,),
            page_count=1,
        )

    def _render_pdf(self, source: Path) -> RenderedPreview:
        try:
            document = pdfium.PdfDocument(str(source))
        except Exception as exc:
            raise PreviewGenerationError("PDF preview rendering failed") from exc
        try:
            page_count = len(document)
            if page_count < 1:
                raise PreviewGenerationError("PDF preview source has no pages")
            assets: list[RenderedPreviewAsset] = []
            for page_index in range(min(page_count, self.max_pages)):
                page = document[page_index]
                try:
                    width, height = page.get_size()
                    if width <= 0 or height <= 0:
                        raise PreviewGenerationError("PDF page has invalid dimensions")
                    scale = min(
                        2.0,
                        self.max_dimension / width,
                        self.max_dimension / height,
                    )
                    bitmap = page.render(scale=max(scale, 0.0001))
                    try:
                        image = bitmap.to_pil()
                        try:
                            assets.append(self._webp_asset(image, page=page_index + 1))
                        finally:
                            image.close()
                    finally:
                        bitmap.close()
                finally:
                    page.close()
            return RenderedPreview(
                representation="pages",
                assets=tuple(assets),
                page_count=page_count,
                truncated=page_count > self.max_pages,
            )
        except PreviewGenerationError:
            raise
        except Exception as exc:
            raise PreviewGenerationError("PDF preview rendering failed") from exc
        finally:
            document.close()

    def _webp_asset(self, image: Image.Image, *, page: int) -> RenderedPreviewAsset:
        width, height = image.size
        self._validate_dimensions(width, height)
        image.thumbnail(
            (self.max_dimension, self.max_dimension),
            Image.Resampling.LANCZOS,
        )
        converted: Image.Image | None = None
        if image.mode not in {"RGB", "RGBA"}:
            converted = image.convert("RGBA" if "A" in image.getbands() else "RGB")
        rendered = converted or image
        try:
            output = BytesIO()
            rendered.save(
                output,
                format="WEBP",
                quality=self.webp_quality,
                method=4,
            )
            data = output.getvalue()
            if not data:
                raise PreviewGenerationError("WebP encoder returned an empty preview")
            return RenderedPreviewAsset(
                data=data,
                content_type="image/webp",
                width=rendered.width,
                height=rendered.height,
                page=page,
            )
        finally:
            if converted is not None:
                converted.close()

    def _validate_dimensions(self, width: int, height: int) -> None:
        if width < 1 or height < 1:
            raise PreviewGenerationError("preview source has invalid dimensions")
        if width * height > self.max_image_pixels:
            raise PreviewGenerationError("preview source exceeds the image pixel limit")


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


__all__ = [
    "KnowledgePreviewRenderer",
    "KnowledgePreviewService",
]
