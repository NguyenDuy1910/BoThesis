"""Google Drive adapter producing canonical Items for governed ingestion."""

from __future__ import annotations

import asyncio
import hashlib
import mimetypes
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import quote

import httpx

from bothesis.connector.base import BaseSourceConnector
from bothesis.connector.file import FileProcessor, FinxFileExtensions
from bothesis.connector.protocol import (
    AccessPolicy,
    AnyItem,
    ChangeType,
    Chunk,
    CollectionItem,
    CollectionKind,
    ConnectorCheckpoint,
    ConnectorScope,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    ItemChange,
    SourceIdentity,
    SourceProvider,
    StorageObject,
)
from bothesis.connector.protocol import RawObjectStore
from bothesis.storage import StoredObject

from .checkpoint import GoogleDriveCheckpoint

_DRIVE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_GOOGLE_MIME_PREFIX = "application/vnd.google-apps."
_EXPORT_MIME_TYPES = {
    "application/vnd.google-apps.document": ("text/html", ".html"),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("image/png", ".png"),
}
_MIME_EXTENSIONS = {
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": ".pptx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": ".xlsx",
    "text/plain": ".txt",
    "text/csv": ".csv",
    "text/html": ".html",
    "application/json": ".json",
    "application/xml": ".xml",
}
_FILE_FIELDS = (
    "id,name,mimeType,modifiedTime,createdTime,version,md5Checksum,"
    "webViewLink,webContentLink,size,parents,driveId,description,"
    "owners(emailAddress,displayName),"
    "permissions(id,type,emailAddress,domain,role,allowFileDiscovery,deleted)"
)
_MAX_SOURCE_FILE_BYTES = 100 * 1024 * 1024


class GoogleDriveConnector(BaseSourceConnector):
    """Read a selected Drive or Shared Drive with the Google Changes API."""

    source = SourceProvider.GOOGLE_DRIVE.value
    checkpoint_model = GoogleDriveCheckpoint

    def __init__(self, config: dict[str, Any], credentials: dict[str, Any]) -> None:
        self._config = dict(config)
        self._credentials = dict(credentials)
        self._api_url = _required_url(config.get("_google_drive_api_url"))
        self._token_url = _required_url(config.get("_google_drive_token_url"))
        self._client_id = _required_text(
            config.get("_google_drive_client_id"), "Google Drive client ID"
        )
        self._client_secret = _required_text(
            config.get("_google_drive_client_secret"), "Google Drive client secret"
        )
        self._timeout_seconds = _positive_number(
            config.get("_google_drive_timeout_seconds"), default=20.0
        )
        self._connector_id = _required_text(
            config.get("_integration_connection_id") or config.get("connector_id"),
            "integration connection ID",
        )
        self._tenant_id = _required_text(config.get("_tenant_id"), "tenant ID")
        self._folder_id = _optional_text(config.get("folder_id"))
        self._shared_drive_id = _optional_text(config.get("shared_drive_id"))
        if self._folder_id and self._shared_drive_id:
            raise ValueError("Google Drive source may select a folder or a Shared Drive, not both")
        self._scope = self._scope_value()
        self._processed_chunks: dict[str, tuple[Chunk, ...]] = {}
        self._files: dict[str, dict[str, Any]] = {}
        self._next_checkpoint = GoogleDriveCheckpoint()
        self._storage: RawObjectStore | None = None
        self._credentials_refreshed = False
        self._access_token = _required_text(
            credentials.get("access_token"), "Google Drive access token"
        )
        self._refresh_token = _optional_text(credentials.get("refresh_token"))
        self._expires_at = _parse_timestamp(credentials.get("expires_at"))

    def set_storage(self, storage: RawObjectStore) -> None:
        self._storage = storage

    @property
    def refreshed_credentials(self) -> dict[str, Any] | None:
        """Return rotation-safe OAuth credentials only when the token changed."""

        if not self._credentials_refreshed:
            return None
        return dict(self._credentials)

    async def test_connection(self) -> bool:
        payload = await self._get_json(
            "about",
            params={"fields": "user(emailAddress,displayName)"},
        )
        user = payload.get("user")
        if not isinstance(user, dict) or not _optional_text(user.get("emailAddress")):
            raise ValueError("Google Drive did not return the connected account")
        return True

    async def list_scopes(self) -> list[ConnectorScope]:
        return [
            ConnectorScope(
                scope_type=(
                    "shared_drive"
                    if self._shared_drive_id
                    else "folder"
                    if self._folder_id
                    else "drive"
                ),
                scope_value=self._scope,
                display_name=(
                    "Shared Drive"
                    if self._shared_drive_id
                    else "Google Drive folder"
                    if self._folder_id
                    else "My Drive"
                ),
            )
        ]

    async def discover_changes(
        self,
        checkpoint: ConnectorCheckpoint,
        scope: ConnectorScope,
    ) -> list[ItemChange]:
        self._validate_scope(scope)
        self._processed_chunks.clear()
        typed_checkpoint = (
            checkpoint
            if isinstance(checkpoint, GoogleDriveCheckpoint)
            else GoogleDriveCheckpoint.model_validate(checkpoint.model_dump())
        )
        if typed_checkpoint.scope_fingerprint != self._scope_fingerprint:
            return await self._initial_changes()
        if typed_checkpoint.start_page_token is None:
            return await self._initial_changes()
        try:
            return await self._incremental_changes(typed_checkpoint.start_page_token)
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code != 410:
                raise
            # Google invalidates old change tokens. A full listing is the only
            # authoritative recovery and the pipeline upserts idempotently.
            return await self._initial_changes()

    async def fetch_item(self, item_id: str) -> DocumentItem:
        file = self._files.get(item_id)
        if file is None:
            file = await self._file(item_id)
        if not self._is_supported_file(file):
            raise ValueError("Google Drive item is not an ingestible file")
        content, content_type, file_name = await self._download(file)
        source = SourceIdentity(
            connector_id=self._connector_id,
            provider=SourceProvider.GOOGLE_DRIVE,
            external_id=_required_text(file.get("id"), "Google Drive file ID"),
            external_version=_file_version(file),
            etag=_optional_text(file.get("md5Checksum")),
            url=_optional_text(file.get("webViewLink")),
        )
        stored = await self._store_original(
            data=content,
            file_id=source.external_id,
            file_name=file_name,
            content_type=content_type,
        )
        processed = await asyncio.to_thread(
            FileProcessor(max_file_bytes=_MAX_SOURCE_FILE_BYTES).process_bytes,
            content,
            file_name=file_name,
            item_id=source.external_id,
            title=_required_text(file.get("name"), "Google Drive file name"),
            source=source,
            document_kind=_document_kind(content_type),
            hierarchy=Hierarchy(parent_id=self._root_external_id()),
            access=_access_policy(file),
            metadata=_metadata(file, exported_content_type=content_type),
            original=stored,
        )
        self._processed_chunks[processed.item.id] = processed.chunks
        return processed.item.model_copy(
            update={
                "created_at": _parse_timestamp(file.get("createdTime")),
                "updated_at": _parse_timestamp(file.get("modifiedTime")),
            }
        )

    async def fetch_chunks(self, item: DocumentItem) -> tuple[Chunk, ...] | None:
        return self._processed_chunks.pop(item.id, None)

    async def fetch_hierarchy(self, scope: ConnectorScope) -> list[AnyItem]:
        self._validate_scope(scope)
        root_id = self._root_external_id()
        return [
            CollectionItem(
                id=root_id,
                title=(await self.list_scopes())[0].display_name,
                collection_kind=CollectionKind.FOLDER,
                source=SourceIdentity(
                    connector_id=self._connector_id,
                    provider=SourceProvider.GOOGLE_DRIVE,
                    external_id=root_id,
                ),
            )
        ]

    def next_checkpoint(self) -> GoogleDriveCheckpoint:
        return self._next_checkpoint.model_copy(deep=True)

    async def _initial_changes(self) -> list[ItemChange]:
        start_page_token = await self._start_page_token()
        files = await self._list_scope_files()
        self._files = {file["id"]: file for file in files}
        self._next_checkpoint = GoogleDriveCheckpoint(
            start_page_token=start_page_token,
            scope_fingerprint=self._scope_fingerprint,
        )
        return [
            ItemChange(
                type=ChangeType.CREATED,
                item_id=file["id"],
                provider_version=_file_version(file),
                occurred_at=_parse_timestamp(file.get("modifiedTime")),
            )
            for file in files
        ]

    async def _incremental_changes(self, start_page_token: str) -> list[ItemChange]:
        page_token = start_page_token
        changes: list[ItemChange] = []
        files: dict[str, dict[str, Any]] = {}
        next_start_page_token: str | None = None
        while True:
            payload = await self._get_json(
                "changes",
                params={
                    "pageToken": page_token,
                    "pageSize": "1000",
                    "includeRemoved": "true",
                    "includeItemsFromAllDrives": "true",
                    "supportsAllDrives": "true",
                    "fields": f"nextPageToken,newStartPageToken,changes(fileId,removed,file({_FILE_FIELDS}))",
                    **self._drive_parameters(),
                },
            )
            raw_changes = payload.get("changes")
            if not isinstance(raw_changes, list):
                raise ValueError("Google Drive changes response is invalid")
            for raw_change in raw_changes:
                if not isinstance(raw_change, dict):
                    continue
                file_id = _optional_text(raw_change.get("fileId"))
                if file_id is None:
                    continue
                file = raw_change.get("file")
                if raw_change.get("removed") is True:
                    changes.append(ItemChange(type=ChangeType.DELETED, item_id=file_id))
                    continue
                if not isinstance(file, dict):
                    file = await self._file(file_id)
                if not self._is_supported_file(file) or not self._in_scope(file):
                    changes.append(ItemChange(type=ChangeType.DELETED, item_id=file_id))
                    continue
                files[file_id] = file
                changes.append(
                    ItemChange(
                        type=ChangeType.UPDATED,
                        item_id=file_id,
                        provider_version=_file_version(file),
                        occurred_at=_parse_timestamp(file.get("modifiedTime")),
                    )
                )
            next_page_token = _optional_text(payload.get("nextPageToken"))
            candidate_start_token = _optional_text(payload.get("newStartPageToken"))
            if candidate_start_token is not None:
                next_start_page_token = candidate_start_token
            if next_page_token is None:
                break
            page_token = next_page_token
        if next_start_page_token is None:
            next_start_page_token = await self._start_page_token()
        self._files = files
        self._next_checkpoint = GoogleDriveCheckpoint(
            start_page_token=next_start_page_token,
            scope_fingerprint=self._scope_fingerprint,
        )
        return changes

    async def _list_scope_files(self) -> list[dict[str, Any]]:
        page_token: str | None = None
        files: list[dict[str, Any]] = []
        while True:
            payload = await self._get_json(
                "files",
                params={
                    "q": self._list_query(),
                    "pageSize": "1000",
                    "orderBy": "modifiedTime,id",
                    "fields": f"nextPageToken,files({_FILE_FIELDS})",
                    "includeItemsFromAllDrives": "true",
                    "supportsAllDrives": "true",
                    **self._drive_parameters(),
                    **({"pageToken": page_token} if page_token else {}),
                },
            )
            raw_files = payload.get("files")
            if not isinstance(raw_files, list):
                raise ValueError("Google Drive files response is invalid")
            files.extend(
                file
                for file in raw_files
                if isinstance(file, dict) and self._is_supported_file(file)
            )
            page_token = _optional_text(payload.get("nextPageToken"))
            if page_token is None:
                return files

    async def _file(self, file_id: str) -> dict[str, Any]:
        payload = await self._get_json(
            f"files/{quote(file_id, safe='')}",
            params={
                "fields": _FILE_FIELDS,
                "supportsAllDrives": "true",
            },
        )
        if _optional_text(payload.get("id")) is None:
            raise ValueError("Google Drive did not return a file ID")
        return payload

    async def _start_page_token(self) -> str:
        payload = await self._get_json(
            "changes/startPageToken",
            params={"supportsAllDrives": "true", **self._drive_parameters()},
        )
        return _required_text(payload.get("startPageToken"), "Google Drive page token")

    async def _download(self, file: dict[str, Any]) -> tuple[bytes, str, str]:
        file_id = _required_text(file.get("id"), "Google Drive file ID")
        mime_type = _required_text(file.get("mimeType"), "Google Drive file type")
        if mime_type in _EXPORT_MIME_TYPES:
            export_type, extension = _EXPORT_MIME_TYPES[mime_type]
            return (
                await self._get_bytes(
                    f"files/{quote(file_id, safe='')}/export",
                    params={
                        "mimeType": export_type,
                        "supportsAllDrives": "true",
                    },
                ),
                export_type,
                _file_name(file, extension),
            )
        content_type = mime_type
        return (
            await self._get_bytes(
                f"files/{quote(file_id, safe='')}",
                params={"alt": "media", "supportsAllDrives": "true"},
            ),
            content_type,
            _file_name(file, _extension_for_mime(content_type)),
        )

    async def _store_original(
        self,
        *,
        data: bytes,
        file_id: str,
        file_name: str,
        content_type: str,
    ) -> StorageObject:
        if self._storage is None:
            raise RuntimeError("Google Drive ingestion requires configured object storage")
        key = (
            f"tenants/{_storage_part(self._tenant_id)}/sources/"
            f"{_storage_part(self._connector_id)}/google_drive/"
            f"{_storage_part(file_id)}/{_storage_part(file_name)}"
        )
        stored = await asyncio.to_thread(
            self._storage.put_bytes,
            data,
            key,
            content_type=content_type,
        )
        if not isinstance(stored, StoredObject):
            raise RuntimeError("configured object storage returned invalid metadata")
        return StorageObject(
            provider=_optional_text(getattr(self._storage, "provider", None)),
            bucket=_optional_text(getattr(self._storage, "bucket", None)),
            key=key,
            file_name=file_name,
            size_bytes=stored.size_bytes,
            content_type=stored.content_type or content_type,
            etag=stored.etag,
            version_id=stored.version_id,
        )

    async def _get_json(
        self, path: str, *, params: dict[str, str]
    ) -> dict[str, Any]:
        response = await self._request("GET", path, params=params)
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Google Drive returned an invalid JSON response")
        return payload

    async def _get_bytes(
        self, path: str, *, params: dict[str, str]
    ) -> bytes:
        for retry in range(2):
            await self._ensure_access_token()
            headers = {"Authorization": f"Bearer {self._access_token}"}
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                async with client.stream(
                    "GET", f"{self._api_url}/{path}", params=params, headers=headers
                ) as response:
                    if response.status_code == 401 and retry == 0 and self._refresh_token:
                        await self._refresh_access_token()
                        continue
                    response.raise_for_status()
                    content_length = _content_length(response.headers.get("Content-Length"))
                    if content_length is not None and content_length > _MAX_SOURCE_FILE_BYTES:
                        raise ValueError("Google Drive file exceeds the 100 MiB ingestion limit")
                    output = bytearray()
                    async for block in response.aiter_bytes():
                        output.extend(block)
                        if len(output) > _MAX_SOURCE_FILE_BYTES:
                            raise ValueError("Google Drive file exceeds the 100 MiB ingestion limit")
                    if not output:
                        raise ValueError("Google Drive returned an empty file")
                    return bytes(output)
        raise RuntimeError("Google Drive download authorization could not be refreshed")

    async def _request(
        self, method: str, path: str, *, params: dict[str, str]) -> httpx.Response:
        for retry in range(2):
            await self._ensure_access_token()
            async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
                response = await client.request(
                    method,
                    f"{self._api_url}/{path}",
                    params=params,
                    headers={"Authorization": f"Bearer {self._access_token}"},
                )
            if response.status_code == 401 and retry == 0 and self._refresh_token:
                await self._refresh_access_token()
                continue
            response.raise_for_status()
            return response
        raise RuntimeError("Google Drive authorization could not be refreshed")

    async def _ensure_access_token(self) -> None:
        if self._expires_at is None or self._expires_at <= datetime.now(UTC) + timedelta(seconds=90):
            await self._refresh_access_token()

    async def _refresh_access_token(self) -> None:
        if self._refresh_token is None:
            raise ValueError("Google Drive authorization has expired; reconnect the account")
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await client.post(
                self._token_url,
                data={
                    "client_id": self._client_id,
                    "client_secret": self._client_secret,
                    "grant_type": "refresh_token",
                    "refresh_token": self._refresh_token,
                },
            )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise ValueError("Google Drive token refresh returned invalid JSON")
        self._access_token = _required_text(payload.get("access_token"), "Google Drive access token")
        new_refresh_token = _optional_text(payload.get("refresh_token"))
        if new_refresh_token is not None:
            self._refresh_token = new_refresh_token
        expires_in = _positive_number(payload.get("expires_in"), default=3600.0)
        self._expires_at = datetime.now(UTC) + timedelta(seconds=expires_in)
        self._credentials = {
            **self._credentials,
            "access_token": self._access_token,
            "refresh_token": self._refresh_token,
            "expires_at": self._expires_at.isoformat(),
            "token_type": _optional_text(payload.get("token_type")) or "Bearer",
            "scope": _optional_text(payload.get("scope"))
            or _optional_text(self._credentials.get("scope")),
        }
        self._credentials_refreshed = True

    def _validate_scope(self, scope: ConnectorScope) -> None:
        expected = (awaitable_scope := self._scope)
        if scope.scope_value != expected:
            raise ValueError("Google Drive source scope does not match the runtime configuration")

    def _scope_value(self) -> str:
        if self._shared_drive_id:
            return self._shared_drive_id
        if self._folder_id:
            return self._folder_id
        return "my-drive"

    def _root_external_id(self) -> str:
        return f"google_drive::{self._scope}"

    @property
    def _scope_fingerprint(self) -> str:
        return hashlib.sha256(self._scope.encode("utf-8")).hexdigest()

    def _drive_parameters(self) -> dict[str, str]:
        if self._shared_drive_id:
            return {"corpora": "drive", "driveId": self._shared_drive_id}
        return {"corpora": "user"}

    def _list_query(self) -> str:
        conditions = ["trashed = false", f"mimeType != '{_DRIVE_FOLDER_MIME_TYPE}'"]
        if self._folder_id:
            conditions.append(f"'{_drive_literal(self._folder_id)}' in parents")
        return " and ".join(conditions)

    def _in_scope(self, file: dict[str, Any]) -> bool:
        if self._shared_drive_id:
            return _optional_text(file.get("driveId")) == self._shared_drive_id
        if self._folder_id:
            parents = file.get("parents")
            return isinstance(parents, list) and self._folder_id in parents
        return file.get("trashed") is not True

    @staticmethod
    def _is_supported_file(file: dict[str, Any]) -> bool:
        mime_type = _optional_text(file.get("mimeType"))
        if mime_type is None or mime_type == _DRIVE_FOLDER_MIME_TYPE:
            return False
        if mime_type in _EXPORT_MIME_TYPES:
            return True
        if mime_type.startswith(_GOOGLE_MIME_PREFIX):
            return False
        name = _optional_text(file.get("name"))
        if name is None:
            return False
        extension = name.rpartition(".")[2].casefold()
        if extension and f".{extension}" in FinxFileExtensions.ALL_ALLOWED_EXTENSIONS:
            return True
        return _extension_for_mime(mime_type) is not None


def _required_url(value: Any) -> str:
    result = _required_text(value, "Google Drive URL")
    if not result.startswith(("https://", "http://")):
        raise ValueError("Google Drive URL must be an HTTP URL")
    return result.rstrip("/")


def _required_text(value: Any, label: str) -> str:
    result = _optional_text(value)
    if result is None:
        raise ValueError(f"{label} is required")
    return result


def _optional_text(value: Any) -> str | None:
    result = str(value).strip() if value is not None else ""
    return result or None


def _positive_number(value: Any, *, default: float) -> float:
    if value is None or value == "":
        return default
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError("Google Drive timeout or token lifetime is invalid") from exc
    if result <= 0:
        raise ValueError("Google Drive timeout or token lifetime must be positive")
    return result


def _parse_timestamp(value: Any) -> datetime | None:
    normalized = _optional_text(value)
    if normalized is None:
        return None
    try:
        timestamp = datetime.fromisoformat(normalized.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("Google Drive returned an invalid timestamp") from exc
    return timestamp if timestamp.tzinfo else timestamp.replace(tzinfo=UTC)


def _file_version(file: dict[str, Any]) -> str:
    return _required_text(
        file.get("version") or file.get("modifiedTime"), "Google Drive file version"
    )


def _extension_for_mime(mime_type: str) -> str | None:
    return _MIME_EXTENSIONS.get(mime_type) or mimetypes.guess_extension(mime_type)


def _file_name(file: dict[str, Any], extension: str | None) -> str:
    name = _required_text(file.get("name"), "Google Drive file name")
    if extension and "." not in name.rsplit("/", 1)[-1]:
        return f"{name}{extension}"
    return name


def _document_kind(mime_type: str) -> DocumentKind:
    if mime_type.startswith("image/"):
        return DocumentKind.IMAGE
    if mime_type == "application/pdf":
        return DocumentKind.PDF
    if mime_type in {"text/html", "application/xhtml+xml"}:
        return DocumentKind.WEB_PAGE
    return DocumentKind.DOCUMENT


def _metadata(file: dict[str, Any], *, exported_content_type: str) -> dict[str, str | list[str]]:
    values: dict[str, str | list[str]] = {
        "source_kind": "google_drive",
        "file_name": _required_text(file.get("name"), "Google Drive file name"),
        "google_mime_type": _required_text(file.get("mimeType"), "Google Drive file type"),
        "content_type": exported_content_type,
    }
    for key in ("driveId", "description", "webViewLink"):
        value = _optional_text(file.get(key))
        if value is not None:
            values[key] = value
    owners = file.get("owners")
    if isinstance(owners, list):
        emails = [
            email
            for owner in owners
            if isinstance(owner, dict)
            and (email := _optional_text(owner.get("emailAddress"))) is not None
        ]
        if emails:
            values["owner_emails"] = emails
    return values


def _access_policy(file: dict[str, Any]) -> AccessPolicy:
    reader_ids: list[str] = []
    permissions = file.get("permissions")
    if not isinstance(permissions, list):
        return AccessPolicy()
    for permission in permissions:
        if not isinstance(permission, dict) or permission.get("deleted") is True:
            continue
        role = _optional_text(permission.get("role"))
        if role not in {"owner", "organizer", "fileOrganizer", "writer", "commenter", "reader"}:
            continue
        permission_type = _optional_text(permission.get("type"))
        if permission_type == "user":
            email = _optional_text(permission.get("emailAddress"))
            if email:
                reader_ids.append(f"google_user:{email.casefold()}")
        elif permission_type == "group":
            email = _optional_text(permission.get("emailAddress"))
            if email:
                reader_ids.append(f"google_group:{email.casefold()}")
        elif permission_type == "domain":
            domain = _optional_text(permission.get("domain"))
            if domain:
                reader_ids.append(f"google_domain:{domain.casefold()}")
        elif permission_type == "anyone":
            reader_ids.append("google_anyone:public")
    return AccessPolicy.from_reader_ids(reader_ids)


def _storage_part(value: str) -> str:
    return quote(value, safe="-_.")


def _drive_literal(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _content_length(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        result = int(value)
    except ValueError:
        return None
    return result if result >= 0 else None


__all__ = ["GoogleDriveConnector"]
