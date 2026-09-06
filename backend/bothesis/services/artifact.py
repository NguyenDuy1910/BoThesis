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

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from bothesis.agent.models import AgentContext, ConversationArtifact
from bothesis.db.engine import SessionFactory
from bothesis.db.models import ArtifactRevision, Item
from bothesis.sandbox import (
    SandboxExecutor,
    SandboxFile,
    SandboxRequest,
    SandboxResult,
)
from bothesis.services import (
    ARTIFACT_COLLECTION_KIND,
    ARTIFACT_COLLECTION_TITLE,
    ARTIFACT_DOCUMENT_TYPE,
    ARTIFACT_EXPORT_FORMATS,
    ARTIFACT_MIME_TYPE,
    KNOWLEDGE_READ_PERMISSION,
    ArtifactValidationError,
    AuthContext,
    DocumentNotFoundError,
    require_tenant_permission,
    timestamp,
)
from bothesis.services.audit import AuditService
from bothesis.services.collection_access import CollectionAccessService
from bothesis.services.document_upload import DocumentUploadService
from bothesis.services.identity_store import resolve_agent_access
from bothesis.services.item import ItemService
from bothesis.storage import DocumentStorage, ObjectNotFoundError

log = logging.getLogger(__name__)

_MAX_TITLE_LENGTH = 200
_MAX_SOURCE_DOCUMENT_BYTES = 20 * 1024 * 1024
_PDF_CONTENT_TYPE = "application/pdf"
_TRUNCATION_MARKER = "\n…[content truncated]…\n"
# The model-facing description of a binary revision (for example a fillable
# PDF's field list) lives beside the revision object under this suffix, so no
# schema change is needed and the pair can never drift apart.
_CONTEXT_SUFFIX = ".context.md"
_CONTEXT_CONTENT_TYPE = "text/markdown"


class ArtifactService:
    """Own artifact Items, their immutable revisions, exports, and publishing.

    An artifact is a canonical ``Item`` under the caller's private artifact
    Collection, so tenant scoping, ownership, message lineage, and tombstones
    are the ordinary Item rules. Every content change is a new
    :class:`ArtifactRevision` with its own object; the Item's ``storage_key``
    always points at the current revision. File operations never run on this
    host: they are handed to the :class:`SandboxExecutor` and only their
    output is persisted.
    """

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        object_storage: Callable[[], DocumentStorage],
        sandbox: SandboxExecutor,
        uploads: Callable[[], DocumentUploadService],
        max_content_bytes: int,
        download_url_seconds: int,
    ) -> None:
        if min(max_content_bytes, download_url_seconds) < 1:
            raise ValueError("artifact limits must be greater than zero")
        self._sessions = session_factory
        self._object_storage = object_storage
        self._sandbox = sandbox
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
        async with self._sessions() as session:
            items = list(
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
            revisions = {
                item.id: await self._revisions(session, item.id) for item in items
            }
        references: list[ConversationArtifact] = []
        for item in items:
            current = revisions[item.id][-1]
            text, truncated = await self._model_text(current, content_characters)
            reference = ConversationArtifact.from_payload(
                self._payload(item, revisions[item.id])
            )
            references.append(
                replace(reference, content=text, content_truncated=truncated)
            )
        return tuple(references)

    # -- Lifecycle ----------------------------------------------------------

    async def create_from_content(
        self,
        access: AuthContext,
        *,
        title: str,
        content: str,
        conversation_id: UUID | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        """Write a new document from model-authored Markdown."""

        tenant_id = require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        normalized_title = _title(title)
        file_name = _file_name(normalized_title)
        self._validate_content(content)
        produced = await self._sandbox.run(
            SandboxRequest("write", {"file_name": file_name, "content": content})
        )
        document = _produced_document(produced, default_name=file_name)
        return await self._create(
            access,
            tenant_id,
            title=normalized_title,
            document=document,
            summary="Created from the conversation",
            conversation_id=conversation_id,
            request_id=request_id,
            source_document_id=None,
        )

    async def create_from_document(
        self,
        access: AuthContext,
        *,
        title: str | None,
        source_document_id: UUID,
        conversation_id: UUID | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        """Start a new, editable artifact as a copy of an indexed source document.

        Any document Item the caller can read is a valid source — a template
        or form is just an ordinary document with useful metadata, not a
        separate kind of thing. The source is never modified; a Collection
        access check at read time is the only authorization this needs.
        """

        tenant_id = require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with self._sessions() as session:
            source = await CollectionAccessService(session).require_item_access(
                source_document_id, access=access
            )
            if source.item_type != "document" or not source.storage_key:
                raise ArtifactValidationError("source is not an available document")
            source_title = source.title
            source_key = source.storage_key
            source_name = _input_name(
                str(source.metadata_.get("file_name") or source.title),
                mime_type=source.mime_type,
            )
        source_bytes = await self._object_storage().read(
            source_key, max_bytes=_MAX_SOURCE_DOCUMENT_BYTES
        )
        normalized_title = _title(title or source_title)
        file_name = _file_name(normalized_title)
        # The sandbox decides the import strategy from the document itself
        # (keep a fillable PDF intact, extract everything else to Markdown)
        # and reports what it produced; the host never inspects file formats.
        produced = await self._sandbox.run(
            SandboxRequest(
                "import",
                {"file_name": source_name, "target_file_name": file_name},
                files=(SandboxFile(source_name, source_bytes),),
            )
        )
        document = _produced_document(produced, default_name=file_name)
        payload = await self._create(
            access,
            tenant_id,
            title=normalized_title,
            document=document,
            summary=f"Created from “{source_title}”",
            conversation_id=conversation_id,
            request_id=request_id,
            source_document_id=source_document_id,
        )
        # The source document's text is new to the model; it needs it to fill
        # the document in. Content the model wrote itself is not echoed back.
        return {**payload, "content": document.model_text()}

    async def edit(
        self,
        access: AuthContext,
        artifact_id: UUID,
        *,
        summary: str,
        edits: Sequence[Mapping[str, str]] = (),
        content: str | None = None,
        fields: Mapping[str, str] | None = None,
        conversation_id: UUID | None,
        request_id: str | None,
    ) -> dict[str, Any]:
        """Apply one change as a new revision.

        A text document takes targeted find/replace ``edits`` or a full
        rewrite ``content``. A fillable PDF takes ``fields`` — its form fields
        are set in place and the original layout is preserved.
        """

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        if sum((bool(edits), content is not None, fields is not None)) != 1:
            raise ArtifactValidationError(
                "provide exactly one of edits (find/replace pairs), content "
                "(a complete rewrite), or fields (form values for a fillable PDF)"
            )
        normalized_summary = _summary(summary)
        item, current = await self._load(access, artifact_id, minimum_role="editor")
        file_name = _stored_file_name(item)
        if current.mime_type == _PDF_CONTENT_TYPE:
            if fields is None:
                raise ArtifactValidationError(
                    "this document is a fillable PDF; change it with fields "
                    "(form field names mapped to values), not text edits"
                )
            if not fields:
                raise ArtifactValidationError("fields must not be empty")
            request = SandboxRequest(
                "fill_pdf",
                {"file_name": file_name, "fields": dict(fields)},
                files=(SandboxFile(file_name, await self._bytes(current.storage_key)),),
            )
        elif fields is not None:
            raise ArtifactValidationError(
                "fields applies only to fillable PDF documents; use edits or content"
            )
        elif content is not None:
            self._validate_content(content)
            request = SandboxRequest(
                "write", {"file_name": file_name, "content": content}
            )
        else:
            request = SandboxRequest(
                "replace",
                {
                    "file_name": file_name,
                    "edits": [
                        {"find": str(edit["find"]), "replace": str(edit["replace"])}
                        for edit in edits
                    ],
                },
                files=(SandboxFile(file_name, await self._bytes(current.storage_key)),),
            )
        produced = await self._sandbox.run(request)
        document = _produced_document(produced, default_name=file_name)
        payload = await self._add_revision(
            access,
            item.id,
            document=document,
            summary=normalized_summary,
            conversation_id=conversation_id,
            request_id=request_id,
        )
        return {**payload, "content": document.model_text()}

    async def export(
        self, access: AuthContext, artifact_id: UUID, *, format: str = "pdf"
    ) -> dict[str, Any]:
        """Render the current revision to an export format and keep it with it."""

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        normalized_format = format.strip().casefold()
        if normalized_format not in ARTIFACT_EXPORT_FORMATS:
            supported = ", ".join(sorted(ARTIFACT_EXPORT_FORMATS))
            raise ArtifactValidationError(f"export format must be one of: {supported}")
        item, current = await self._load(access, artifact_id)
        if normalized_format in current.exports:
            return await self.get(access, artifact_id)
        file_name = _stored_file_name(item)
        if current.mime_type == _PDF_CONTENT_TYPE:
            # The revision already is a PDF: the export is the revision itself.
            key = current.storage_key
            export_name = file_name
            size_bytes = current.size_bytes
        else:
            produced = await self._sandbox.run(
                SandboxRequest(
                    "export_pdf",
                    {"file_name": file_name, "title": item.title},
                    files=(
                        SandboxFile(file_name, await self._bytes(current.storage_key)),
                    ),
                )
            )
            export_name = f"{Path(file_name).stem}.pdf"
            data = produced.file(export_name)
            size_bytes = len(data)
            key = _revision_key(
                item.tenant_id, item.id, current.revision_number, export_name
            )
            await asyncio.to_thread(
                self._object_storage().put_bytes,
                data,
                key,
                content_type=_PDF_CONTENT_TYPE,
            )
        async with self._sessions.begin() as session:
            revision = await session.get(ArtifactRevision, current.id, with_for_update=True)
            if revision is None:
                raise DocumentNotFoundError(f"artifact not found: {artifact_id}")
            revision.exports = {
                **dict(revision.exports),
                normalized_format: {
                    "file_name": export_name,
                    "content_type": _PDF_CONTENT_TYPE,
                    "storage_key": key,
                    "size_bytes": size_bytes,
                },
            }
            await AuditService(session).record(
                access,
                action="artifact.exported",
                resource_type="artifact",
                resource_id=str(item.id),
                details={"revision": current.revision_number, "format": normalized_format},
            )
        return await self.get(access, artifact_id)

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

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        item, current = await self._load(access, artifact_id)
        async with self._sessions() as session:
            target = await CollectionAccessService(session).require_item_access(
                collection_id, access=access, minimum_role="editor"
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
        async with self._sessions.begin() as session:
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
        async with self._sessions() as session:
            item = await self._authorized_item(session, access, artifact_id)
            revisions = await self._revisions(session, item.id)
        return self._payload(item, revisions)

    async def content(
        self, access: AuthContext, artifact_id: UUID, *, revision: int | None = None
    ) -> dict[str, Any]:
        """Return one revision's text for in-app preview."""

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        async with self._sessions() as session:
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
        item_id = uuid4()
        key = _revision_key(tenant_id, item_id, 1, document.file_name)
        await self._store_revision_objects(document, key)
        async with self._sessions.begin() as session:
            items = ItemService(session)
            collection_id = await items.ensure_personal_collection(
                access.user_id,
                tenant_id,
                collection_id=ItemService.artifact_collection_id(tenant_id, access.user_id),
                title=ARTIFACT_COLLECTION_TITLE,
                system_kind=ARTIFACT_COLLECTION_KIND,
            )
            item = await items.create_document(
                tenant_id=tenant_id,
                parent_item_id=collection_id,
                title=title,
                document_type=_document_type(document.mime_type),
                created_by_user_id=access.user_id,
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
                created_by_user_id=access.user_id,
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
        async with self._sessions.begin() as session:
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
                created_by_user_id=access.user_id,
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
        """Write one revision's bytes and, when present, its description."""

        await asyncio.to_thread(
            self._object_storage().put_bytes,
            document.data,
            key,
            content_type=document.mime_type,
        )
        if document.context is not None:
            await asyncio.to_thread(
                self._object_storage().put_bytes,
                document.context,
                f"{key}{_CONTEXT_SUFFIX}",
                content_type=_CONTEXT_CONTENT_TYPE,
            )

    async def _load(
        self, access: AuthContext, artifact_id: UUID, *, minimum_role: str = "viewer"
    ) -> tuple[Item, ArtifactRevision]:
        async with self._sessions() as session:
            item = await self._authorized_item(
                session, access, artifact_id, minimum_role=minimum_role
            )
            revisions = await self._revisions(session, item.id)
            return item, revisions[-1]

    async def _authorized_item(
        self,
        session: AsyncSession,
        access: AuthContext,
        artifact_id: UUID,
        *,
        minimum_role: str = "viewer",
    ) -> Item:
        item = await CollectionAccessService(session).require_item_access(
            artifact_id, access=access, minimum_role=minimum_role
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
        """The revision's text as the model (and previews) should see it.

        A text revision is its own text. A binary revision (a fillable PDF)
        is represented by the description stored beside it — never by its
        bytes decoded as text.
        """

        if revision.mime_type.startswith("text/"):
            return await self._text(revision.storage_key, limit)
        try:
            return await self._text(
                f"{revision.storage_key}{_CONTEXT_SUFFIX}", limit
            )
        except ObjectNotFoundError:
            return f"(binary document: {revision.mime_type}; no text preview)", False

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
            "exports": self._exports(current),
            "revisions": [
                {
                    "revision": revision.revision_number,
                    "summary": revision.summary,
                    "size_bytes": revision.size_bytes,
                    "created_at": timestamp(revision.created_at),
                    "download_url": self._presigned(revision.storage_key),
                    "exports": self._exports(revision),
                }
                for revision in revisions
            ],
        }

    def _exports(self, revision: ArtifactRevision) -> dict[str, Any]:
        exports: dict[str, Any] = {}
        for name, export in dict(revision.exports).items():
            if not isinstance(export, Mapping):
                continue
            exports[str(name)] = {
                "file_name": str(export.get("file_name") or f"export.{name}"),
                "size_bytes": int(export.get("size_bytes") or 0),
                "download_url": self._presigned(str(export.get("storage_key") or "")),
            }
        return exports

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
    """What one sandbox operation produced, as the runner reported it.

    ``context`` is the model-facing description of a binary document (for
    example a fillable PDF's field list); it is ``None`` for text documents,
    whose data is its own description.
    """

    file_name: str
    mime_type: str
    data: bytes
    context: bytes | None

    def model_text(self) -> str:
        source = self.context if self.context is not None else self.data
        return source.decode("utf-8", errors="replace")


def _produced_document(
    produced: SandboxResult, *, default_name: str
) -> _ProducedDocument:
    """Read the runner's report of what it wrote, without trusting it blindly."""

    file_name = _safe_produced_name(produced.result.get("file_name"), default_name)
    mime_type = str(produced.result.get("content_type") or ARTIFACT_MIME_TYPE)
    context_name = produced.result.get("context_file_name")
    context = (
        produced.file(_safe_produced_name(context_name, context_name.strip()))
        if isinstance(context_name, str) and context_name.strip()
        else None
    )
    return _ProducedDocument(
        file_name=file_name,
        mime_type=mime_type,
        data=produced.file(file_name),
        context=context,
    )


def _safe_produced_name(value: object, default: str) -> str:
    """A bare file name from the runner result; anything else is the default."""

    if isinstance(value, str):
        name = value.strip()
        if name and Path(name).name == name and name not in {".", ".."}:
            return name
    return default


def _document_type(mime_type: str) -> str:
    return "pdf" if mime_type == _PDF_CONTENT_TYPE else ARTIFACT_DOCUMENT_TYPE


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


def _input_name(value: str, *, mime_type: str | None) -> str:
    """A safe sandbox input name that keeps the format the runner keys on."""

    name = Path(value.strip()).name if value.strip() else ""
    name = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.")
    if not Path(name).suffix:
        extension = {
            "text/markdown": ".md",
            "text/x-markdown": ".md",
            "text/plain": ".txt",
            "application/pdf": ".pdf",
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document": (
                ".docx"
            ),
        }.get((mime_type or "").split(";", 1)[0].strip().casefold(), "")
        name = f"{name or 'document'}{extension}"
    return name or "document"


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


__all__ = ["ArtifactService", "produced_artifact_ids"]
