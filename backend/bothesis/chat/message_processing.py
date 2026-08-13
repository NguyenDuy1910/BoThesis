"""Process one user message and its conversation-scoped attachments."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace

from bothesis.agent.models import (
    AgentContext,
    AgentEvent,
    AttachmentProgress,
    RunCompleted,
    RunFailed,
    RunStarted,
)
from bothesis.chat.agent_loop import AgentLoop
from bothesis.chat.attachment_repository import AttachmentAccessError
from bothesis.chat.attachment_service import (
    AttachmentError,
    AttachmentService,
    PreparedAttachments,
)


class MessageProcessor:
    """Merge attachment preparation into the existing bounded agent stream."""

    def __init__(self, agent_loop: AgentLoop, attachments: AttachmentService) -> None:
        self._agent_loop = agent_loop
        self._attachments = attachments

    async def run_stream(
        self,
        user_message: str,
        attachment_ids: list[str],
        ctx: AgentContext,
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
        if not ctx.conversation_id:
            yield sequenced(
                RunFailed(error="conversation context is required for attachments")
            )
            return

        queue: asyncio.Queue[AttachmentProgress] = asyncio.Queue()
        preparation = asyncio.create_task(
            self._attachments.prepare_for_message(
                attachment_ids,
                tenant_id=ctx.tenant_id,
                owner_user_id=ctx.user_id,
                conversation_id=ctx.conversation_id,
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
        except (AttachmentAccessError, AttachmentError, ValueError):
            yield sequenced(
                RunFailed(
                    error="One or more attachments are unavailable for this conversation."
                )
            )
            return

        run_context = replace(
            ctx,
            attachments=prepared.contexts,
            model_extra_body=prepared.model_extra_body,
        )
        async for event in self._agent_loop.run_stream(user_message, run_context):
            if isinstance(event, RunStarted):
                continue
            if isinstance(event, RunCompleted):
                await self._finish_attachment_work(prepared, event)
            yield sequenced(event)

    async def _finish_attachment_work(
        self,
        prepared: PreparedAttachments,
        event: RunCompleted,
    ) -> None:
        if event.provider_annotations:
            await self._attachments.cache_provider_annotations(
                prepared,
                event.provider_annotations,
            )
        self._attachments.schedule_background_index(prepared)


async def _preparation_events(
    preparation: asyncio.Task[PreparedAttachments],
    queue: asyncio.Queue[AttachmentProgress],
) -> AsyncIterator[AttachmentProgress]:
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
