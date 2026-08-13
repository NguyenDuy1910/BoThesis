from __future__ import annotations

import hashlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from bothesis.agent.models import AgentContext, TextDelta, TurnDone
from bothesis.agent.tools import ToolRegistry
from bothesis.agent.transports.base import ChatMessage, LLMResponse, LLMTransport
from bothesis.chat.agent_loop import AgentLoop
from bothesis.chat.attachment_models import AttachmentMode
from bothesis.chat.attachment_repository import (
    AttachmentAccessError,
    SQLiteAttachmentRepository,
)
from bothesis.chat.attachment_service import AttachmentService
from bothesis.chat.attachment_storage import PresignedRequest, StoredObject
from bothesis.chat.message_processing import MessageProcessor


class StubStorage:
    def __init__(self) -> None:
        self.metadata: dict[str, StoredObject] = {}
        self.content: dict[str, bytes] = {}
        self.last_upload_key: str | None = None

    def presign_upload(
        self,
        key: str,
        *,
        content_type: str,
        sha256: str,
        expires_seconds: int,
    ) -> PresignedRequest:
        del sha256
        self.last_upload_key = key
        return PresignedRequest(
            url=f"https://storage.example/{key}",
            method="PUT",
            headers={"content-type": content_type},
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
        )

    def presign_download(
        self,
        key: str,
        *,
        expires_seconds: int,
    ) -> PresignedRequest:
        return PresignedRequest(
            url=f"https://storage.example/{key}?expires={expires_seconds}",
            method="GET",
            headers={},
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_seconds),
        )

    async def head(self, key: str) -> StoredObject:
        return self.metadata[key]

    async def read(self, key: str, *, max_bytes: int) -> bytes:
        value = self.content[key]
        if len(value) > max_bytes:
            raise ValueError("too large")
        return value


class StubEmbedder:
    model = "test-embedding"

    def __init__(self) -> None:
        self.document_batches: list[list[str]] = []
        self.queries: list[str] = []

    async def embed_query(self, query: str) -> list[float]:
        self.queries.append(query)
        return [1.0, 0.0]

    async def embed_documents(self, documents: list[str]) -> list[list[float]]:
        self.document_batches.append(documents)
        return [[1.0, 0.0] for _ in documents]


class DirectTransport(LLMTransport):
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    async def complete(self, *_: Any, **__: Any) -> LLMResponse:
        raise AssertionError("direct validated flow does not need a completion")

    async def stream_turn(
        self,
        messages: Any,
        **_: Any,
    ) -> Any:
        self.messages = [
            message.as_dict() if isinstance(message, ChatMessage) else dict(message)
            for message in messages
        ]
        yield TextDelta("The screenshot shows a warning.")
        yield TurnDone("stop")


def make_service(tmp_path: Path) -> tuple[AttachmentService, StubStorage, StubEmbedder]:
    storage = StubStorage()
    embedder = StubEmbedder()
    service = AttachmentService(
        repository=SQLiteAttachmentRepository(tmp_path / "attachments.sqlite3"),
        storage=storage,  # type: ignore[arg-type]
        embedder=embedder,
        preparation_timeout_seconds=2,
    )
    return service, storage, embedder


async def upload(
    service: AttachmentService,
    storage: StubStorage,
    *,
    file_name: str,
    content_type: str,
    content: bytes,
) -> Any:
    checksum = hashlib.sha256(content).hexdigest()
    started = await service.start_upload(
        tenant_id="tenant-1",
        owner_user_id="user-1",
        conversation_id="conversation-1",
        file_name=file_name,
        content_type=content_type,
        size_bytes=len(content),
        checksum=checksum,
    )
    assert started.upload_required is True
    assert started.upload_id is not None
    assert storage.last_upload_key is not None
    storage.metadata[storage.last_upload_key] = StoredObject(
        size_bytes=len(content),
        content_type=content_type,
        sha256=checksum,
    )
    storage.content[storage.last_upload_key] = content
    return await service.complete_upload(
        started.upload_id,
        tenant_id="tenant-1",
        owner_user_id="user-1",
        conversation_id="conversation-1",
    )


@pytest.mark.asyncio
async def test_upload_completion_and_tenant_checksum_deduplication(
    tmp_path: Path,
) -> None:
    service, storage, _ = make_service(tmp_path)
    content = b"Quarterly revenue was 42."
    first = await upload(
        service,
        storage,
        file_name="report.txt",
        content_type="text/plain",
        content=content,
    )

    repeated = await service.start_upload(
        tenant_id="tenant-1",
        owner_user_id="user-1",
        conversation_id="conversation-1",
        file_name="renamed-report.txt",
        content_type="text/plain",
        size_bytes=len(content),
        checksum=hashlib.sha256(content).hexdigest(),
    )

    assert first.status.value == "available"
    assert repeated.upload_required is False
    assert repeated.attachment is not None
    assert repeated.attachment.id != first.id
    assert repeated.attachment.object_key == first.object_key


@pytest.mark.asyncio
async def test_attachment_scope_is_enforced_before_preparation(tmp_path: Path) -> None:
    service, storage, _ = make_service(tmp_path)
    record = await upload(
        service,
        storage,
        file_name="report.txt",
        content_type="text/plain",
        content=b"Scoped content",
    )

    with pytest.raises(AttachmentAccessError):
        await service.prepare_for_message(
            [record.id],
            tenant_id="tenant-1",
            owner_user_id="another-user",
            conversation_id="conversation-1",
            message="Summarize this",
            report=lambda _: None,
        )


@pytest.mark.asyncio
async def test_attachments_route_independently_and_index_only_selected_text(
    tmp_path: Path,
) -> None:
    service, storage, embedder = make_service(tmp_path)
    image = await upload(
        service,
        storage,
        file_name="screen.png",
        content_type="image/png",
        content=b"not-a-real-image-but-object-storage-validated-it",
    )
    document = await upload(
        service,
        storage,
        file_name="report.txt",
        content_type="text/plain",
        content=b"Revenue increased. Risks remain in the supplier pipeline.",
    )
    progress = []

    prepared = await service.prepare_for_message(
        [image.id, document.id],
        tenant_id="tenant-1",
        owner_user_id="user-1",
        conversation_id="conversation-1",
        message="Find the exact wording about revenue",
        report=progress.append,
    )

    assert [context.mode for context in prepared.contexts] == [
        AttachmentMode.DIRECT.value,
        AttachmentMode.INDEXED.value,
    ]
    assert prepared.contexts[0].content_block is not None
    assert prepared.contexts[1].evidence
    assert embedder.queries == ["Find the exact wording about revenue"]
    assert len(embedder.document_batches) == 1
    assert {event.attachment_id for event in progress} == {image.id, document.id}
    assert all(event.status in {"preparing", "indexing", "ready"} for event in progress)

    await service.prepare_for_message(
        [document.id],
        tenant_id="tenant-1",
        owner_user_id="user-1",
        conversation_id="conversation-1",
        message="Find the exact wording about revenue",
        report=lambda _: None,
    )
    assert len(embedder.document_batches) == 1


@pytest.mark.asyncio
async def test_lazy_request_does_not_read_extract_or_embed(tmp_path: Path) -> None:
    service, storage, embedder = make_service(tmp_path)
    record = await upload(
        service,
        storage,
        file_name="later.txt",
        content_type="text/plain",
        content=b"Keep this content for another request.",
    )
    storage.content.clear()

    prepared = await service.prepare_for_message(
        [record.id],
        tenant_id="tenant-1",
        owner_user_id="user-1",
        conversation_id="conversation-1",
        message="Save for later and do not process it now",
        report=lambda _: None,
    )

    assert prepared.contexts[0].mode == AttachmentMode.LAZY.value
    assert embedder.queries == []
    assert embedder.document_batches == []


@pytest.mark.asyncio
async def test_message_processor_streams_progress_and_direct_vision_input(
    tmp_path: Path,
) -> None:
    service, storage, _ = make_service(tmp_path)
    image = await upload(
        service,
        storage,
        file_name="screen.png",
        content_type="image/png",
        content=b"image-content",
    )
    transport = DirectTransport()
    loop = AgentLoop(
        transport,
        ToolRegistry(),
        max_model_turns=1,
        max_tool_rounds=0,
        enable_interleaved=False,
    )
    processor = MessageProcessor(loop, service)

    events = [
        event
        async for event in processor.run_stream(
            "What does this show?",
            [image.id],
            AgentContext(
                user_id="user-1",
                tenant_id="tenant-1",
                roles=[],
                conversation_id="conversation-1",
                request_id="request-1",
            ),
        )
    ]

    assert [event.sequence for event in events] == list(range(1, len(events) + 1))
    assert [event.type for event in events[:3]] == [
        "run_started",
        "attachment_progress",
        "attachment_progress",
    ]
    user_content = transport.messages[-1]["content"]
    assert isinstance(user_content, list)
    assert user_content[0] == {"type": "text", "text": "What does this show?"}
    assert user_content[1]["type"] == "image_url"
