"""Conversation artifacts: documents the agent creates and revises for a user."""

from __future__ import annotations

import asyncio
import logging
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.agent.models import AgentContext, ConversationArtifact
from bothesis.db.engine import SessionFactory, transaction_scope
from bothesis.db.models import ArtifactRevision, Item
from bothesis.services import (
    COLLECTION_READ_PERMISSION,
    COLLECTION_UPDATE_PERMISSION,
    ARTIFACT_COLLECTION_KIND,
    ARTIFACT_COLLECTION_TITLE,
    ARTIFACT_DOCUMENT_TYPE,
    ARTIFACT_MIME_TYPE,
    KNOWLEDGE_READ_PERMISSION,
    ArtifactValidationError,
    AuthContext,
    DocumentNotFoundError,
    require_tenant_permission,
    require_user_identity,
    timestamp,
)
from bothesis.services.audit import AuditService
from bothesis.services.identity_access.authorization import AuthorizationService
from bothesis.services.document_upload import DocumentUploadService
from bothesis.services.identity_access.identity_store import resolve_agent_access
from bothesis.services.item import ItemService
from bothesis.storage import DocumentStorage, ObjectNotFoundError

log = logging.getLogger(__name__)

_MAX_TITLE_LENGTH = 200
_MAX_SOURCE_DOCUMENT_BYTES = 20 * 1024 * 1024
_PDF_CONTENT_TYPE = "application/pdf"
_TRUNCATION_MARKER = "\n…[content truncated]…\n"
_DEFAULT_OUTPUT_NAME = "document"
# The file extensions a produced file is named by when the workspace reported
# no usable content type. Everything else falls back to an opaque binary type,
# which is enough for storage and download.
_MIME_TYPES = {
    ".md": ARTIFACT_MIME_TYPE,
    ".markdown": ARTIFACT_MIME_TYPE,
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
    ".html": "text/html",
    ".pdf": _PDF_CONTENT_TYPE,
    ".docx": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    ),
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".pptx": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation"
    ),
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".zip": "application/zip",
}
_DEFAULT_MIME_TYPE = "application/octet-stream"


class ArtifactService:
    """Own artifact Items, their immutable revisions, and publishing.

    An artifact is a canonical ``Item`` under the caller's private artifact
    Collection, so tenant scoping, ownership, message lineage, and tombstones
    are the ordinary Item rules. Every content change is a new
    :class:`ArtifactRevision` with its own object; the Item's ``storage_key``
    always points at the current revision.

    No file is manipulated here. The agent produces files in its hosted
    execution workspace, and this service is the durable side of that: it
    stores the bytes that came back, hands out download URLs, and reads
    originals back out when a workspace has to be rebuilt. An artifact is a
    conversation document, never Knowledge Base content — :meth:`publish` is
    the one explicit, user-initiated step that crosses that line.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        object_storage: Callable[[], DocumentStorage],
        uploads: Callable[[], DocumentUploadService],
        max_content_bytes: int,
        download_url_seconds: int,
    ) -> None:
        if min(max_content_bytes, download_url_seconds) < 1:
            raise ValueError("artifact limits must be greater than zero")
        self._sessions = session_factory
        self._object_storage = object_storage
        self._uploads = uploads
        self._max_content_bytes = max_content_bytes
        self._download_url_seconds = download_url_seconds

    # -- Agent boundary -----------------------------------------------------

    async def resolve_access(self, scope: AgentContext) -> AuthContext:
        """Re-resolve the authenticated caller behind an agent tool call."""

        return await resolve_agent_access(
            self._sessions, user_id=scope.user_id, tenant_id=scope.tenant_id
        )

    async def conversation_artifacts(
        self,
        access: AuthContext,
        conversation_id: UUID,
        *,
        content_characters: int,
    ) -> tuple[ConversationArtifact, ...]:
        """The working documents of one conversation, with bounded content.

        Only artifacts the caller created in their own tenant are returned; a
        conversation is private to its user, and so are its documents.
        """

        if access.tenant_id is None:
            return ()
        async with transaction_scope(self._sessions) as session:
            items = await self._conversation_items(session, access, conversation_id)
            revisions = {
                item.id: await self._revisions(session, item.id) for item in items
            }
        references: list[ConversationArtifact] = []
        for item in items:
            current = revisions[item.id][-1]
            reference = ConversationArtifact.from_payload(
                self._payload(item, revisions[item.id])
            )
            if not current.mime_type.startswith("text/"):
                # A binary file is named, not described: the model reads it in
                # the workspace, where it has the file itself.
                references.append(reference)
                continue
            text, truncated = await self._text(current.storage_key, content_characters)
            references.append(
                replace(reference, content=text, content_truncated=truncated)
            )
        return tuple(references)

    # -- Lifecycle ----------------------------------------------------------

    async def record_generated(
        self,
        access: AuthContext,
        *,
        conversation_id: UUID | None,
        request_id: str | None,
        file_name: str,
        mime_type: str,
        data: bytes,
        summary: str,
    ) -> dict[str, Any]:
        """Persist one file the agent produced as a downloadable document.

        A conversation keeps one document per file name, so writing
        ``report.xlsx`` a second time is revision 2 of the same document: the
        user sees one card with a history instead of a pile of near-identical
        files. The execution workspace the bytes came from is disposable; this
        record is what outlives it.
        """

        tenant_id = require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        name = _output_name(file_name)
        if not data:
            raise ArtifactValidationError(f"produced file is empty: {name}")
        if len(data) > self._max_content_bytes:
            raise ArtifactValidationError(
                f"produced file exceeds the {self._max_content_bytes} byte limit: {name}"
            )
        document = _ProducedDocument(
            file_name=name, mime_type=_mime_type(mime_type, name), data=data
        )
        existing = (
            await self._conversation_item(access, conversation_id, name)
            if conversation_id is not None
            else None
        )
        if existing is not None:
            return await self._add_revision(
                access,
                existing.id,
                document=document,
                summary=_summary(summary),
                conversation_id=conversation_id,
                request_id=request_id,
            )
        return await self._create(
            access,
            tenant_id,
            title=_title(name),
            document=document,
            summary=_summary(summary),
            conversation_id=conversation_id,
            request_id=request_id,
            source_document_id=None,
        )

    async def source_file(
        self, access: AuthContext, document_id: UUID
    ) -> WorkspaceSource:
        """Read one document the caller may read, as bytes with its file name.

        Any readable document Item is a valid source — a template or a form is
        an ordinary document with useful metadata, not a separate kind of
        thing — and reading one never modifies it. The Collection access check
        at read time is the whole authorization this needs.
        """

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with transaction_scope(self._sessions) as session:
            source = await AuthorizationService(session).require_item(
                document_id, access=access
            )
            if source.item_type != "document" or not source.storage_key:
                raise ArtifactValidationError("source is not an available document")
            title = source.title
            storage_key = source.storage_key
            mime_type = source.mime_type or ARTIFACT_MIME_TYPE
            name = _output_name(
                str(source.metadata_.get("file_name") or source.title),
                mime_type=mime_type,
            )
        data = await self._object_storage().read(
            storage_key, max_bytes=_MAX_SOURCE_DOCUMENT_BYTES
        )
        return WorkspaceSource(
            document_id=str(document_id),
            title=title,
            file_name=name,
            mime_type=mime_type,
            data=data,
        )

    async def conversation_files(
        self, access: AuthContext, conversation_id: UUID, *, limit: int = 10
    ) -> tuple[WorkspaceSource, ...]:
        """The current revision of every document this conversation produced.

        This is what a rebuilt workspace is seeded with: the files the user and
        the model were last working on, so a follow-up edit finds them again
        after the previous workspace expired. The newest ``limit`` files are
        returned, oldest first, which is the order they are written back in.
        """

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        if access.tenant_id is None:
            return ()
        async with transaction_scope(self._sessions) as session:
            items = list(await self._conversation_items(session, access, conversation_id))
            selected = items[-limit:]
            current = {
                item.id: (await self._revisions(session, item.id))[-1]
                for item in selected
            }
        sources: list[WorkspaceSource] = []
        for item in selected:
            revision = current[item.id]
            sources.append(
                WorkspaceSource(
                    document_id=str(item.id),
                    title=item.title,
                    file_name=_stored_file_name(item),
                    mime_type=revision.mime_type,
                    data=await self._bytes(revision.storage_key),
                )
            )
        return tuple(sources)

    async def _conversation_item(
        self, access: AuthContext, conversation_id: UUID, file_name: str
    ) -> Item | None:
        """The document this conversation already keeps under one file name."""

        if access.tenant_id is None:
            return None
        async with transaction_scope(self._sessions) as session:
            items = await self._conversation_items(session, access, conversation_id)
        return next(
            (item for item in items if _stored_file_name(item) == file_name), None
        )

    @staticmethod
    async def _conversation_items(
        session: AsyncSession, access: AuthContext, conversation_id: UUID
    ) -> Sequence[Item]:
        """Every artifact Item one conversation produced, oldest first.

        A conversation is private to its user, and so are its documents, so
        ownership is part of the query rather than a later check.
        """

        return list(
            await session.scalars(
                select(Item)
                .join(ArtifactRevision, ArtifactRevision.item_id == Item.id)
                .where(
                    ArtifactRevision.conversation_id == conversation_id,
                    ArtifactRevision.deleted_at.is_(None),
                    Item.tenant_id == access.tenant_id,
                    Item.created_by_user_id == access.user_id,
                    Item.status != "deleted",
                    Item.deleted_at.is_(None),
                )
                .distinct()
                .order_by(Item.created_at, Item.id)
            )
        )

    async def publish(
        self,
        access: AuthContext,
        artifact_id: UUID,
        *,
        collection_id: UUID,
        title: str | None = None,
    ) -> dict[str, Any]:
        """Copy the current revision into a Collection as a KB document.

        This is the one deliberate step that turns a working document into
        Knowledge Base content: it goes through the ordinary governed upload,
        so ACLs, indexing, previews, and audit are the upload's. Editor access
        on the destination Collection is the only gate — publishing does not
        require a specially designated Collection; any indexed document is
        already discoverable through knowledge_search regardless of which
        Collection it lands in.
        """

        require_user_identity(access)
        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        item, current = await self._load(access, artifact_id)
        async with transaction_scope(self._sessions) as session:
            target = await AuthorizationService(session).require_item(
                collection_id, access=access, permission=COLLECTION_UPDATE_PERMISSION
            )
            if target.item_type != "collection":
                raise ArtifactValidationError("the destination must be a Collection")
        file_name = _file_name(
            _title(title) if title else item.title,
            suffix=Path(_stored_file_name(item)).suffix or ".md",
        )
        upload = await self._uploads().upload_to_collection(
            access,
            collection_id,
            idempotency_key=f"artifact:{item.id}:r{current.revision_number}:{file_name}",
            file_name=file_name,
            content_type=current.mime_type,
            content=_BytesStream(await self._bytes(current.storage_key)),
        )
        async with transaction_scope(self._sessions) as session:
            await AuditService(session).record(
                access,
                action="artifact.published",
                resource_type="artifact",
                resource_id=str(item.id),
                details={
                    "revision": current.revision_number,
                    "collection_id": str(collection_id),
                    "item_id": str(upload.item.id),
                    "created": upload.created,
                },
            )
        return {
            "artifact_id": str(item.id),
            "revision": current.revision_number,
            "item_id": str(upload.item.id),
            "collection_id": str(collection_id),
            "title": upload.item.title,
            "status": upload.item.status,
            "created": upload.created,
        }

    # -- Reads --------------------------------------------------------------

    async def get(self, access: AuthContext, artifact_id: UUID) -> dict[str, Any]:
        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with transaction_scope(self._sessions) as session:
            item = await self._authorized_item(session, access, artifact_id)
            revisions = await self._revisions(session, item.id)
        return self._payload(item, revisions)

    async def content(
        self, access: AuthContext, artifact_id: UUID, *, revision: int | None = None
    ) -> dict[str, Any]:
        """Return one revision's text for in-app preview."""

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with transaction_scope(self._sessions) as session:
            item = await self._authorized_item(session, access, artifact_id)
            revisions = await self._revisions(session, item.id)
        selected = revisions[-1]
        if revision is not None:
            matches = [row for row in revisions if row.revision_number == revision]
            if not matches:
                raise DocumentNotFoundError(f"artifact revision not found: {revision}")
            selected = matches[0]
        # For a binary revision (a fillable PDF) the preview is its stored
        # description; the bytes themselves are reached via the download URL.
        text, truncated = await self._model_text(selected, self._max_content_bytes)
        return {
            "artifact_id": str(item.id),
            "revision": selected.revision_number,
            "mime_type": selected.mime_type,
            "content": text,
            "truncated": truncated,
        }

    # -- Internals ----------------------------------------------------------

    async def _create(
        self,
        access: AuthContext,
        tenant_id: UUID,
        *,
        title: str,
        document: _ProducedDocument,
        summary: str,
        conversation_id: UUID | None,
        request_id: str | None,
        source_document_id: UUID | None,
    ) -> dict[str, Any]:
        user_id = require_user_identity(access)
        item_id = uuid4()
        key = _revision_key(tenant_id, item_id, 1, document.file_name)
        await self._store_revision_objects(document, key)
        async with transaction_scope(self._sessions) as session:
            items = ItemService(session)
            collection_id = await items.ensure_personal_collection(
                user_id,
                tenant_id,
                collection_id=ItemService.artifact_collection_id(tenant_id, user_id),
                title=ARTIFACT_COLLECTION_TITLE,
                system_kind=ARTIFACT_COLLECTION_KIND,
            )
            item = await items.create_document(
                tenant_id=tenant_id,
                parent_item_id=collection_id,
                title=title,
                document_type=_document_type(document.mime_type),
                created_by_user_id=user_id,
                mime_type=document.mime_type,
                size_bytes=len(document.data),
                storage_key=key,
                metadata={
                    "file_name": document.file_name,
                    "artifact": {
                        "current_revision": 1,
                        "conversation_id": str(conversation_id) if conversation_id else None,
                        "source_document_id": (
                            str(source_document_id) if source_document_id else None
                        ),
                    },
                },
                status="ready",
                item_id=item_id,
            )
            revision = ArtifactRevision(
                item_id=item.id,
                revision_number=1,
                storage_key=key,
                mime_type=document.mime_type,
                size_bytes=len(document.data),
                summary=summary,
                conversation_id=conversation_id,
                request_id=request_id,
                created_by_user_id=user_id,
            )
            session.add(revision)
            await session.flush()
            await AuditService(session).record(
                access,
                action="artifact.created",
                resource_type="artifact",
                resource_id=str(item.id),
                details={
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "source_document_id": (
                        str(source_document_id) if source_document_id else None
                    ),
                    "size_bytes": len(document.data),
                },
            )
            return self._payload(item, [revision])

    async def _add_revision(
        self,
        access: AuthContext,
        item_id: UUID,
        *,
        document: _ProducedDocument,
        summary: str,
        conversation_id: UUID | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        user_id = require_user_identity(access)
        async with transaction_scope(self._sessions) as session:
            item = await session.get(Item, item_id, with_for_update=True)
            if item is None or item.status == "deleted" or item.deleted_at is not None:
                raise DocumentNotFoundError(f"artifact not found: {item_id}")
            previous = await self._revisions(session, item.id)
            number = previous[-1].revision_number + 1
            key = _revision_key(item.tenant_id, item.id, number, document.file_name)
            await self._store_revision_objects(document, key)
            revision = ArtifactRevision(
                item_id=item.id,
                revision_number=number,
                storage_key=key,
                mime_type=document.mime_type,
                size_bytes=len(document.data),
                summary=summary,
                conversation_id=conversation_id,
                request_id=request_id,
                created_by_user_id=user_id,
            )
            session.add(revision)
            item.storage_key = key
            item.size_bytes = len(document.data)
            artifact_metadata = dict(item.metadata_.get("artifact") or {})
            artifact_metadata["current_revision"] = number
            item.metadata_ = {**dict(item.metadata_), "artifact": artifact_metadata}
            await session.flush()
            await AuditService(session).record(
                access,
                action="artifact.revised",
                resource_type="artifact",
                resource_id=str(item.id),
                details={
                    "revision": number,
                    "conversation_id": str(conversation_id) if conversation_id else None,
                    "size_bytes": len(document.data),
                },
            )
            return self._payload(item, [*previous, revision])

    async def _store_revision_objects(
        self, document: _ProducedDocument, key: str
    ) -> None:
        """Write one revision's bytes to durable object storage."""

        await asyncio.to_thread(
            self._object_storage().put_bytes,
            document.data,
            key,
            content_type=document.mime_type,
        )

    async def _load(
        self,
        access: AuthContext,
        artifact_id: UUID,
        *,
        permission: str = COLLECTION_READ_PERMISSION,
    ) -> tuple[Item, ArtifactRevision]:
        async with transaction_scope(self._sessions) as session:
            item = await self._authorized_item(
                session, access, artifact_id, permission=permission
            )
            revisions = await self._revisions(session, item.id)
            return item, revisions[-1]

    async def _authorized_item(
        self,
        session: AsyncSession,
        access: AuthContext,
        artifact_id: UUID,
        *,
        permission: str = COLLECTION_READ_PERMISSION,
    ) -> Item:
        item = await AuthorizationService(session).require_item(
            artifact_id, access=access, permission=permission
        )
        if item.item_type != "document" or not isinstance(
            item.metadata_.get("artifact"), Mapping
        ):
            raise DocumentNotFoundError(f"artifact not found: {artifact_id}")
        return item

    @staticmethod
    async def _revisions(session: AsyncSession, item_id: UUID) -> list[ArtifactRevision]:
        revisions = list(
            await session.scalars(
                select(ArtifactRevision)
                .where(
                    ArtifactRevision.item_id == item_id,
                    ArtifactRevision.deleted_at.is_(None),
                )
                .order_by(ArtifactRevision.revision_number)
            )
        )
        if not revisions:
            raise DocumentNotFoundError(f"artifact not found: {item_id}")
        return revisions

    async def _bytes(self, storage_key: str) -> bytes:
        return await self._object_storage().read(
            storage_key, max_bytes=self._max_content_bytes
        )

    async def _text(self, storage_key: str, limit: int) -> tuple[str, bool]:
        """Up to ``limit`` characters of a revision, marked when cut short."""

        text = (await self._bytes(storage_key)).decode("utf-8", errors="replace")
        if len(text) <= limit:
            return text, False
        return f"{text[:limit]}{_TRUNCATION_MARKER}", True

    async def _model_text(
        self, revision: ArtifactRevision, limit: int
    ) -> tuple[str, bool]:
        """The revision's text as previews should see it.

        A text revision is its own text. A binary revision is named, not
        decoded: its bytes are reached through the download URL, and the model
        reads it in the workspace rather than here.
        """

        if not revision.mime_type.startswith("text/"):
            return f"(binary document: {revision.mime_type}; no text preview)", False
        try:
            return await self._text(revision.storage_key, limit)
        except ObjectNotFoundError:
            return "(document content is unavailable)", False

    def _validate_content(self, content: str) -> None:
        if not content.strip():
            raise ArtifactValidationError("document content must not be empty")
        if len(content.encode("utf-8")) > self._max_content_bytes:
            raise ArtifactValidationError(
                f"document content exceeds the {self._max_content_bytes} byte limit"
            )

    def _payload(self, item: Item, revisions: Sequence[ArtifactRevision]) -> dict[str, Any]:
        current = revisions[-1]
        artifact_metadata = item.metadata_.get("artifact")
        if not isinstance(artifact_metadata, Mapping):
            artifact_metadata = {}
        return {
            "id": str(item.id),
            "title": item.title,
            "file_name": _stored_file_name(item),
            "mime_type": current.mime_type,
            "size_bytes": current.size_bytes,
            "revision": current.revision_number,
            "revision_count": len(revisions),
            "conversation_id": artifact_metadata.get("conversation_id"),
            "source_document_id": artifact_metadata.get("source_document_id"),
            "created_at": timestamp(item.created_at),
            "updated_at": timestamp(current.created_at) or timestamp(item.updated_at),
            "download_url": self._presigned(current.storage_key),
            "revisions": [
                {
                    "revision": revision.revision_number,
                    "summary": revision.summary,
                    "size_bytes": revision.size_bytes,
                    "created_at": timestamp(revision.created_at),
                    "download_url": self._presigned(revision.storage_key),
                }
                for revision in revisions
            ],
        }

    def _presigned(self, storage_key: str) -> str | None:
        if not storage_key:
            return None
        try:
            return self._object_storage().presign_download(
                storage_key, expires_seconds=self._download_url_seconds
            ).url
        except Exception:
            log.exception("could not presign artifact download")
            return None


@dataclass(frozen=True, slots=True)
class _ProducedDocument:
    """One file to store as a revision, with the name and type it keeps."""

    file_name: str
    mime_type: str
    data: bytes


@dataclass(frozen=True, slots=True)
class WorkspaceSource:
    """One stored document, ready to be written into an execution workspace."""

    document_id: str
    title: str
    file_name: str
    mime_type: str
    data: bytes

    @property
    def size_bytes(self) -> int:
        return len(self.data)


def _output_name(value: str, *, mime_type: str | None = None) -> str:
    """A safe, bare file name that keeps the extension the format is keyed on.

    Path separators, traversal and control characters are stripped rather than
    rejected: the name arrives from a model-driven workspace, so it is data to
    be made safe, not input to be trusted.
    """

    name = Path(value.strip()).name if value.strip() else ""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")[:120]
    if not Path(name).suffix:
        extension = next(
            (
                suffix
                for suffix, candidate in _MIME_TYPES.items()
                if candidate == (mime_type or "").split(";", 1)[0].strip().casefold()
            ),
            "",
        )
        name = f"{name or _DEFAULT_OUTPUT_NAME}{extension}"
    return name or _DEFAULT_OUTPUT_NAME


def _mime_type(value: str | None, file_name: str) -> str:
    """The content type to store a produced file under.

    The workspace's own reported type wins; when it is missing or generic, the
    file extension decides, because that is what the browser and every later
    reader key on.
    """

    reported = (value or "").split(";", 1)[0].strip().casefold()
    if reported and reported != _DEFAULT_MIME_TYPE:
        return reported
    return _MIME_TYPES.get(Path(file_name).suffix.casefold(), _DEFAULT_MIME_TYPE)


def _document_type(mime_type: str) -> str:
    if mime_type == _PDF_CONTENT_TYPE:
        return "pdf"
    if mime_type == ARTIFACT_MIME_TYPE:
        return ARTIFACT_DOCUMENT_TYPE
    return "file"


class _BytesStream:
    """Present in-memory bytes through the upload service's stream contract."""

    def __init__(self, data: bytes) -> None:
        self._data = data
        self._offset = 0

    async def read(self, size: int = -1) -> bytes:
        if size is None or size < 0:
            chunk = self._data[self._offset :]
        else:
            chunk = self._data[self._offset : self._offset + size]
        self._offset += len(chunk)
        return chunk


def _revision_key(tenant_id: UUID, item_id: UUID, revision: int, file_name: str) -> str:
    return f"tenants/{tenant_id}/items/{item_id}/revisions/{revision}/{file_name}"


def _title(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ArtifactValidationError("document title must not be blank")
    if len(normalized) > _MAX_TITLE_LENGTH:
        raise ArtifactValidationError(
            f"document title must be at most {_MAX_TITLE_LENGTH} characters"
        )
    return normalized


def _summary(value: str) -> str:
    normalized = " ".join(value.split())
    if not normalized:
        raise ArtifactValidationError("revision summary must not be blank")
    return normalized[:500]


def _file_name(title: str, *, suffix: str = ".md") -> str:
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", title).strip("-._")[:120] or "document"
    return f"{stem}{suffix}"


def _stored_file_name(item: Item) -> str:
    value = item.metadata_.get("file_name")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return _file_name(item.title)


def produced_artifact_ids(annotations: Sequence[Mapping[str, Any]]) -> tuple[UUID, ...]:
    """Extract the artifact identities an answer's annotations carry."""

    result: list[UUID] = []
    seen: set[UUID] = set()
    for annotation in annotations:
        artifact = annotation.get("artifact")
        if not isinstance(artifact, Mapping):
            continue
        try:
            artifact_id = UUID(str(artifact.get("id")))
        except (TypeError, ValueError, AttributeError):
            continue
        if artifact_id not in seen:
            result.append(artifact_id)
            seen.add(artifact_id)
    return tuple(result)


__all__ = ["ArtifactService", "WorkspaceSource", "produced_artifact_ids"]
