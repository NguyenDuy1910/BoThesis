from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..base import BaseSourceConnector, GenerateDocumentsOutput, LoadConnector
from ..contracts import StorageContract
from ..models import (
    ConnectorCheckpoint,
    ConnectorScope,
    Document,
    DocumentSource,
    HierarchyNode,
    HierarchyNodeType,
    SourceACL,
    SourceChange,
    SourceCheckpoint,
    SourceDocument,
    TextSection,
)
from .processing import FileProcessor

log = logging.getLogger(__name__)

MANUAL_UPLOAD_SOURCE = "file"
MANUAL_UPLOAD_SCOPE_VALUE = "manual_uploads"
MANUAL_UPLOAD_DISPLAY_NAME = "Manual uploads"
MANUAL_UPLOAD_CONNECTOR_NAME = "Manual uploads"
MANUAL_UPLOAD_HIERARCHY_NODE_ID = "file::manual_uploads"


@dataclass(frozen=True, slots=True)
class ManualUploadRecord:
    external_id: str
    file_name: str
    path: Path
    size_bytes: int
    mime_type: str | None
    sha256: str
    uploaded_at: datetime
    modified_at: datetime
    acl: SourceACL
    metadata: dict[str, str | list[str]]


class ManualFileUploadConnector(BaseSourceConnector):
    """Incremental adapter for admin-uploaded files and their record JSON."""

    source = DocumentSource.FILE.value
    checkpoint_model = SourceCheckpoint

    def __init__(
        self,
        config: dict[str, Any],
        *,
        processor: FileProcessor | None = None,
    ) -> None:
        self.config = dict(config)
        self.base_dir = Path(
            str(config.get("base_dir") or "/tmp/bothesis-manual-uploads")
        ).expanduser()
        self._processor = processor or FileProcessor(
            max_file_bytes=int(config.get("max_file_bytes") or 20 * 1024 * 1024)
        )
        self._records: dict[str, ManualUploadRecord] = {}
        self._next_checkpoint = SourceCheckpoint()
        self._storage: StorageContract | None = None
        self._default_acl = _acl_from_mapping(config.get("acl") or config)

    def set_storage(self, storage: StorageContract) -> None:
        self._storage = storage

    async def test_connection(self) -> bool:
        await asyncio.to_thread(self.base_dir.mkdir, parents=True, exist_ok=True)
        return self.base_dir.is_dir()

    async def list_scopes(self) -> list[ConnectorScope]:
        return [
            ConnectorScope(
                scope_type="folder",
                scope_value=MANUAL_UPLOAD_SCOPE_VALUE,
                display_name=MANUAL_UPLOAD_DISPLAY_NAME,
            )
        ]

    async def discover_changes(
        self,
        checkpoint: ConnectorCheckpoint,
        scope: ConnectorScope,
    ) -> list[SourceChange]:
        previous = checkpoint if isinstance(checkpoint, SourceCheckpoint) else SourceCheckpoint()
        previous_position = (_parse_optional_datetime(previous.updated_at), previous.cursor or "")
        records = await asyncio.to_thread(
            lambda: sorted(
                self._records_for_scope(scope),
                key=lambda record: (record.modified_at, record.external_id),
            )
        )
        external_ids = [record.external_id for record in records]
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("Manual upload records contain duplicate external_id values")
        self._records = {record.external_id: record for record in records}

        changes = [
            SourceChange(
                external_id=record.external_id,
                external_version=record.sha256,
                etag=record.sha256,
                last_modified_at=record.modified_at,
            )
            for record in records
            if (record.modified_at, record.external_id) > previous_position
        ]
        if records:
            last = records[-1]
            self._next_checkpoint = SourceCheckpoint(
                updated_at=last.modified_at.isoformat(),
                cursor=last.external_id,
            )
        else:
            self._next_checkpoint = previous
        return changes

    async def fetch_document(self, external_id: str) -> SourceDocument:
        record = self._records.get(external_id)
        if record is None:
            record = await asyncio.to_thread(self._load_record, external_id)
        processed = await asyncio.to_thread(
            self._processor.process_path, record.path, file_name=record.file_name
        )
        if processed.sha256 != record.sha256:
            raise RuntimeError(f"File changed after discovery: {record.external_id}")

        raw_storage_bucket = None
        raw_storage_key = None
        raw_storage_region = None
        if self._storage is not None:
            key = (
                f"manual_uploads/{_safe_storage_part(record.external_id)}/"
                f"{_safe_storage_part(record.file_name)}"
            )
            await asyncio.to_thread(self._storage.save_bytes, processed.raw_bytes, key)
            raw_storage_bucket = getattr(self._storage, "bucket_name", None)
            raw_storage_key = (
                self._storage.object_key(key)
                if hasattr(self._storage, "object_key")
                else key
            )
            raw_storage_region = getattr(self._storage, "region_name", None)

        metadata = {
            **record.metadata,
            "source_kind": "manual_upload",
            "file_name": record.file_name,
            "sha256": record.sha256,
        }
        return SourceDocument(
            external_id=record.external_id,
            source=DocumentSource.FILE,
            semantic_identifier=record.file_name,
            title=record.file_name,
            sections=[TextSection(text=processed.text)],
            metadata=metadata,
            external_version=record.sha256,
            etag=record.sha256,
            doc_created_at=record.uploaded_at,
            doc_updated_at=record.modified_at,
            parent_hierarchy_raw_node_id=MANUAL_UPLOAD_HIERARCHY_NODE_ID,
            acl=record.acl,
            raw_storage_bucket=raw_storage_bucket,
            raw_storage_key=raw_storage_key,
            raw_storage_region=raw_storage_region,
            mime_type=record.mime_type or processed.mime_type,
            file_name=record.file_name,
            size_bytes=processed.size_bytes,
        )

    async def fetch_acl(self, external_id: str) -> SourceACL:
        record = self._records.get(external_id)
        if record is None:
            record = await asyncio.to_thread(self._load_record, external_id)
        return record.acl.model_copy(deep=True)

    async def fetch_hierarchy(self, scope: ConnectorScope) -> list[HierarchyNode]:
        del scope
        return [
            HierarchyNode(
                raw_node_id=MANUAL_UPLOAD_HIERARCHY_NODE_ID,
                display_name=MANUAL_UPLOAD_DISPLAY_NAME,
                node_type=HierarchyNodeType.FOLDER,
            )
        ]

    def next_checkpoint(self) -> ConnectorCheckpoint:
        return self._next_checkpoint.model_copy(deep=True)

    def _records_for_scope(self, scope: ConnectorScope) -> Iterator[ManualUploadRecord]:
        if scope.scope_type == "file" or scope.scope_value != MANUAL_UPLOAD_SCOPE_VALUE:
            yield self._load_record(scope.scope_value)
            return
        if not self.base_dir.exists():
            return
        for record_path in sorted(self.base_dir.glob("*.json")):
            yield self._load_record(record_path.stem)

    def _load_record(self, external_id: str) -> ManualUploadRecord:
        record_path = _confined_path(self.base_dir, self.base_dir / f"{external_id}.json")
        if not record_path.is_file():
            raise FileNotFoundError(f"Manual upload record not found: {external_id}")

        try:
            data = json.loads(record_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid manual upload record {record_path.name}: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"Manual upload record must be an object: {record_path.name}")

        raw_path = Path(str(data.get("path") or ""))
        file_path = raw_path if raw_path.is_absolute() else self.base_dir / raw_path
        file_path = _confined_path(self.base_dir, file_path)
        if not file_path.is_file():
            raise FileNotFoundError(f"Manual upload file not found: {file_path}")

        stat = file_path.stat()
        file_name = str(data.get("file_name") or file_path.name).strip()
        if not file_name:
            raise ValueError(f"Manual upload file_name is empty: {external_id}")
        actual_size = stat.st_size
        declared_size = data.get("size_bytes")
        if declared_size is not None and int(declared_size) != actual_size:
            raise ValueError(f"Manual upload size mismatch: {external_id}")
        actual_sha256 = _sha256_path(file_path)
        declared_sha256 = str(data.get("sha256") or "").strip().lower()
        if declared_sha256 and declared_sha256 != actual_sha256:
            raise ValueError(f"Manual upload checksum mismatch: {external_id}")

        uploaded_at = _parse_datetime(
            data.get("uploaded_at"),
            fallback=datetime.fromtimestamp(record_path.stat().st_mtime, tz=timezone.utc),
        )
        modified_at = max(
            uploaded_at,
            datetime.fromtimestamp(record_path.stat().st_mtime, tz=timezone.utc),
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
        )
        raw_metadata = data.get("metadata") or {}
        if not isinstance(raw_metadata, Mapping):
            raise ValueError(f"Manual upload metadata must be an object: {external_id}")
        metadata = {
            str(key): [str(item) for item in value] if isinstance(value, list) else str(value)
            for key, value in raw_metadata.items()
        }
        resolved_external_id = str(data.get("external_id") or external_id).strip()
        if not resolved_external_id:
            raise ValueError(f"Manual upload external_id is empty: {record_path.name}")
        return ManualUploadRecord(
            external_id=resolved_external_id,
            file_name=file_name,
            path=file_path,
            size_bytes=actual_size,
            mime_type=str(data.get("mime_type") or mimetypes.guess_type(file_name)[0] or "") or None,
            sha256=actual_sha256,
            uploaded_at=uploaded_at,
            modified_at=modified_at,
            acl=_acl_from_mapping(data.get("acl") or {}, default=self._default_acl),
            metadata=metadata,
        )


class LocalFileConnector(LoadConnector):
    """One-shot local file loader with real extraction and bounded batches."""

    def __init__(
        self,
        file_locations: list[Path | str] | None = None,
        file_names: list[str] | None = None,
        batch_size: int = 50,
        *,
        processor: FileProcessor | None = None,
        acl: SourceACL | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least one")
        self.file_locations = [Path(location).expanduser() for location in (file_locations or [])]
        self.file_names = list(file_names or [])
        if self.file_names and len(self.file_names) != len(self.file_locations):
            raise ValueError("file_names must be empty or match file_locations")
        self.batch_size = batch_size
        self._processor = processor or FileProcessor()
        self._acl = acl or SourceACL()

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        del credentials
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        batch: list[Document | HierarchyNode] = []
        for index, path in enumerate(self.file_locations):
            if not path.is_file():
                raise FileNotFoundError(f"Local connector file not found: {path}")
            display_name = self.file_names[index] if self.file_names else path.name
            processed = self._processor.process_path(path, file_name=display_name)
            external_id = _local_file_id(path)
            batch.append(
                Document(
                    id=external_id,
                    external_id=external_id,
                    external_version=processed.sha256,
                    etag=processed.sha256,
                    source=DocumentSource.FILE,
                    semantic_identifier=display_name,
                    title=display_name,
                    metadata={
                        "source_kind": "local_file",
                        "file_name": display_name,
                        "sha256": processed.sha256,
                    },
                    sections=[TextSection(text=processed.text)],
                    external_access=self._acl.to_external_access(),
                    mime_type=processed.mime_type,
                    file_name=display_name,
                    size_bytes=processed.size_bytes,
                    doc_updated_at=datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc),
                )
            )
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


def _acl_from_mapping(value: Any, *, default: SourceACL | None = None) -> SourceACL:
    if not isinstance(value, Mapping):
        return default.model_copy(deep=True) if default else SourceACL()
    has_acl_key = any(
        key in value
        for key in (
            "user_emails",
            "user_group_ids",
            "source_reader_ids",
            "is_public",
            "public",
        )
    )
    if not has_acl_key:
        return default.model_copy(deep=True) if default else SourceACL()
    return SourceACL(
        user_emails=value.get("user_emails") or [],
        user_group_ids=value.get("user_group_ids") or [],
        source_reader_ids=value.get("source_reader_ids") or [],
        is_public=bool(value.get("is_public", value.get("public", False))),
    )


def _confined_path(base_dir: Path, candidate: Path) -> Path:
    resolved_base = base_dir.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_base):
        raise ValueError(f"Manual upload path escapes base_dir: {candidate}")
    return resolved_candidate


def _sha256_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_datetime(value: Any, *, fallback: datetime) -> datetime:
    if value in (None, ""):
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO timestamp: {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _parse_optional_datetime(value: str | None) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    return _parse_datetime(value, fallback=datetime.min.replace(tzinfo=timezone.utc))


def _safe_storage_part(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_." else "_" for character in value)
    return cleaned.strip("._") or "unnamed"


def _local_file_id(path: Path) -> str:
    stable_path = str(path.resolve()).encode("utf-8")
    return f"file::{hashlib.sha256(stable_path).hexdigest()}"


__all__ = [
    "LocalFileConnector",
    "MANUAL_UPLOAD_CONNECTOR_NAME",
    "MANUAL_UPLOAD_DISPLAY_NAME",
    "MANUAL_UPLOAD_HIERARCHY_NODE_ID",
    "MANUAL_UPLOAD_SCOPE_VALUE",
    "MANUAL_UPLOAD_SOURCE",
    "ManualFileUploadConnector",
    "ManualUploadRecord",
]
