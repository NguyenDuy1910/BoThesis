"""External connection resources and provider authorization callback."""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import HTMLResponse

from api.deps import Caller, ConnectionLifecycle
from api.errors import HANDLED_ERRORS, detail_for, status_for
from api.routers import (
    Connection,
    ConnectionAuthorization,
    ConnectionAuthorizationCreate,
    ConnectionCreate,
    ConnectionPage,
    ConnectionUpdate,
    ConnectionValidation,
    ProviderCatalog,
    ProviderResourcePage,
    Source,
    SourceCreate,
)
from api.routers._mapping import connection_payload, source_payload

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("/providers", response_model=ProviderCatalog)
async def list_connection_providers(
    caller: Caller, connections: ConnectionLifecycle
) -> ProviderCatalog:
    value = await connections.connector_capabilities(caller)
    return ProviderCatalog(items=value.get("items", value.get("connectors", [])))


@router.get("", response_model=ConnectionPage)
async def list_connections(
    caller: Caller,
    connections: ConnectionLifecycle,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
) -> ConnectionPage:
    value = await connections.list_connections(
        caller, page=page, page_size=page_size, search=search
    )
    return ConnectionPage(
        items=[connection_payload(item) for item in value.get("items", [])],
        page=value.get("page", page),
        page_size=value.get("page_size", page_size),
        total=value.get("total", 0),
    )


@router.post("", response_model=Connection, status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionCreate,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Connection:
    values = body.model_dump()
    if values.get("owner_type") == "workspace":
        values["owner_type"] = "tenant"
    return Connection.model_validate(
        connection_payload(await connections.create_connection(caller, values))
    )


@router.post(
    "/authorizations",
    response_model=ConnectionAuthorization,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection_authorization(
    body: ConnectionAuthorizationCreate,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> ConnectionAuthorization:
    started = connections.start_authorization(
        caller,
        connector_key=body.connector_key,
        owner_type="tenant" if body.owner_type == "workspace" else body.owner_type,
        integration_connection_id=body.connection_id,
    )
    return ConnectionAuthorization(
        authorization_url=started.authorization_url, nonce=started.nonce
    )


@router.get("/authorizations/callback", include_in_schema=False)
async def complete_connection_authorization(
    connections: ConnectionLifecycle,
    state: Annotated[str, Query(max_length=4_096)],
    code: Annotated[str | None, Query(max_length=4_096)] = None,
    error: Annotated[str | None, Query(max_length=512)] = None,
    error_description: Annotated[str | None, Query(max_length=1_024)] = None,
) -> HTMLResponse:
    nonce = ""
    try:
        completed = connections.read_authorization_state(state)
        nonce = completed.pending.nonce
        if error or not code:
            return _completion_page(
                connections.authorization_client_origin(),
                {
                    "status": "error",
                    "nonce": nonce,
                    "message": _provider_error(error, error_description),
                },
            )
        connection = await connections.complete_authorization(
            code=code, state=state
        )
        return _completion_page(
            connections.authorization_client_origin(),
            {
                "status": "connected",
                "nonce": nonce,
                "connection_id": connection["id"],
                "connector_key": connection["connector_key"],
            },
        )
    except HANDLED_ERRORS as exc:
        return _completion_page(
            connections.authorization_client_origin(),
            {
                "status": "error",
                "nonce": nonce,
                "message": detail_for(exc),
            },
            status_code=status_for(exc),
        )


@router.get("/{connection_id}", response_model=Connection)
async def get_connection(
    connection_id: UUID,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Connection:
    return Connection.model_validate(
        connection_payload(await connections.get_connection(caller, connection_id))
    )


@router.patch("/{connection_id}", response_model=Connection)
async def update_connection(
    connection_id: UUID,
    body: ConnectionUpdate,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Connection:
    changes = body.model_dump(exclude_unset=True)
    if changes.pop("status", None):
        result = await connections.disconnect_connection(caller, connection_id)
    else:
        result = await connections.update_connection(caller, connection_id, changes)
    return Connection.model_validate(connection_payload(result))


@router.delete("/{connection_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    connection_id: UUID,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Response:
    await connections.delete_connection(caller, connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{connection_id}/validate", response_model=ConnectionValidation)
async def validate_connection(
    connection_id: UUID,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> ConnectionValidation:
    return ConnectionValidation.model_validate(
        await connections.validate_connection(caller, connection_id)
    )


@router.get("/{connection_id}/resources", response_model=ProviderResourcePage)
async def list_connection_resources(
    connection_id: UUID,
    caller: Caller,
    connections: ConnectionLifecycle,
    parent_id: str | None = None,
    search: str | None = None,
) -> ProviderResourcePage:
    value = await connections.list_connection_resources(
        caller, connection_id, parent_id=parent_id, search=search
    )
    return ProviderResourcePage(items=value.get("items", value.get("resources", [])))


@router.post(
    "/{connection_id}/sources",
    tags=["sources"],
    response_model=Source,
    status_code=status.HTTP_201_CREATED,
)
async def create_connection_source(
    connection_id: UUID,
    body: SourceCreate,
    caller: Caller,
    connections: ConnectionLifecycle,
) -> Source:
    values = body.model_dump()
    values["target_item_id"] = values.pop("collection_id")
    return Source.model_validate(
        source_payload(
            await connections.create_source(caller, connection_id, values)
        )
    )


def _script_literal(value: Any) -> str:
    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _provider_error(error: str | None, description: str | None) -> str:
    if error == "access_denied":
        return "The account owner declined this authorization."
    detail = (description or "").strip() or (error or "").strip()
    if not detail:
        return "The provider did not complete the authorization."
    return f"{detail[:400]} (reported by the provider)"


def _completion_page(
    origin: str, payload: dict[str, Any], *, status_code: int = 200
) -> HTMLResponse:
    message = _script_literal({"source": "bothesis.connection", **payload})
    target = _script_literal(origin)
    return HTMLResponse(
        status_code=status_code,
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; script-src 'unsafe-inline'"
            ),
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
        content=(
            '<!doctype html><meta charset="utf-8">'
            "<title>Finishing up...</title>"
            "<p>You can close this window.</p>"
            "<script>"
            f"var message = {message}; var target = {target};"
            "if (window.opener) { window.opener.postMessage(message, target); }"
            "window.close();"
            "</script>"
        ),
    )


__all__ = ["router"]
