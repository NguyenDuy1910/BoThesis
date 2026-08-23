from __future__ import annotations

import logging
import hashlib
import tempfile
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from pathlib import Path
from urllib.parse import parse_qs
from urllib.parse import quote
from urllib.parse import urljoin
from urllib.parse import urlparse

import httpx
from pydantic import BaseModel, Field

from ..file import FileProcessor, FinxFileExtensions, FinxMimeTypes
from bothesis.connector.protocol import AnyContentPart, Chunk, RawObjectStore

log = logging.getLogger(__name__)

CONFLUENCE_OAUTH_TOKEN_URL = "https://auth.atlassian.com/oauth/token"

_ATTACHMENT_SIZE_THRESHOLD = 10 * 1024 * 1024
_ATTACHMENT_CHAR_COUNT_THRESHOLD = 500_000


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    expires_in: int
    scope: str


def get_file_ext(filename: str) -> str:
    # Extract lowercase file extension from a filename.
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_attachment_filetype(
    attachment: dict[str, Any],
) -> bool:
    # Check if attachment MIME type or extension is in the allowed set.
    media_type = attachment.get("metadata", {}).get("mediaType", "")
    if media_type.startswith("image/"):
        return media_type in FinxMimeTypes.IMAGE_MIME_TYPES

    title = attachment.get("title", "")
    extension = get_file_ext(title)

    return extension in FinxFileExtensions.ALL_ALLOWED_EXTENSIONS


class AttachmentProcessingResult(BaseModel):
    text: str | None
    file_name: str | None
    content: list[AnyContentPart] = Field(default_factory=list)
    chunks: tuple[Chunk, ...] = ()
    error: str | None = None
    raw_storage_provider: str | None = None
    raw_storage_bucket: str | None = None
    raw_storage_key: str | None = None
    raw_storage_region: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    checksum_sha256: str | None = None


def _safe_storage_part(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in value
    )
    return cleaned.strip("._") or "unnamed"


def _storage_metadata(
    storage: RawObjectStore | None,
    storage_key: str | None,
    *,
    mime_type: str,
    size_bytes: int,
) -> dict[str, Any]:
    if storage is None or storage_key is None:
        return {"mime_type": mime_type, "size_bytes": size_bytes}
    object_key = getattr(storage, "object_key", lambda key: key)(storage_key)
    return {
        "raw_storage_provider": getattr(storage, "provider", None),
        "raw_storage_bucket": (
            getattr(storage, "bucket", None)
            or getattr(storage, "bucket_name", None)
        ),
        "raw_storage_key": object_key,
        "raw_storage_region": (
            getattr(storage, "region", None)
            or getattr(storage, "region_name", None)
        ),
        "mime_type": mime_type,
        "size_bytes": size_bytes,
    }

def _make_attachment_link(
    confluence_client: Any,
    attachment: dict[str, Any],
    parent_content_id: str | None = None,
) -> str | None:
    base_url = confluence_client.base_url
    host = urlparse(base_url).hostname or ""
    is_cloud = bool(confluence_client.config.get("is_cloud")) or host.endswith(
        "atlassian.net"
    ) or host == "api.atlassian.com"

    if is_cloud:
        attachment_id = attachment.get("id")
        if not parent_content_id or not attachment_id:
            log.warning(
                "parent_content_id and attachment.id are required to download attachments from Confluence Cloud!"
            )
            return None

        download_link = (
            base_url
            + f"/rest/api/content/{parent_content_id}/child/attachment/{attachment_id}/download"
        )
    else:
        download_link = base_url + attachment["_links"]["download"]

    return download_link


def process_attachment(
    confluence_client: Any,
    attachment: dict[str, Any],
    parent_content_id: str | None,
    allow_images: bool,
    storage: RawObjectStore | None = None,
    document_id: str | None = None,
    processor: FileProcessor | None = None,
) -> AttachmentProcessingResult:
    # Download and extract text from a Confluence attachment.
    try:
        media_type: str = attachment.get("metadata", {}).get("mediaType", "")
        if not validate_attachment_filetype(attachment):
            return AttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"Unsupported file type: {media_type}",
            )

        attachment_link = _make_attachment_link(
            confluence_client, attachment, parent_content_id
        )
        if not attachment_link:
            return AttachmentProcessingResult(
                text=None, file_name=None, error="Failed to make attachment link"
            )

        attachment_size = int(attachment.get("extensions", {}).get("fileSize") or 0)

        if media_type.startswith("image/"):
            if not allow_images:
                return AttachmentProcessingResult(
                    text=None,
                    file_name=None,
                    error="Image downloading is not enabled",
                )
        if attachment_size > _ATTACHMENT_SIZE_THRESHOLD:
            log.warning(
                "Skipping %s due to size. size=%d threshold=%d",
                attachment_link,
                attachment_size,
                _ATTACHMENT_SIZE_THRESHOLD,
            )
            return AttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"Attachment too large: {attachment_size} bytes",
            )

        log.info(
            "Downloading attachment: title=%s length=%d link=%s",
            attachment["title"],
            attachment_size,
            attachment_link,
        )

        resp = confluence_client.confluence_client._session.get(
            attachment_link,
            timeout=getattr(confluence_client, "timeout_seconds", 30),
            stream=True,
        )
        try:
            if resp.status_code != 200:
                log.warning(
                    "Failed to fetch %s with status code %d",
                    attachment_link,
                    resp.status_code,
                )
                return AttachmentProcessingResult(
                    text=None,
                    file_name=None,
                    error=f"Attachment download status code is {resp.status_code}",
                )
            content_length = int((getattr(resp, "headers", {}) or {}).get("content-length") or 0)
            if content_length > _ATTACHMENT_SIZE_THRESHOLD:
                return AttachmentProcessingResult(
                    text=None,
                    file_name=None,
                    error=f"Attachment too large: {content_length} bytes",
                )

            attachment_title = attachment["title"]
            safe_title = _safe_storage_part(attachment_title)
            with tempfile.TemporaryDirectory(prefix="bothesis-confluence-") as directory:
                path = Path(directory) / safe_title
                digest = hashlib.sha256()
                downloaded_size = 0
                with path.open("wb") as target:
                    for block in resp.iter_content(chunk_size=1024 * 1024):
                        if not block:
                            continue
                        downloaded_size += len(block)
                        if downloaded_size > _ATTACHMENT_SIZE_THRESHOLD:
                            return AttachmentProcessingResult(
                                text=None,
                                file_name=None,
                                error=(
                                    f"Attachment too large: {downloaded_size} bytes"
                                ),
                            )
                        digest.update(block)
                        target.write(block)
                if downloaded_size == 0:
                    return AttachmentProcessingResult(
                        text=None,
                        file_name=None,
                        error="attachment content is empty",
                    )

                storage_key: str | None = None
                if storage:
                    safe_doc_id = _safe_storage_part(
                        document_id or parent_content_id or "unknown"
                    )
                    kind = "images" if media_type.startswith("image/") else "files"
                    storage_key = f"{kind}/confluence/{safe_doc_id}/{safe_title}"
                    storage.put_path(path, storage_key, content_type=media_type)
                    log.info(
                        "Stored attachment: key=%s size=%d",
                        storage_key,
                        downloaded_size,
                    )

                processed = (processor or FileProcessor()).process_path(
                    path,
                    file_name=attachment_title,
                    item_id=document_id,
                )
            text = processed.text

            if len(text) > _ATTACHMENT_CHAR_COUNT_THRESHOLD:
                return AttachmentProcessingResult(
                    text=None,
                    file_name=None,
                    error=f"Attachment text too long: {len(text)} chars",
                )

            return AttachmentProcessingResult(
                text=text,
                file_name=attachment_title,
                content=processed.item.content,
                chunks=processed.chunks,
                error=None,
                checksum_sha256=digest.hexdigest(),
                **_storage_metadata(
                    storage,
                    storage_key,
                    mime_type=media_type,
                    size_bytes=downloaded_size,
                ),
            )
        except Exception as e:
            return AttachmentProcessingResult(
                text=None, file_name=None, error=f"Failed to extract text: {e}"
            )
        finally:
            close = getattr(resp, "close", None)
            if callable(close):
                close()

    except Exception as e:
        return AttachmentProcessingResult(
            text=None, file_name=None, error=f"Failed to process attachment: {e}"
        )


def convert_attachment_to_content(
    confluence_client: Any,
    attachment: dict[str, Any],
    page_id: str,
    allow_images: bool,
    storage: RawObjectStore | None = None,
    document_id: str | None = None,
    processor: FileProcessor | None = None,
) -> AttachmentProcessingResult | None:
    # Process a Confluence attachment and return its text content.
    media_type = attachment.get("metadata", {}).get("mediaType", "")
    if media_type.startswith("video/") or media_type == "application/gliffy+json":
        log.warning(
            "Skipping unsupported attachment type: '%s' for %s",
            media_type,
            attachment["title"],
        )
        return None

    result = process_attachment(
        confluence_client,
        attachment,
        page_id,
        allow_images,
        storage,
        document_id=document_id,
        processor=processor,
    )
    if result.error is not None:
        log.warning(
            "Attachment %s encountered error: %s",
            attachment["title"],
            result.error,
        )
        return None

    return result


def build_confluence_document_id(
    base_url: str, content_url: str, is_cloud: bool
) -> str:
    # Construct a canonical document ID URL from Confluence base URL and content path.
    final_url = base_url.rstrip("/") + "/"
    if is_cloud and not final_url.endswith("/wiki/"):
        final_url = urljoin(final_url, "wiki") + "/"
    final_url = urljoin(final_url, content_url.lstrip("/"))
    return final_url


def datetime_from_string(datetime_string: str) -> datetime:
    # Parse an ISO datetime string to a UTC-aware datetime object.
    datetime_object = datetime.fromisoformat(datetime_string)

    if datetime_object.tzinfo is None:
        datetime_object = datetime_object.replace(tzinfo=timezone.utc)
    else:
        datetime_object = datetime_object.astimezone(timezone.utc)

    return datetime_object


def confluence_refresh_tokens(
    client_id: str, client_secret: str, cloud_id: str, refresh_token: str
) -> dict[str, Any]:
    # Refresh Confluence Cloud OAuth tokens and return updated credentials.
    response = httpx.post(
        CONFLUENCE_OAUTH_TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        timeout=30,
    )

    response.raise_for_status()

    try:
        token_response = TokenResponse.model_validate_json(response.text)
    except Exception:
        raise RuntimeError("Confluence Cloud token refresh failed.")

    now = datetime.now(timezone.utc)
    expires_at = now + timedelta(seconds=token_response.expires_in)

    new_credentials: dict[str, Any] = {}
    new_credentials["confluence_access_token"] = token_response.access_token
    new_credentials["confluence_refresh_token"] = token_response.refresh_token
    new_credentials["created_at"] = now.isoformat()
    new_credentials["expires_at"] = expires_at.isoformat()
    new_credentials["expires_in"] = token_response.expires_in
    new_credentials["scope"] = token_response.scope
    new_credentials["cloud_id"] = cloud_id
    return new_credentials


def get_single_param_from_url(url: str, param: str) -> str | None:
    parsed_url = urlparse(url)
    return parse_qs(parsed_url.query).get(param, [None])[0]


def get_start_param_from_url(url: str) -> int:
    start_str = get_single_param_from_url(url, "start")
    return int(start_str) if start_str else 0


def update_param_in_path(path: str, param: str, value: str) -> str:
    parsed_url = urlparse(path)
    query_params = parse_qs(parsed_url.query)
    query_params[param] = [value]
    return (
        path.split("?")[0]
        + "?"
        + "&".join(f"{k}={quote(v[0])}" for k, v in query_params.items())
    )
