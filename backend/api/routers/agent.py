"""Canonical grounded chat resource."""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from api.deps import Chat, ChatCaller
from api.routers import ChatRequest

router = APIRouter(prefix="/agent", tags=["agent"])

_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


@router.post(
    "/chat",
    operation_id="streamAgentChat",
    response_class=StreamingResponse,
    responses={
        200: {
            "description": "Server-Sent Events chat stream",
            "content": {"text/event-stream": {"schema": {"type": "string"}}},
        }
    },
)
async def chat_stream(
    body: ChatRequest,
    caller: ChatCaller,
    chat: Chat,
    request: Request,
) -> StreamingResponse:
    events = await chat.stream_turn(
        caller,
        message=body.message,
        conversation_id=body.conversation_id,
        history=[(message.role, message.content) for message in body.history],
        collection_item_ids=body.collection_ids,
        attachment_ids=body.attachment_ids,
        is_disconnected=request.is_disconnected,
    )
    return StreamingResponse(
        (f"data: {event}\n\n" async for event in events),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )
