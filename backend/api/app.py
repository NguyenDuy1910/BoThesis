"""BoThesis HTTP application: assemble routers, errors, and the runtime."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api.deps import get_runtime
from api.errors import register_error_handlers
from api.routers import admin, agent, documents, health, knowledge
from api.routers.planned import PLANNED_ROUTERS

API_PREFIX = "/api/v1"

_ROUTERS = (
    agent.router,
    knowledge.router,
    documents.collections_router,
    documents.router,
    admin.router,
    *PLANNED_ROUTERS,
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
        title="BoThesis API",
        version="0.1.0",
        description="Enterprise knowledge and BI assistant.",
        lifespan=lifespan,
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
    for router in _ROUTERS:
        app.include_router(router, prefix=API_PREFIX)
    app.include_router(health.router)
    return app


app = create_app()

__all__ = ["API_PREFIX", "app", "create_app", "lifespan"]
