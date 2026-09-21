"""Enterprise Agent HTTP application: assemble routers, errors, and the runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import get_runtime
from api.errors import register_error_handlers
from api.authentication import JwtAuthenticationMiddleware
from api.routers import (
    agent,
    auth,
    artifacts,
    canonical,
    documents,
    health,
)

API_PREFIX = "/api/v1"


def _operation_id(route) -> str:
    """Use contract operation names instead of FastAPI's path-derived IDs."""
    name = route.name.removesuffix("_contract")
    if name == "health":
        return "getHealth"
    parts = name.split("_")
    return parts[0] + "".join(part.title() for part in parts[1:])

_ROUTERS = (
    agent.router,
    canonical.router,
    documents.collections_router,
    documents.router,
    artifacts.router,
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
    return app


app = create_app()

__all__ = ["API_PREFIX", "app", "create_app", "lifespan"]
