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
import tempfile
from typing import Any

from ..base import BaseSourceConnector, GenerateDocumentsOutput, LoadConnector
from bothesis.connector.protocol import (
    AccessEffect,
    AccessPolicy,
    AccessRule,
    AnyItem,
    ChangeType,
    Chunk,
    CollectionItem,
    CollectionKind,
    ConnectorCheckpoint,
    ConnectorScope,
    DocumentItem,
    DocumentKind,
    DirectAccess,
    EffectiveAccess,
    Hierarchy,
    ItemChange,
    Principal,
    SourceIdentity,
    SourceCheckpoint,
    SourceProvider,
    StorageObject,
)
from bothesis.connector.protocol import RawObjectStore
from .processing import FileProcessor

log = logging.getLogger(__name__)

FILE_SOURCE = SourceProvider.FILE.value
FILE_SCOPE_VALUE = SourceProvider.FILE.value
FILE_DISPLAY_NAME = "Files"
FILE_CONNECTOR_NAME = "Files"
FILE_HIERARCHY_NODE_ID = "file::files"


@dataclass(frozen=True, slots=True)
class FileRecord:
    external_id: str
    file_name: str
    path: Path | None
    storage_key: str | None
    size_bytes: int
    mime_type: str | None
    provider_version: str
    uploaded_at: datetime
    modified_at: datetime
    access: AccessPolicy
    metadata: dict[str, str | list[str]]


class FileConnector(BaseSourceConnector):
    """Incremental adapter for a file source and its record JSON."""

    source = SourceProvider.FILE.value
    checkpoint_model = SourceCheckpoint

    def __init__(
        self,
        config: dict[str, Any],
        *,
        processor: FileProcessor | None = None,
    ) -> None:
        self.config = dict(config)
        self.base_dir = Path(
            str(config.get("base_dir") or "/tmp/bothesis-files")
        ).expanduser()
        self._processor = processor or FileProcessor(
            max_file_bytes=int(config.get("max_file_bytes") or 20 * 1024 * 1024)
        )
        self._records: dict[str, FileRecord] = {}
        self._records_configured = False
        self._processed_chunks: dict[str, tuple[Chunk, ...]] = {}
        self._next_checkpoint = SourceCheckpoint()
        self._storage: RawObjectStore | None = None
        self._default_access = _access_from_mapping(config.get("acl") or config)

    def set_storage(self, storage: RawObjectStore) -> None:
        self._storage = storage

    def set_records(self, records: list[Mapping[str, Any]]) -> None:
        """Load canonical PostgreSQL Item metadata without a sidecar manifest."""

        resolved: dict[str, FileRecord] = {}
        for raw in records:
            external_id = str(raw.get("external_id") or "").strip()
            file_name = str(raw.get("file_name") or "").strip()
            storage_key = str(raw.get("storage_key") or "").strip()
            size_bytes = int(raw.get("size_bytes") or 0)
            if not external_id or not file_name or not storage_key:
                raise ValueError("stored file Item metadata is incomplete")
            if size_bytes < 1:
                raise ValueError(f"stored file Item is invalid: {external_id}")
            uploaded_at = _parse_datetime(
                raw.get("uploaded_at"),
                fallback=datetime.min.replace(tzinfo=timezone.utc),
            )
            modified_at = _parse_datetime(
                raw.get("modified_at"), fallback=uploaded_at
            )
            provider_version = str(
                raw.get("provider_version")
                or raw.get("version")
                or modified_at.isoformat()
            ).strip()
            if not provider_version:
                raise ValueError(f"stored file Item version is empty: {external_id}")
            metadata = raw.get("metadata") or {}
            if not isinstance(metadata, Mapping):
                raise ValueError(f"stored file Item metadata is invalid: {external_id}")
            resolved[external_id] = FileRecord(
                external_id=external_id,
                file_name=file_name,
                path=None,
                storage_key=storage_key,
                size_bytes=size_bytes,
                mime_type=str(raw.get("mime_type") or "").strip() or None,
                provider_version=provider_version,
                uploaded_at=uploaded_at,
                modified_at=modified_at,
                access=_access_from_mapping(
                    raw.get("acl") or {}, default=self._default_access
                ),
                metadata={
                    str(key): (
                        [str(item) for item in value]
                        if isinstance(value, list)
                        else str(value)
                    )
                    for key, value in metadata.items()
                },
            )
        self._records = resolved
        self._records_configured = True

    async def test_connection(self) -> bool:
        await asyncio.to_thread(self.base_dir.mkdir, parents=True, exist_ok=True)
        return self.base_dir.is_dir()

    async def list_scopes(self) -> list[ConnectorScope]:
        return [
            ConnectorScope(
                scope_type="source_provider",
                scope_value=FILE_SCOPE_VALUE,
                display_name=FILE_DISPLAY_NAME,
            )
        ]

    async def discover_changes(
        self,
        checkpoint: ConnectorCheckpoint,
        scope: ConnectorScope,
    ) -> list[ItemChange]:
        previous = checkpoint if isinstance(checkpoint, SourceCheckpoint) else SourceCheckpoint()
        previous_versions = dict(previous.versions)
        records = await asyncio.to_thread(
            lambda: sorted(
                self._records_for_scope(scope),
                key=lambda record: (record.modified_at, record.external_id),
            )
        )
        external_ids = [record.external_id for record in records]
        if len(external_ids) != len(set(external_ids)):
            raise ValueError("File records contain duplicate external_id values")
        self._records = {record.external_id: record for record in records}
        self._processed_chunks.clear()

        current_ids = {record.external_id for record in records}
        changes = [
            ItemChange(
                type=(
                    ChangeType.CREATED
                    if record.external_id not in previous_versions
                    else ChangeType.UPDATED
                ),
                item_id=record.external_id,
                provider_version=record.provider_version,
                occurred_at=record.modified_at,
            )
            for record in records
            if previous_versions.get(record.external_id) != record.provider_version
        ]
        changes.extend(
            ItemChange(type=ChangeType.DELETED, item_id=external_id)
            for external_id in previous_versions.keys() - current_ids
        )
        if records:
            last = records[-1]
            self._next_checkpoint = SourceCheckpoint(
                updated_at=last.modified_at.isoformat(),
                cursor=last.external_id,
                versions={
                    record.external_id: record.provider_version for record in records
                },
            )
        else:
            self._next_checkpoint = SourceCheckpoint()
        return changes

    async def fetch_item(self, external_id: str) -> AnyItem:
        record = self._records.get(external_id)
        if record is None:
            record = await asyncio.to_thread(self._load_record, external_id)
        metadata = {
            **record.metadata,
            "source_kind": FILE_SOURCE,
            "file_name": record.file_name,
        }
        source = SourceIdentity(
            connector_id=str(self.config.get("connector_id") or FILE_SOURCE),
            provider=SourceProvider.FILE,
            external_id=record.external_id,
            external_version=record.provider_version,
            etag=None,
        )
        source_path = record.path
        temporary: tempfile.TemporaryDirectory[str] | None = None
        if source_path is None:
            if self._storage is None or not record.storage_key:
                raise RuntimeError("file Item object storage is unavailable")
            downloader = getattr(self._storage, "download_to_path", None)
            if downloader is None:
                raise RuntimeError("configured object storage cannot download files")
            temporary = tempfile.TemporaryDirectory(prefix="bothesis-file-connector-")
            source_path = Path(temporary.name) / record.file_name
            await downloader(
                record.storage_key,
                source_path,
                max_bytes=self._processor.max_file_bytes,
            )
        processed = await asyncio.to_thread(
            self._processor.process_path,
            source_path,
            file_name=record.file_name,
            item_id=record.external_id,
            title=record.file_name,
            source=source,
            hierarchy=Hierarchy(parent_id=FILE_HIERARCHY_NODE_ID),
            access=record.access,
            metadata=metadata,
            document_kind=_document_kind(
                record.mime_type or mimetypes.guess_type(record.file_name)[0]
            ),
        )
        try:
            item = processed.item
            key = record.storage_key
            stored = None
            if key is None and self._storage is not None:
                assert record.path is not None
                key = (
                    f"files/{_safe_storage_part(record.external_id)}/"
                    f"{_safe_storage_part(record.file_name)}"
                )
                stored = await asyncio.to_thread(
                    self._storage.put_path,
                    record.path,
                    key,
                    content_type=record.mime_type or processed.mime_type,
                )
            if key is not None and self._storage is not None:
                if stored is None:
                    stored = await self._storage.head(key)  # type: ignore[attr-defined]
                item = item.model_copy(
                    update={
                        "original": _storage_object(
                            self._storage,
                            stored,
                            key=key,
                            file_name=record.file_name,
                            content_type=record.mime_type or processed.mime_type,
                            size_bytes=record.size_bytes,
                        )
                    }
                )

            self._processed_chunks[item.id] = processed.chunks
            return item.model_copy(
                update={"created_at": record.uploaded_at, "updated_at": record.modified_at}
            )
        finally:
            if temporary is not None:
                temporary.cleanup()

    async def fetch_chunks(self, item: DocumentItem) -> tuple[Chunk, ...] | None:
        """Return chunks produced in the same Docling pass as ``fetch_item``."""

        return self._processed_chunks.pop(item.id, None)

    async def fetch_hierarchy(self, scope: ConnectorScope) -> list[CollectionItem]:
        del scope
        return [
            CollectionItem(
                id=FILE_HIERARCHY_NODE_ID,
                title=FILE_DISPLAY_NAME,
                collection_kind=CollectionKind.FOLDER,
                source=SourceIdentity(
                    connector_id=str(self.config.get("connector_id") or FILE_SOURCE),
                    provider=SourceProvider.FILE,
                    external_id=FILE_HIERARCHY_NODE_ID,
                ),
            )
        ]

    def next_checkpoint(self) -> ConnectorCheckpoint:
        return self._next_checkpoint.model_copy(deep=True)

    def _records_for_scope(self, scope: ConnectorScope) -> Iterator[FileRecord]:
        if self._records_configured:
            if scope.scope_value == FILE_SCOPE_VALUE:
                yield from self._records.values()
                return
            record = self._records.get(scope.scope_value)
            if record is not None:
                yield record
            return
        if scope.scope_value != FILE_SCOPE_VALUE:
            yield self._load_record(scope.scope_value)
            return
        if not self.base_dir.exists():
            return
        for record_path in sorted(self.base_dir.glob("*.json")):
            yield self._load_record(record_path.stem)

    def _load_record(self, external_id: str) -> FileRecord:
        record_path = _confined_path(self.base_dir, self.base_dir / f"{external_id}.json")
        if not record_path.is_file():
            raise FileNotFoundError(f"File record not found: {external_id}")

        try:
            data = json.loads(record_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid file record {record_path.name}: {exc.msg}") from exc
        if not isinstance(data, dict):
            raise ValueError(f"File record must be an object: {record_path.name}")

        storage_key = str(data.get("storage_key") or "").strip() or None
        raw_path = str(data.get("path") or "").strip()
        file_path: Path | None = None
        if raw_path:
            candidate = Path(raw_path)
            file_path = candidate if candidate.is_absolute() else self.base_dir / candidate
            file_path = _confined_path(self.base_dir, file_path)
            if not file_path.is_file():
                raise FileNotFoundError(f"File not found: {file_path}")
        if file_path is None and storage_key is None:
            raise ValueError(f"File record has no storage key: {external_id}")
        file_name = str(data.get("file_name") or (file_path.name if file_path else "")).strip()
        if not file_name:
            raise ValueError(f"File name is empty: {external_id}")
        declared_size = int(data.get("size_bytes") or 0)
        actual_size = file_path.stat().st_size if file_path is not None else declared_size
        if actual_size < 1 or (declared_size and declared_size != actual_size):
            raise ValueError(f"File size mismatch: {external_id}")
        uploaded_at = _parse_datetime(
            data.get("uploaded_at"),
            fallback=datetime.fromtimestamp(record_path.stat().st_mtime, tz=timezone.utc),
        )
        modified_at = max(
            uploaded_at,
            datetime.fromtimestamp(record_path.stat().st_mtime, tz=timezone.utc),
            *(
                [datetime.fromtimestamp(file_path.stat().st_mtime, tz=timezone.utc)]
                if file_path is not None
                else []
            ),
        )
        raw_metadata = data.get("metadata") or {}
        if not isinstance(raw_metadata, Mapping):
            raise ValueError(f"File metadata must be an object: {external_id}")
        metadata = {
            str(key): [str(item) for item in value] if isinstance(value, list) else str(value)
            for key, value in raw_metadata.items()
        }
        resolved_external_id = str(data.get("external_id") or external_id).strip()
        if not resolved_external_id:
            raise ValueError(f"File external_id is empty: {record_path.name}")
        return FileRecord(
            external_id=resolved_external_id,
            file_name=file_name,
            path=file_path,
            storage_key=storage_key,
            size_bytes=actual_size,
            mime_type=str(data.get("mime_type") or mimetypes.guess_type(file_name)[0] or "") or None,
            provider_version=str(
                data.get("provider_version") or data.get("version") or max(
                    record_path.stat().st_mtime_ns,
                    file_path.stat().st_mtime_ns if file_path else 0,
                )
            ),
            uploaded_at=uploaded_at,
            modified_at=modified_at,
            access=_access_from_mapping(data.get("acl") or {}, default=self._default_access),
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
        access: AccessPolicy | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least one")
        self.file_locations = [Path(location).expanduser() for location in (file_locations or [])]
        self.file_names = list(file_names or [])
        if self.file_names and len(self.file_names) != len(self.file_locations):
            raise ValueError("file_names must be empty or match file_locations")
        self.batch_size = batch_size
        self._processor = processor or FileProcessor()
        self._access = access or AccessPolicy()

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        del credentials
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        batch: list[AnyItem] = []
        for index, path in enumerate(self.file_locations):
            if not path.is_file():
                raise FileNotFoundError(f"Local connector file not found: {path}")
            display_name = self.file_names[index] if self.file_names else path.name
            external_id = _local_file_id(path)
            provider_version = str(path.stat().st_mtime_ns)
            processed = self._processor.process_path(
                path,
                file_name=display_name,
                item_id=external_id,
                title=display_name,
                source=SourceIdentity(
                    connector_id=FILE_SOURCE,
                    provider=SourceProvider.FILE,
                    external_id=external_id,
                    external_version=provider_version,
                    etag=None,
                ),
                access=self._access,
                metadata={
                    "source_kind": "local_file",
                    "file_name": display_name,
                },
                document_kind=_document_kind(mimetypes.guess_type(display_name)[0]),
                original=StorageObject(
                    provider="local",
                    key=str(path.resolve()),
                    file_name=display_name,
                    size_bytes=path.stat().st_size,
                    content_type=mimetypes.guess_type(display_name)[0],
                ),
            )
            batch.append(
                processed.item.model_copy(
                    update={
                        "updated_at": datetime.fromtimestamp(
                            path.stat().st_mtime, tz=timezone.utc
                        )
                    }
                )
            )
            if len(batch) >= self.batch_size:
                yield batch
                batch = []
        if batch:
            yield batch


def _document_kind(mime_type: str | None) -> DocumentKind:
    if (mime_type or "").startswith("image/"):
        return DocumentKind.IMAGE
    if mime_type == "application/pdf":
        return DocumentKind.PDF
    if mime_type in {"text/html", "application/xhtml+xml"}:
        return DocumentKind.WEB_PAGE
    return DocumentKind.DOCUMENT


def _access_from_mapping(
    value: Any,
    *,
    default: AccessPolicy | None = None,
) -> AccessPolicy:
    if not isinstance(value, Mapping):
        return default.model_copy(deep=True) if default else AccessPolicy()
    has_acl_key = any(
        key in value
        for key in (
            "user_emails",
            "user_group_ids",
            "source_reader_ids",
            "source_denied_reader_ids",
            "is_public",
            "public",
        )
    )
    if not has_acl_key:
        return default.model_copy(deep=True) if default else AccessPolicy()
    readers = [
        *(f"email:{email}" for email in value.get("user_emails") or []),
        *(f"external_group:{group}" for group in value.get("user_group_ids") or []),
        *(str(reader) for reader in value.get("source_reader_ids") or []),
    ]
    if bool(value.get("is_public", value.get("public", False))):
        readers.append("public")
    denied = [str(reader) for reader in value.get("source_denied_reader_ids") or []]
    allowed_policy = AccessPolicy.from_reader_ids(readers)
    deny_rules = [
        AccessRule(
            effect=AccessEffect.DENY,
            principal=Principal(
                type=reader.split(":", 1)[0] if ":" in reader else "source",
                id=reader.split(":", 1)[1] if ":" in reader else reader,
            ),
        )
        for reader in denied
        if reader.strip()
    ]
    return AccessPolicy(
        direct=DirectAccess(
            inherit=allowed_policy.direct.inherit,
            rules=[*allowed_policy.direct.rules, *deny_rules],
        ),
        effective=EffectiveAccess(reader_ids=allowed_policy.effective.reader_ids),
    )


def _confined_path(base_dir: Path, candidate: Path) -> Path:
    resolved_base = base_dir.resolve()
    resolved_candidate = candidate.resolve()
    if not resolved_candidate.is_relative_to(resolved_base):
        raise ValueError(f"File path escapes base_dir: {candidate}")
    return resolved_candidate


def _parse_datetime(value: Any, *, fallback: datetime) -> datetime:
    if value in (None, ""):
        return fallback
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"Invalid ISO timestamp: {value!r}") from exc
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _safe_storage_part(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_." else "_" for character in value)
    return cleaned.strip("._") or "unnamed"


def _local_file_id(path: Path) -> str:
    stable_path = str(path.resolve()).encode("utf-8")
    return f"file::{hashlib.sha256(stable_path).hexdigest()}"


def _storage_object(
    storage: RawObjectStore,
    stored: object,
    *,
    key: str,
    file_name: str,
    content_type: str | None,
    size_bytes: int,
) -> StorageObject:
    return StorageObject(
        provider=_optional_attribute(storage, "provider"),
        bucket=_optional_attribute(storage, "bucket"),
        key=key,
        file_name=file_name,
        size_bytes=_integer_attribute(stored, "size_bytes") or size_bytes,
        content_type=_optional_attribute(stored, "content_type") or content_type,
        etag=_optional_attribute(stored, "etag"),
        version_id=_optional_attribute(stored, "version_id"),
    )


def _optional_attribute(value: object, name: str) -> str | None:
    candidate = getattr(value, name, None)
    if not isinstance(candidate, str):
        return None
    normalized = candidate.strip()
    return normalized or None


def _integer_attribute(value: object, name: str) -> int | None:
    candidate = getattr(value, name, None)
    return candidate if isinstance(candidate, int) and not isinstance(candidate, bool) else None


__all__ = [
    "FILE_CONNECTOR_NAME",
    "FILE_DISPLAY_NAME",
    "FILE_HIERARCHY_NODE_ID",
    "FILE_SCOPE_VALUE",
    "FILE_SOURCE",
    "FileConnector",
    "FileRecord",
    "LocalFileConnector",
]
