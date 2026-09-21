"""Temporal activity that indexes one durable native upload."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from temporalio import activity
from temporalio.exceptions import ApplicationError

from bothesis.document_index import ItemIndex
from bothesis.services import DocumentProcessingError, StoredFileContent
from bothesis.services.item_ingestion import ItemIngestionService
from bothesis.services.preview import KnowledgePreview
from bothesis.services.workflow import (
    NATIVE_UPLOAD_INDEXING_ACTIVITY_NAME,
    NativeUploadIndexingInput,
    NativeUploadIndexingResult,
)


class NativeUploadIndexingActivity:
    """Invoke the source-neutral Item indexing path for one native upload."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        *,
        index: ItemIndex,
        source: StoredFileContent,
        preview: KnowledgePreview | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._index = index
        self._source = source
        self._preview = preview

    @activity.defn(name=NATIVE_UPLOAD_INDEXING_ACTIVITY_NAME)
    async def index_upload(
        self, input: NativeUploadIndexingInput
    ) -> NativeUploadIndexingResult:
        try:
            document = await ItemIngestionService(
                self._session_factory,
                index=self._index,
                preview=self._preview,
            ).index_available_upload(
                UUID(input.document_id),
                owner_user_id=UUID(input.owner_user_id),
                tenant_id=UUID(input.tenant_id),
                source=self._source,
            )
        except (DocumentProcessingError, ValueError) as exc:
            # Canonicalization has already recorded the document's index state.
            # Retrying malformed input cannot make an immutable upload readable.
            raise ApplicationError(
                str(exc), type="NativeUploadIndexingError", non_retryable=True
            ) from exc
        return NativeUploadIndexingResult(
            document_id=str(document.id),
            index_status=document.index_status or "failed",
        )


__all__ = ["NativeUploadIndexingActivity"]
