"""Bounded renderer for derived Item preview assets.

Preview objects are durable, permission-neutral presentation assets. Access
URLs are resolved only after the owning Item has passed normal authorization;
the original object remains authoritative and is never replaced by a preview.
"""

from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pypdfium2 as pdfium
from PIL import Image, ImageOps, UnidentifiedImageError

from bothesis.services import (
    DEFAULT_PREVIEW_MAX_DIMENSION,
    DEFAULT_PREVIEW_MAX_PAGES,
    DEFAULT_PREVIEW_WEBP_QUALITY,
    PreviewGenerationError,
    RenderedPreview,
    RenderedPreviewAsset,
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


__all__ = ["KnowledgePreviewRenderer"]
