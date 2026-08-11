from __future__ import annotations

import logging
from datetime import datetime
from datetime import timezone
from io import BytesIO
from typing import Any
from urllib.parse import urljoin

from pydantic import BaseModel

from ..contracts import StorageContract
from ..file.processing import extract_file_text
from ..file.processing import FinxFileExtensions
from ..file.processing import FinxMimeTypes

log = logging.getLogger(__name__)

_ATTACHMENT_SIZE_THRESHOLD = 10 * 1024 * 1024
_ATTACHMENT_CHAR_COUNT_THRESHOLD = 500_000


class JiraAttachmentProcessingResult(BaseModel):
    text: str | None
    file_name: str | None
    error: str | None = None
    raw_storage_bucket: str | None = None
    raw_storage_key: str | None = None
    raw_storage_region: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None


def build_jira_document_id(issue_key: str) -> str:
    return f"jira::{issue_key}"


def build_jira_attachment_document_id(issue_key: str, attachment_id: str) -> str:
    return f"jira::{issue_key}::att::{attachment_id}"


def _safe_storage_part(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_." else "_"
        for character in value
    )
    return cleaned.strip("._") or "unnamed"


def _storage_metadata(
    storage: StorageContract | None,
    storage_key: str | None,
    *,
    mime_type: str,
    size_bytes: int,
) -> dict[str, Any]:
    if storage is None or storage_key is None:
        return {"mime_type": mime_type, "size_bytes": size_bytes}
    object_key = getattr(storage, "object_key", lambda key: key)(storage_key)
    return {
        "raw_storage_bucket": getattr(storage, "bucket_name", None),
        "raw_storage_key": object_key,
        "raw_storage_region": getattr(storage, "region_name", None),
        "mime_type": mime_type,
        "size_bytes": size_bytes,
    }

def build_jira_issue_link(jira_base: str, issue_key: str) -> str:
    return urljoin(jira_base.rstrip("/") + "/", f"browse/{issue_key}")


def parse_jira_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value
    if len(value) > 5 and value[-5] in ("+", "-") and value[-3] != ":":
        normalized = f"{value[:-2]}:{value[-2:]}"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        try:
            parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%S.%f%z")
        except ValueError:
            log.exception("Failed to parse Jira datetime %s", value)
            return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def format_jira_jql_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M")


def get_file_ext(filename: str) -> str:
    return "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""


def validate_jira_attachment_filetype(attachment: dict[str, Any]) -> bool:
    media_type = attachment.get("mimeType", "")
    if media_type.startswith("image/"):
        return media_type in FinxMimeTypes.IMAGE_MIME_TYPES
    return get_file_ext(attachment.get("filename", "")) in FinxFileExtensions.ALL_ALLOWED_EXTENSIONS


def _join_adf_children(content: Any, separator: str) -> str:
    if not isinstance(content, list):
        return adf_to_text(content)
    return separator.join(filter(None, (adf_to_text(item) for item in content)))


def adf_to_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return "\n".join(filter(None, (adf_to_text(item) for item in value)))
    if not isinstance(value, dict):
        return str(value)

    node_type = value.get("type", "")
    attrs = value.get("attrs", {})
    content = value.get("content", [])

    if node_type == "text":
        return str(value.get("text", ""))
    if node_type == "mention":
        return str(attrs.get("text") or attrs.get("displayName") or "")
    if node_type == "hardBreak":
        return "\n"
    if node_type in {"inlineCard", "blockCard"}:
        return str(attrs.get("url", ""))
    if node_type == "media":
        return str(attrs.get("alt") or attrs.get("id") or "")

    inline_nodes = {"paragraph", "heading", "blockquote", "listItem", "tableCell", "tableHeader"}
    children = _join_adf_children(content, "" if node_type in inline_nodes else "\n")
    if node_type in {"paragraph", "heading", "blockquote", "listItem"}:
        return children.strip()
    if node_type in {"bulletList", "orderedList"}:
        return "\n".join(line for line in children.splitlines() if line.strip())
    if node_type == "codeBlock":
        return children.strip()
    if node_type in {"table", "tableRow", "tableCell", "tableHeader"}:
        return children.strip()
    return children.strip()


def process_jira_attachment(
    jira_client: Any,
    attachment: dict[str, Any],
    issue_key: str,
    allow_images: bool,
    storage: StorageContract | None = None,
) -> JiraAttachmentProcessingResult:
    try:
        if not validate_jira_attachment_filetype(attachment):
            return JiraAttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"Unsupported file type: {attachment.get('mimeType', '')}",
            )

        filename = attachment.get("filename", str(attachment.get("id", "attachment")))
        media_type = attachment.get("mimeType", "")
        attachment_size = int(attachment.get("size") or 0)

        if media_type.startswith("image/"):
            if not allow_images:
                return JiraAttachmentProcessingResult(
                    text=None,
                    file_name=None,
                    error="Image downloading is not enabled",
                )
        elif attachment_size > _ATTACHMENT_SIZE_THRESHOLD:
            return JiraAttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"Attachment too large: {attachment_size} bytes",
            )

        raw_bytes = jira_client.get_attachment_content(str(attachment.get("id", "")))
        if not raw_bytes:
            return JiraAttachmentProcessingResult(
                text=None,
                file_name=None,
                error="attachment content is empty",
            )
        if len(raw_bytes) > _ATTACHMENT_SIZE_THRESHOLD and not media_type.startswith("image/"):
            return JiraAttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"Attachment too large: {len(raw_bytes)} bytes",
            )

        storage_key: str | None = None
        if storage:
            document_id = build_jira_attachment_document_id(issue_key, str(attachment.get("id", "")))
            kind = "images" if media_type.startswith("image/") else "files"
            storage_key = f"{kind}/jira/{_safe_storage_part(document_id)}/{_safe_storage_part(filename)}"
            storage.save_bytes(raw_bytes, storage_key)

        if media_type.startswith("image/"):
            return JiraAttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"No image text extractor configured for {filename}",
                **_storage_metadata(
                    storage,
                    storage_key,
                    mime_type=media_type,
                    size_bytes=len(raw_bytes),
                ),
            )

        try:
            text = extract_file_text(file=BytesIO(raw_bytes), file_name=filename)
        except Exception as exc:
            return JiraAttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"Failed to extract text: {exc}",
            )

        if len(text) > _ATTACHMENT_CHAR_COUNT_THRESHOLD:
            return JiraAttachmentProcessingResult(
                text=None,
                file_name=None,
                error=f"Attachment text too long: {len(text)} chars",
            )
        return JiraAttachmentProcessingResult(
            text=text,
            file_name=filename,
            error=None,
            **_storage_metadata(
                storage,
                storage_key,
                mime_type=media_type,
                size_bytes=len(raw_bytes),
            ),
        )
    except Exception as exc:
        return JiraAttachmentProcessingResult(
            text=None,
            file_name=None,
            error=f"Failed to process attachment: {exc}",
        )
