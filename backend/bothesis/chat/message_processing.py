"""Persist and process one document-aware chat turn."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import replace
from uuid import UUID

from bothesis.agent.models import (
    AgentContext,
    AgentEvent,
    CitationAvailable,
    CitationEvent,
    DocumentProgress,
    FinalAnswerDelta,
    MessageDelta,
    RunCompleted,
    RunFailed,
    RunStarted,
)
from bothesis.chat.agent_loop import AgentLoop
from bothesis.services import (
    AuthContext,
    ConversationService,
    DocumentNotFoundError,
)
from bothesis.connector.document_pipeline import (
    DocumentProcessingError,
    DocumentPipeline,
    PreparedDocuments,
)

log = logging.getLogger(__name__)


class MessageProcessor:
    """Keep persistence and optional document preparation outside AgentLoop."""

    def __init__(
        self,
        agent_loop: AgentLoop,
        document_pipeline: DocumentPipeline,
        conversations: ConversationService,
    ) -> None:
        self._agent_loop = agent_loop
        self._document_pipeline = document_pipeline
        self._conversations = conversations

    async def run_stream(
        self,
        user_message: str,
        document_ids: list[UUID],
        ctx: AgentContext,
        *,
        access: AuthContext,
    ) -> AsyncIterator[AgentEvent]:
        sequence = 0

        def sequenced(event: AgentEvent) -> AgentEvent:
            nonlocal sequence
            sequence += 1
            return replace(event, sequence=sequence, event_id=f"event-{sequence}")

        yield sequenced(
            RunStarted(
                conversation_id=ctx.conversation_id,
                request_id=ctx.request_id,
            )
        )
        try:
            conversation_id = UUID(ctx.conversation_id or "")
        except ValueError:
            yield sequenced(RunFailed(error="a valid conversation ID is required"))
            return

        try:
            await self._conversations.start_turn(
                conversation_id,
                access=access,
                content=user_message,
                document_ids=document_ids,
                request_id=ctx.request_id or "",
            )
        except (DocumentNotFoundError, ValueError):
            yield sequenced(
                RunFailed(error="The conversation or one of its documents is unavailable.")
            )
            return
        except Exception:
            log.exception("user message could not be persisted")
            yield sequenced(RunFailed(error="The chat turn could not be started."))
            return

        queue: asyncio.Queue[DocumentProgress] = asyncio.Queue()
        preparation = asyncio.create_task(
            self._document_pipeline.prepare_for_message(
                document_ids,
                access=access,
                message=user_message,
                report=queue.put_nowait,
            )
        )
        try:
            async for event in _preparation_events(preparation, queue):
                yield sequenced(event)
            prepared = await preparation
        except asyncio.CancelledError:
            preparation.cancel()
            await asyncio.gather(preparation, return_exceptions=True)
            raise
        except (DocumentNotFoundError, DocumentProcessingError, ValueError) as exc:
            yield sequenced(RunFailed(error=str(exc)))
            return
        except Exception:
            log.exception("document preparation failed")
            yield sequenced(RunFailed(error="Document preparation failed."))
            return

        run_context = replace(ctx, documents=prepared.contexts)
        answer_parts: list[str] = []
        evidence_documents: dict[str, UUID] = {}
        referenced_documents: list[UUID] = []
        async for event in self._agent_loop.run_stream(user_message, run_context):
            if isinstance(event, RunStarted):
                continue
            if isinstance(event, (FinalAnswerDelta, MessageDelta)):
                answer_parts.append(event.text)
            elif isinstance(event, CitationAvailable):
                try:
                    evidence_documents[event.evidence.id] = UUID(
                        event.evidence.document_id
                    )
                except ValueError:
                    pass
            elif isinstance(event, CitationEvent):
                document_id = evidence_documents.get(event.evidence_id)
                if document_id is not None:
                    referenced_documents.append(document_id)
            elif isinstance(event, RunCompleted):
                try:
                    await self._conversations.finish_turn(
                        conversation_id,
                        access=access,
                        content="".join(answer_parts),
                        referenced_document_ids=referenced_documents,
                        request_id=ctx.request_id or "",
                    )
                except Exception:
                    log.exception("assistant message could not be persisted")
                    yield sequenced(
                        RunFailed(error="The completed response could not be persisted.")
                    )
                    return
                if event.provider_annotations:
                    try:
                        await self._document_pipeline.cache_provider_annotations(
                            prepared,
                            event.provider_annotations,
                        )
                    except Exception:
                        log.exception("provider file metadata could not be cached")
            yield sequenced(event)


async def _preparation_events(
    preparation: asyncio.Task[PreparedDocuments],
    queue: asyncio.Queue[DocumentProgress],
) -> AsyncIterator[DocumentProgress]:
    while not preparation.done() or not queue.empty():
        if not queue.empty():
            yield queue.get_nowait()
            continue
        queue_read = asyncio.create_task(queue.get())
        done, _ = await asyncio.wait(
            {preparation, queue_read},
            return_when=asyncio.FIRST_COMPLETED,
        )
        if queue_read in done:
            yield queue_read.result()
        else:
            queue_read.cancel()
            await asyncio.gather(queue_read, return_exceptions=True)


__all__ = ["MessageProcessor"]
