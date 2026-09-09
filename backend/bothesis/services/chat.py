"""Run one grounded chat turn under the caller's Collection permissions."""

from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable, Mapping, Sequence
from typing import Literal
from uuid import UUID, uuid4

from bothesis.agent import (
    Agent,
    AttachmentInput,
    AttachmentRef,
    ImageInput,
    ResourceResolver,
    TextInput,
    UserTurn,
)
from bothesis.agent.models import AgentContext, ConversationMessage
from bothesis.agent.protocol import Response, ResponseCompletedEvent
from bothesis.db.engine import SessionFactory, session_scope
from bothesis.services import (
    KNOWLEDGE_READ_PERMISSION,
    AuthContext,
    require_tenant_permission,
)
from bothesis.services.collection_access import CollectionAccessService
from bothesis.services.conversation import ConversationService

HistoryTurn = tuple[Literal["user", "assistant"], str]
_RESOURCE_TOOL_NAMES = frozenset(
    {"inspect_resource", "read_resource", "materialize_resource"}
)


class ChatService:
    """Authorize a chat turn, stream the agent, and persist the exchange."""

    def __init__(
        self,
        session_factory: SessionFactory,
        *,
        agent: Agent,
        conversations: ConversationService,
        resource_resolver: Callable[[AuthContext], ResourceResolver] | None = None,
    ) -> None:
        self._sessions = session_factory
        self._agent = agent
        self._conversations = conversations
        self._resource_resolver = resource_resolver

    async def stream_turn(
        self,
        access: AuthContext,
        *,
        message: str,
        conversation_id: UUID | None,
        history: Sequence[HistoryTurn],
        collection_item_ids: Sequence[UUID],
        attachment_ids: Sequence[UUID] = (),
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[str]:
        """Yield serialized agent events for one authorized chat turn."""

        require_tenant_permission(access, KNOWLEDGE_READ_PERMISSION)
        if access.tenant_id is None:
            raise PermissionError("an active tenant membership is required for chat")
        selected_ids = await self._resolve_knowledge_scope(access, collection_item_ids)
        resolved_conversation_id = conversation_id or uuid4()
        referenced_resources = (
            await self._conversations.referenced_resources(
                resolved_conversation_id, access=access
            )
            if conversation_id is not None
            else ()
        )
        attachments = tuple(dict.fromkeys(attachment_ids))
        attachment_resources = await self._conversations.resources(
            attachments, access=access
        )
        context = AgentContext(
            user_id=str(access.user_id),
            tenant_id=str(access.tenant_id),
            roles=[access.role_code] if access.role_code else [],
            collection_item_ids=tuple(str(value) for value in selected_ids),
            conversation_id=str(resolved_conversation_id),
            request_id=uuid4().hex,
            history=tuple(
                ConversationMessage(role=role, content=content)
                for role, content in history
            ),
            allowed_tool_names=self._available_tool_names(
                resources_available=bool(attachment_resources or referenced_resources)
            ),
            resources=referenced_resources,
        )
        user_turn = UserTurn(
            inputs=(
                TextInput(text=message),
                *(
                    ImageInput(resource=resource)
                    if resource.is_image
                    else AttachmentInput(attachment=AttachmentRef(resource=resource))
                    for resource in attachment_resources
                ),
            )
        )
        await self._conversations.start_turn(
            resolved_conversation_id,
            access=access,
            content=message,
            attachment_ids=attachments,
            request_id=context.request_id or "",
        )
        return self._event_stream(
            user_turn,
            context,
            access=access,
            conversation_id=resolved_conversation_id,
            resource_resolver=(
                self._resource_resolver(access)
                if self._resource_resolver is not None
                and (attachment_resources or referenced_resources)
                else None
            ),
            is_disconnected=is_disconnected,
        )

    async def _event_stream(
        self,
        user_turn: UserTurn,
        context: AgentContext,
        *,
        access: AuthContext,
        conversation_id: UUID,
        resource_resolver: ResourceResolver | None,
        is_disconnected: Callable[[], Awaitable[bool]],
    ) -> AsyncIterator[str]:
        stream = self._agent.run(
            user_turn,
            context,
            resource_resolver=resource_resolver,
        )
        final_answer: str | None = None
        referenced_document_ids: tuple[UUID, ...] = ()
        try:
            async for event in stream:
                if await is_disconnected():
                    break
                if isinstance(event, ResponseCompletedEvent):
                    answer = event.response.final_answer_text.strip()
                    if answer:
                        final_answer = answer
                        referenced_document_ids = referenced_item_ids(event.response)
                yield event.model_dump_json()
        finally:
            await stream.aclose()
        if final_answer:
            await self._conversations.finish_turn(
                conversation_id,
                access=access,
                content=final_answer,
                referenced_document_ids=referenced_document_ids,
                request_id=context.request_id or "",
            )

    async def _resolve_knowledge_scope(
        self,
        access: AuthContext,
        collection_item_ids: Sequence[UUID],
    ) -> tuple[UUID, ...]:
        """Bind the turn to Collections the caller may actually read."""

        async with session_scope(self._sessions) as session:
            allowed_ids = await CollectionAccessService(session).allowed_collection_ids(
                access
            )
        if not collection_item_ids:
            return allowed_ids
        if not set(collection_item_ids).issubset(set(allowed_ids)):
            raise PermissionError("one or more selected Collections are unavailable")
        return tuple(dict.fromkeys(collection_item_ids))

    def _available_tool_names(
        self, *, resources_available: bool = True
    ) -> tuple[str, ...]:
        """Expose the runtime's registered chat tools for this turn."""

        return tuple(
            name
            for name, _ in self._agent.tools.executors()
            if resources_available or name not in _RESOURCE_TOOL_NAMES
        )


def referenced_item_ids(response: Response) -> tuple[UUID, ...]:
    """Extract durable Item identities from the answer's citations only."""

    result: list[UUID] = []
    seen: set[UUID] = set()
    for annotation in response.output_annotations:
        citation = annotation.get("citation")
        if not isinstance(citation, Mapping):
            continue
        try:
            item_id = UUID(str(citation.get("item_id")))
        except (TypeError, ValueError, AttributeError):
            continue
        if item_id not in seen:
            result.append(item_id)
            seen.add(item_id)
    return tuple(result)


__all__ = [
    "ChatService",
    "HistoryTurn",
    "referenced_item_ids",
]
