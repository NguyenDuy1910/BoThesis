"""FastAPI dependency providers: one runtime, one identity, ready services."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import Depends, Request

from bothesis.db.engine import session_scope
from bothesis.health import HealthService
from bothesis.runtime import AppRuntime
from bothesis.services import AuthContext
from bothesis.services.admin_console import AdminConsoleService
from bothesis.services.chat import ChatService
from bothesis.services.knowledge_query import KnowledgeQueryService
from bothesis.services.knowledge_view import KnowledgeViewService
from bothesis.services.workspace_documents import WorkspaceDocumentService

from api.identity import RequestIdentity, resolve_auth_context
from api.routers import ChatRequest


@lru_cache(maxsize=1)
def get_runtime() -> AppRuntime:
    """Return the process-wide composition root."""

    return AppRuntime()


def get_request_identity(request: Request) -> RequestIdentity:
    """Read the identity the authentication middleware placed on the request."""

    return RequestIdentity(
        auth_context=getattr(request.state, "auth_context", None),
        user_id=request.headers.get("X-Bothesis-User-Id"),
        tenant_id=request.headers.get("X-Bothesis-Tenant-Id"),
    )


async def get_auth_context(
    identity: Annotated[RequestIdentity, Depends(get_request_identity)],
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> AuthContext:
    """Resolve the trusted caller before any service sees the request."""

    async with session_scope(runtime.sessions()) as session:
        return await resolve_auth_context(
            identity,
            session,
            allow_insecure_development_identity=(
                runtime.config.identity.allow_insecure_development_identity
            ),
        )


async def get_chat_auth_context(
    body: ChatRequest,
    identity: Annotated[RequestIdentity, Depends(get_request_identity)],
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> AuthContext:
    """Resolve the caller and reject a chat body that claims another tenant."""

    async with session_scope(runtime.sessions()) as session:
        return await resolve_auth_context(
            identity,
            session,
            claimed_user_id=body.user_id,
            claimed_tenant_id=body.tenant_id,
            allow_insecure_development_identity=(
                runtime.config.identity.allow_insecure_development_identity
            ),
        )


def get_chat_service(
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> ChatService:
    return runtime.chat_service()


def get_knowledge_query_service(
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> KnowledgeQueryService:
    return runtime.knowledge_query_service()


def get_knowledge_view_service(
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> KnowledgeViewService:
    return runtime.knowledge_view_service()


def get_workspace_document_service(
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> WorkspaceDocumentService:
    return runtime.workspace_document_service()


def get_admin_console_service(
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> AdminConsoleService:
    return runtime.admin_console_service()


def get_health_service(
    runtime: Annotated[AppRuntime, Depends(get_runtime)],
) -> HealthService:
    return runtime.health_service()


Runtime = Annotated[AppRuntime, Depends(get_runtime)]
Caller = Annotated[AuthContext, Depends(get_auth_context)]
ChatCaller = Annotated[AuthContext, Depends(get_chat_auth_context)]
Chat = Annotated[ChatService, Depends(get_chat_service)]
KnowledgeQuery = Annotated[KnowledgeQueryService, Depends(get_knowledge_query_service)]
KnowledgeView = Annotated[KnowledgeViewService, Depends(get_knowledge_view_service)]
Documents = Annotated[
    WorkspaceDocumentService, Depends(get_workspace_document_service)
]
AdminConsole = Annotated[AdminConsoleService, Depends(get_admin_console_service)]
Health = Annotated[HealthService, Depends(get_health_service)]

__all__ = [
    "AdminConsole",
    "Caller",
    "Chat",
    "ChatCaller",
    "Documents",
    "Health",
    "KnowledgeQuery",
    "KnowledgeView",
    "Runtime",
    "get_auth_context",
    "get_chat_auth_context",
    "get_request_identity",
    "get_runtime",
]
