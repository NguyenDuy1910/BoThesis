"""Minimal durable conversation/message boundary used by streaming chat."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from bothesis.db.models import Conversation, Message
from bothesis.services import AuthContext, DocumentNotFoundError
from bothesis.services.item import ItemService


class ConversationService:
    """Persist current turns without coupling storage to the agent loop."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        self._session_factory = session_factory

    async def start_turn(
        self,
        conversation_id: UUID,
        *,
        access: AuthContext,
        content: str,
        document_ids: Sequence[UUID],
        request_id: str,
    ) -> Message:
        normalized_content = content.strip()
        if not normalized_content:
            raise ValueError("message content must not be blank")
        if access.tenant_id is None:
            raise DocumentNotFoundError(f"conversation not found: {conversation_id}")
        async with self._session_factory.begin() as session:
            now = datetime.now(UTC)
            await session.execute(
                insert(Conversation)
                .values(
                    id=conversation_id,
                    tenant_id=access.tenant_id,
                    user_id=access.user_id,
                    title=_title(normalized_content),
                    last_message_at=now,
                )
                .on_conflict_do_nothing(index_elements=[Conversation.id])
            )
            conversation = await session.scalar(
                select(Conversation)
                .where(Conversation.id == conversation_id)
                .with_for_update()
            )
            if conversation is None or (
                conversation.user_id != access.user_id
                or conversation.tenant_id != access.tenant_id
                or conversation.status != "active"
            ):
                raise DocumentNotFoundError(
                    f"conversation not found: {conversation_id}"
                )

            sequence = await _next_sequence(session, conversation.id)
            message = Message(
                conversation_id=conversation.id,
                role="user",
                content=normalized_content,
                metadata_={"request_id": request_id},
                sequence_number=sequence,
            )
            session.add(message)
            conversation.last_message_at = now
            await session.flush()
            items = ItemService(session)
            for position, document_id in enumerate(document_ids):
                await items.link_message(
                    message.id,
                    document_id,
                    "attachment",
                    access=access,
                    position=position,
                )
            return message

    async def finish_turn(
        self,
        conversation_id: UUID,
        *,
        access: AuthContext,
        content: str,
        referenced_document_ids: Iterable[UUID],
        request_id: str,
    ) -> Message | None:
        normalized_content = content.strip()
        if not normalized_content:
            return None
        if access.tenant_id is None:
            raise DocumentNotFoundError(f"conversation not found: {conversation_id}")
        unique_references = list(dict.fromkeys(referenced_document_ids))
        async with self._session_factory.begin() as session:
            conversation = await session.scalar(
                select(Conversation)
                .where(
                    Conversation.id == conversation_id,
                    Conversation.tenant_id == access.tenant_id,
                    Conversation.user_id == access.user_id,
                    Conversation.status == "active",
                )
                .with_for_update()
            )
            if conversation is None:
                raise DocumentNotFoundError(
                    f"conversation not found: {conversation_id}"
                )
            sequence = await _next_sequence(session, conversation.id)
            message = Message(
                conversation_id=conversation.id,
                role="assistant",
                content=normalized_content,
                metadata_={"request_id": request_id},
                sequence_number=sequence,
            )
            session.add(message)
            conversation.last_message_at = datetime.now(UTC)
            await session.flush()
            items = ItemService(session)
            for position, document_id in enumerate(unique_references):
                await items.link_message(
                    message.id,
                    document_id,
                    "reference",
                    access=access,
                    position=position,
                )
            return message


async def _next_sequence(session: AsyncSession, conversation_id: UUID) -> int:
    current = await session.scalar(
        select(func.max(Message.sequence_number)).where(
            Message.conversation_id == conversation_id
        )
    )
    return int(current or 0) + 1


def _title(content: str) -> str:
    normalized = " ".join(content.split())
    return normalized[:120]


__all__ = ["ConversationService"]
