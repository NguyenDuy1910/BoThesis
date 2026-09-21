"""Enterprise Agent HTTP application: assemble routers, errors, and the runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import get_runtime
from api.errors import register_error_handlers
from api.authentication import JwtAuthenticationMiddleware
from api.routers import (
    agent,
    auth,
    artifacts,
    collections,
    connections,
    documents,
    governance,
    health,
    iam,
    ingestions,
    knowledge,
    platform,
    sources,
    workspaces,
)

API_PREFIX = "/api/v1"

_CONTRACT_METADATA: dict[tuple[str, str], dict[str, Any]] = {
    ("post", "/api/v1/auth/accounts"): {"x-optional-bearer": "guest-upgrade"},
    ("post", "/api/v1/auth/sessions"): {
        "x-optional-bearer": "guest-upgrade",
        "x-method-security": {"password": "public", "guest": "public", "google": "public"},
    },
    ("post", "/api/v1/agent/chat"): {"x-required-permissions": ["knowledge.read"]},
    ("get", "/api/v1/knowledge/home"): {"x-required-permissions": ["knowledge.read"]},
    ("get", "/api/v1/collections"): {"x-required-permissions": ["knowledge.collections.read"]},
    ("post", "/api/v1/collections"): {"x-required-permissions": ["knowledge.collections.create"]},
    ("get", "/api/v1/collections/{collection_id}/access"): {"x-required-permissions": ["knowledge.access.read"]},
    ("put", "/api/v1/collections/{collection_id}/access/{principal_type}/{principal_id}"): {"x-required-permissions": ["knowledge.access.manage"]},
    ("delete", "/api/v1/collections/{collection_id}/access/{principal_type}/{principal_id}"): {"x-required-permissions": ["knowledge.access.manage"]},
    ("post", "/api/v1/collections/{collection_id}/documents"): {
        "tags": ["documents"],
        "x-required-permissions": ["knowledge.documents.create"],
        "x-required-collection-role": "editor",
    },
    ("get", "/api/v1/documents"): {
        "x-required-permissions": ["knowledge.documents.read"],
        "x-required-collection-role": "viewer",
    },
    ("post", "/api/v1/documents/search"): {
        "x-required-permissions": ["knowledge.documents.search"],
        "x-required-collection-role": "viewer",
    },
    ("get", "/api/v1/documents/{document_id}"): {
        "x-required-permissions": ["knowledge.documents.read"],
        "x-required-collection-role": "viewer",
    },
    ("delete", "/api/v1/documents/{document_id}"): {
        "x-required-permissions": ["knowledge.documents.delete"],
        "x-required-collection-role": "editor",
    },
    ("put", "/api/v1/documents/{document_id}/content"): {
        "x-required-permissions": ["knowledge.documents.write"],
        "x-required-collection-role": "editor",
    },
    ("post", "/api/v1/connections"): {"x-required-permissions": ["connections.manage"]},
    ("post", "/api/v1/connections/{connection_id}/sources"): {"tags": ["sources"]},
    ("post", "/api/v1/sources/{source_id}/ingestions"): {"tags": ["ingestions"]},
    ("get", "/api/v1/sources/{source_id}/ingestions"): {"tags": ["ingestions"]},
    ("get", "/api/v1/sources/{source_id}/ingestions/{ingestion_id}"): {"tags": ["ingestions"]},
    ("patch", "/api/v1/workspaces/{workspace_id}"): {"x-required-permissions": ["iam.workspaces.manage"]},
    ("get", "/api/v1/users"): {"x-required-permissions": ["iam.users.read"]},
    ("post", "/api/v1/users"): {"x-required-permissions": ["iam.users.manage"]},
    ("get", "/api/v1/audit-logs"): {"x-required-permissions": ["audit.read"]},
    ("get", "/api/v1/platform/overview"): {"x-required-permissions": ["platform.tenant.read"]},
    ("get", "/api/v1/platform/workspaces"): {"x-required-permissions": ["platform.tenant.read"]},
    ("get", "/api/v1/platform/users"): {"x-required-permissions": ["platform.user.read"]},
    ("get", "/api/v1/platform/audit-logs"): {"x-required-permissions": ["platform.audit.read"]},
    ("get", "/api/v1/platform/health"): {"x-required-permissions": ["platform.health.read"]},
}


def _operation_id(route) -> str:
    """Use contract operation names instead of FastAPI's path-derived IDs."""
    name = route.name.removesuffix("_contract")
    if name == "health":
        return "getHealth"
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])

_ROUTERS = (
    agent.router,
    knowledge.router,
    collections.router,
    documents.collections_router,
    documents.router,
    artifacts.router,
    connections.router,
    sources.router,
    ingestions.router,
    workspaces.router,
    iam.router,
    governance.router,
    platform.router,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    """Close every client the runtime opened when the process shuts down."""

    try:
        yield
    finally:
        await get_runtime().aclose()


def create_app() -> FastAPI:
    """Build the application; one call per process, or one per test."""

    app = FastAPI(
        title="Enterprise Agent API",
        version="0.1.0",
        description="Enterprise knowledge and BI assistant.",
        lifespan=lifespan,
        generate_unique_id_function=_operation_id,
    )
    app.state.allow_insecure_development_identity = (
        get_runtime().config.identity.allow_insecure_development_identity
    )
    register_error_handlers(app)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],  # tighten per environment
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(
        JwtAuthenticationMiddleware,
        tokens=get_runtime().jwt_token_service(),
    )
    for router in _ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    app.include_router(auth.router, prefix=API_PREFIX)
    app.include_router(health.router)
    _apply_contract_security(app)
    return app


def _apply_contract_security(app: FastAPI) -> None:
    """Add contract-level bearer metadata without changing middleware behavior."""

    original_openapi = app.openapi

    def openapi() -> dict[str, Any]:
        if app.openapi_schema:
            return app.openapi_schema
        schema = original_openapi()
        schema.setdefault("components", {}).setdefault("securitySchemes", {})[
            "bearerAuth"
        ] = {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
        }
        schema["security"] = [{"bearerAuth": []}]
        paths = schema["paths"]
        for path in ("/api/v1/auth/accounts", "/api/v1/auth/sessions", "/health"):
            for operation in paths.get(path, {}).values():
                if isinstance(operation, dict) and "operationId" in operation:
                    operation["security"] = []
        paths.get("/api/v1/auth/accounts", {}).get("post", {})["x-optional-bearer"] = True
        paths.get("/api/v1/auth/sessions", {}).get("post", {})["x-optional-bearer"] = True
        for (method, path), metadata in _CONTRACT_METADATA.items():
            operation = paths.get(path, {}).get(method)
            if operation is not None:
                operation.update(metadata)
        app.openapi_schema = schema
        return schema

    app.openapi = openapi


app = create_app()

__all__ = ["API_PREFIX", "app", "create_app", "lifespan"]
