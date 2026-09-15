"""Connection routes: authorized external accounts and their discovery."""

from __future__ import annotations

import json
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Query, Response, status
from fastapi.responses import HTMLResponse

from api.deps import Caller, Integrations
from api.errors import HANDLED_ERRORS, detail_for, status_for
from api.routers import (
    ConnectionAuthorizationCreate,
    ConnectionAuthorizationStarted,
    IngestionSourceCreate,
    IntegrationConnectionCreate,
    IntegrationConnectionUpdate,
)

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("/providers")
async def list_providers(caller: Caller, integrations: Integrations) -> dict[str, Any]:
    """What this deployment can connect, and whether each one is configured."""

    return await integrations.connector_capabilities(caller)


@router.get("")
async def list_connections(
    caller: Caller,
    integrations: Integrations,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    search: str | None = None,
    connector_key: str | None = None,
    owner_type: str | None = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    return await integrations.list_connections(
        caller,
        page=page,
        page_size=page_size,
        search=search,
        connector_key=connector_key,
        owner_type=owner_type,
        status=status_filter,
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: IntegrationConnectionCreate,
    caller: Caller,
    integrations: Integrations,
) -> dict[str, Any]:
    return await integrations.create_connection(caller, body.model_dump())


@router.post("/authorizations", status_code=status.HTTP_201_CREATED)
async def start_authorization(
    body: ConnectionAuthorizationCreate,
    caller: Caller,
    integrations: Integrations,
) -> ConnectionAuthorizationStarted:
    """Return where to send the browser for consent.

    Nothing is written yet: a Connection exists only once the provider hands
    back a grant, so an abandoned consent screen leaves no record behind.
    """

    started = integrations.start_authorization(
        caller,
        connector_key=body.connector_key,
        owner_type=body.owner_type,
        integration_connection_id=body.integration_connection_id,
    )
    return ConnectionAuthorizationStarted(
        authorization_url=started.authorization_url, nonce=started.nonce
    )


@router.get("/authorizations/callback", include_in_schema=False)
async def complete_authorization(
    integrations: Integrations,
    state: Annotated[str, Query(max_length=4_096)],
    code: Annotated[str | None, Query(max_length=4_096)] = None,
    error: Annotated[str | None, Query(max_length=512)] = None,
    error_description: Annotated[str | None, Query(max_length=1_024)] = None,
) -> HTMLResponse:
    """Receive the provider's redirect and hand the result back to the opener.

    This route is deliberately unauthenticated: the browser arrives straight
    from the provider with no BoThesis token. The signed ``state`` is what
    identifies the person who began the flow, and it is the only thing trusted
    here. Nothing about the grant reaches the page — the opener is told a
    connection id and nothing more.
    """

    nonce = ""
    try:
        completed = integrations.read_authorization_state(state)
        nonce = completed.pending.nonce
        if error or not code:
            return _completion_page(
                integrations.authorization_client_origin(),
                {
                    "status": "error",
                    "nonce": nonce,
                    "message": _provider_error(error, error_description),
                },
            )
        connection = await integrations.complete_authorization(code=code, state=state)
        return _completion_page(
            integrations.authorization_client_origin(),
            {
                "status": "connected",
                "nonce": nonce,
                "connection_id": connection["id"],
                "connector_key": connection["connector_key"],
            },
        )
    except HANDLED_ERRORS as exc:
        return _completion_page(
            integrations.authorization_client_origin(),
            {"status": "error", "nonce": nonce, "message": detail_for(exc)},
            status_code=status_for(exc),
        )


@router.get("/{integration_connection_id}")
async def get_connection(
    integration_connection_id: UUID,
    caller: Caller,
    integrations: Integrations,
) -> dict[str, Any]:
    return await integrations.get_connection(caller, integration_connection_id)


@router.patch("/{integration_connection_id}")
async def update_connection(
    integration_connection_id: UUID,
    body: IntegrationConnectionUpdate,
    caller: Caller,
    integrations: Integrations,
) -> dict[str, Any]:
    """Rename or reconfigure a connection, or disconnect the account.

    Disconnecting is a state of the connection rather than an action on it: the
    record and its sources survive so that reconnecting resumes them.
    """

    changes = body.model_dump(exclude_unset=True)
    if changes.pop("status", None) is not None:
        return await integrations.disconnect_connection(
            caller, integration_connection_id
        )
    return await integrations.update_connection(
        caller, integration_connection_id, changes
    )


@router.delete(
    "/{integration_connection_id}", status_code=status.HTTP_204_NO_CONTENT
)
async def delete_connection(
    integration_connection_id: UUID,
    caller: Caller,
    integrations: Integrations,
) -> Response:
    await integrations.delete_connection(caller, integration_connection_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{integration_connection_id}/validate")
async def validate_connection(
    integration_connection_id: UUID,
    caller: Caller,
    integrations: Integrations,
) -> dict[str, Any]:
    return await integrations.validate_connection(caller, integration_connection_id)


@router.get("/{integration_connection_id}/resources")
async def list_connection_resources(
    integration_connection_id: UUID,
    caller: Caller,
    integrations: Integrations,
    connector_key: str | None = None,
    parent_id: Annotated[str | None, Query(max_length=1_024)] = None,
    search: Annotated[str | None, Query(max_length=255)] = None,
) -> dict[str, Any]:
    """What this account can reach, for choosing what to synchronize."""

    return await integrations.list_connection_resources(
        caller,
        integration_connection_id,
        connector_key=connector_key,
        parent_id=parent_id,
        search=search,
    )


@router.post("/{integration_connection_id}/sources", status_code=status.HTTP_201_CREATED)
async def create_connection_source(
    integration_connection_id: UUID,
    body: IngestionSourceCreate,
    caller: Caller,
    integrations: Integrations,
) -> dict[str, Any]:
    return await integrations.create_source(
        caller, integration_connection_id, body.model_dump()
    )


def _script_literal(value: Any) -> str:
    """Serialize one value for embedding inside a script element.

    ``json.dumps`` alone is not enough: it leaves ``/`` untouched, so the
    sequence ``</script>`` inside a string would end this tag and everything
    after it would be parsed as markup. The line separators are escaped for the
    same reason — older parsers treat them as statement terminators.
    """

    return (
        json.dumps(value)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )


def _provider_error(error: str | None, description: str | None) -> str:
    """Say what the provider said, not a summary of it.

    A misconfigured app fails here with something specific and fixable — an
    unapproved scope, an unregistered redirect — and replacing that with
    "authorization failed" would cost whoever is setting this up an afternoon.
    """

    if error == "access_denied":
        return "The account owner declined this authorization."
    detail = (description or "").strip() or (error or "").strip()
    if not detail:
        return "The provider did not complete the authorization."
    return f"{detail[:400]} (reported by the provider)"


def _completion_page(
    origin: str, payload: dict[str, Any], *, status_code: int = 200
) -> HTMLResponse:
    """Hand one fixed-shape result to the window that opened this flow.

    The message goes to exactly one origin, and every value in it is escaped
    for a script element rather than merely JSON-encoded, so no text a provider
    put in the query string can close this tag or become markup.
    """

    message = _script_literal({"source": "bothesis.connection", **payload})
    target = _script_literal(origin)
    return HTMLResponse(
        status_code=status_code,
        headers={
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
        content=(
            "<!doctype html><meta charset=\"utf-8\">"
            "<title>Finishing up…</title>"
            "<p>You can close this window.</p>"
            "<script>"
            f"var message = {message}; var target = {target};"
            "if (window.opener) { window.opener.postMessage(message, target); }"
            "window.close();"
            "</script>"
        ),
    )


__all__ = ["router"]
