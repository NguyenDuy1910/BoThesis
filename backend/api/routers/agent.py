"""Chat routes: stream one grounded turn and list selectable Collections."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from api.deps import Caller, Chat, ChatCaller, Documents
from api.routers import ChatRequest

router = APIRouter(prefix="/agent", tags=["agent"])

_STREAM_HEADERS = {
    "Cache-Control": "no-cache, no-transform",
    "X-Accel-Buffering": "no",
}


@router.post("/chat")
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
        knowledge_mode=body.knowledge_mode,
        collection_item_ids=body.collection_item_ids,
        is_disconnected=request.is_disconnected,
    )
    return StreamingResponse(
        (f"data: {event}\n\n" async for event in events),
        media_type="text/event-stream",
        headers=_STREAM_HEADERS,
    )


@router.get("/collections")
async def list_chat_collections(
    caller: Caller, documents: Documents
) -> dict[str, Any]:
    return await documents.list_collections(caller)
