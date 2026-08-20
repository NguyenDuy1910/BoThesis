"""Thin async boundary over the official OpenAI Python SDK."""

from __future__ import annotations

import os
from collections.abc import Sequence
from os import PathLike
from typing import Any, TypeVar, cast

from openai import AsyncOpenAI, AsyncStream
from openai.pagination import AsyncCursorPage
from openai.types import CreateEmbeddingResponse, FileDeleted, FileObject, FilePurpose
from openai.types.responses import (
    ParsedResponse,
    Response,
    ResponseInputParam,
    ResponseStreamEvent,
)

TextFormat = TypeVar("TextFormat")


class OpenAITransport:
    """Expose OpenAI Responses, embeddings, and files without normalization."""

    provider = "openai"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        model: str | None = None,
        embedding_model: str | None = None,
        timeout: float = 60.0,
        client: AsyncOpenAI | None = None,
    ) -> None:
        if timeout <= 0:
            raise ValueError("timeout must be greater than zero")
        self.model = model or os.getenv("OPENAI_MODEL")
        self.embedding_model = embedding_model or os.getenv("OPENAI_EMBEDDING_MODEL")
        self._client = client or AsyncOpenAI(
            api_key=api_key or os.getenv("OPENAI_API_KEY"),
            timeout=timeout,
        )
        self._owns_client = client is None

    async def responses(
        self,
        *,
        input: str | ResponseInputParam,
        model: str | None = None,
        **params: Any,
    ) -> Response:
        """Create a normal OpenAI Response and return the SDK object unchanged."""

        selected_model = self._model(model)
        if "stream" in params:
            raise ValueError("use stream_response for streaming Responses requests")
        response = await self._client.responses.create(
            model=selected_model,
            input=input,
            **params,
        )
        return cast(Response, response)

    async def stream_response(
        self,
        *,
        input: str | ResponseInputParam,
        model: str | None = None,
        **params: Any,
    ) -> AsyncStream[ResponseStreamEvent]:
        """Create a streaming Response using the SDK's typed event stream."""

        selected_model = self._model(model)
        if "stream" in params:
            raise ValueError("stream_response controls the stream parameter")
        stream = await self._client.responses.create(
            model=selected_model,
            input=input,
            stream=True,
            **params,
        )
        return cast(AsyncStream[ResponseStreamEvent], stream)

    async def parse_response(
        self,
        *,
        input: str | ResponseInputParam,
        text_format: type[TextFormat],
        model: str | None = None,
        **params: Any,
    ) -> ParsedResponse[TextFormat]:
        """Use the SDK's native structured-output parser."""

        selected_model = self._model(model)
        if "stream" in params:
            raise ValueError("structured response parsing is non-streaming")
        return await self._client.responses.parse(
            model=selected_model,
            input=input,
            text_format=text_format,
            **params,
        )

    async def embeddings(
        self,
        *,
        input: str | Sequence[str] | Sequence[int] | Sequence[Sequence[int]],
        model: str | None = None,
        **params: Any,
    ) -> CreateEmbeddingResponse:
        """Create embeddings and return the SDK response unchanged."""

        selected_model = model or self.embedding_model
        if not selected_model:
            raise ValueError("OpenAI embedding model is required")
        return await self._client.embeddings.create(
            model=selected_model,
            input=input,
            **params,
        )

    async def upload_file(
        self,
        *,
        file: bytes | PathLike[str] | tuple[str, bytes] | tuple[str, bytes, str],
        purpose: FilePurpose,
        **params: Any,
    ) -> FileObject:
        """Upload a file through the native Files API."""

        return await self._client.files.create(
            file=file,
            purpose=purpose,
            **params,
        )

    async def retrieve_file(self, file_id: str, **params: Any) -> FileObject:
        return await self._client.files.retrieve(file_id, **params)

    async def list_files(self, **params: Any) -> AsyncCursorPage[FileObject]:
        return await self._client.files.list(**params)

    async def file_content(self, file_id: str, **params: Any) -> Any:
        """Return the SDK's binary file-content response."""

        return await self._client.files.content(file_id, **params)

    async def delete_file(self, file_id: str, **params: Any) -> FileDeleted:
        return await self._client.files.delete(file_id, **params)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.close()

    def _model(self, model: str | None) -> str:
        selected_model = model or self.model
        if not selected_model:
            raise ValueError("OpenAI model is required")
        return selected_model


__all__ = ["OpenAITransport"]
