"""Google account authorization for the Google Drive connector."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlencode

import httpx

from bothesis.integrations import (
    AuthorizationGrant,
    IntegrationAuthorizationError,
    IntegrationConfigurationError,
    IntegrationUnavailableError,
    ProviderAccount,
    ProviderCapability,
    ProviderCredentials,
    ProviderDefinition,
    ProviderResource,
    expiry_from_seconds,
    granted_scopes,
)

GOOGLE_PROVIDER_KEY = "google"
GOOGLE_DRIVE_CONNECTOR_KEY = "google_drive"

_AUTHORIZATION_URL = "https://accounts.google.com/o/oauth2/v2/auth"
_TOKEN_URL = "https://oauth2.googleapis.com/token"
_REVOKE_URL = "https://oauth2.googleapis.com/revoke"
_USERINFO_URL = "https://www.googleapis.com/oauth2/v3/userinfo"
_DRIVE_API_URL = "https://www.googleapis.com/drive/v3"

#: Read-only Drive plus the account's own identity. Nothing here can change a
#: file, and no scope is requested that ingestion does not read.
_SCOPES = (
    "https://www.googleapis.com/auth/drive.readonly",
    "openid",
    "email",
)

_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
_MY_DRIVE_ID = "my-drive"
_MAX_RESOURCE_PAGES = 10


class GoogleConnectionProvider:
    """Authorize one Google account and enumerate the Drives it can read."""

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str | None,
        timeout_seconds: float = 20.0,
        authorization_url: str = _AUTHORIZATION_URL,
        token_url: str = _TOKEN_URL,
        revoke_url: str = _REVOKE_URL,
        userinfo_url: str = _USERINFO_URL,
        drive_api_url: str = _DRIVE_API_URL,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout_seconds = timeout_seconds
        self._authorization_url = authorization_url
        self._token_url = token_url
        self._revoke_url = revoke_url
        self._userinfo_url = userinfo_url
        self._drive_api_url = drive_api_url.rstrip("/")

    @property
    def definition(self) -> ProviderDefinition:
        return ProviderDefinition(
            key=GOOGLE_PROVIDER_KEY,
            display_name="Google",
            authorization_type="oauth",
            capabilities=(
                ProviderCapability(
                    connector_key=GOOGLE_DRIVE_CONNECTOR_KEY,
                    display_name="Google Drive",
                    resource_type="drive",
                ),
            ),
            scopes=_SCOPES,
        )

    @property
    def configured(self) -> bool:
        return bool(self._client_id and self._client_secret and self._redirect_uri)

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        client_id, _, redirect_uri = self._client()
        query = urlencode(
            {
                "client_id": client_id,
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "scope": " ".join(_SCOPES),
                "state": state,
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
                # A refresh token is issued only for an offline grant, and only
                # re-prompting guarantees one when the account already consented.
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
            }
        )
        return f"{self._authorization_url}?{query}"

    async def exchange(self, *, code: str, code_verifier: str) -> AuthorizationGrant:
        client_id, client_secret, redirect_uri = self._client()
        payload = await self._token_request(
            {
                "grant_type": "authorization_code",
                "code": code,
                "client_id": client_id,
                "client_secret": client_secret,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        access_token = _required_text(payload.get("access_token"), "access token")
        refresh_token = _optional_text(payload.get("refresh_token"))
        if refresh_token is None:
            raise IntegrationAuthorizationError(
                "Google did not return a refresh token. Remove BoThesis from the "
                "account's third-party access and authorize again."
            )
        expires_at = expiry_from_seconds(
            payload.get("expires_in"), now=datetime.now(UTC)
        )
        account = await self._account(access_token)
        return AuthorizationGrant(
            account=account,
            credentials=ProviderCredentials(
                values={
                    "access_token": access_token,
                    "refresh_token": refresh_token,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                },
                expires_at=expires_at,
            ),
            scopes=granted_scopes(payload.get("scope")) or _SCOPES,
        )

    async def refresh(
        self, credentials: ProviderCredentials
    ) -> ProviderCredentials | None:
        client_id, client_secret, _ = self._client()
        refresh_token = _optional_text(credentials.values.get("refresh_token"))
        if refresh_token is None:
            raise IntegrationAuthorizationError(
                "this Google connection has no refresh token and must be reconnected"
            )
        payload = await self._token_request(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "client_id": client_id,
                "client_secret": client_secret,
            }
        )
        access_token = _required_text(payload.get("access_token"), "access token")
        expires_at = expiry_from_seconds(
            payload.get("expires_in"), now=datetime.now(UTC)
        )
        return ProviderCredentials(
            values={
                "access_token": access_token,
                # Google rotates refresh tokens for some clients and omits the
                # field otherwise; dropping the previous one would end the grant.
                "refresh_token": _optional_text(payload.get("refresh_token"))
                or refresh_token,
                "expires_at": expires_at.isoformat() if expires_at else None,
            },
            expires_at=expires_at,
        )

    async def revoke(self, credentials: ProviderCredentials) -> None:
        token = _optional_text(
            credentials.values.get("refresh_token")
        ) or _optional_text(credentials.values.get("access_token"))
        if token is None:
            return
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            # A grant the account already removed answers 400. That is the
            # intended end state, so the status is not inspected; only a
            # transport failure, which means nothing was revoked, propagates.
            await _post_form(client, self._revoke_url, {"token": token})

    async def list_resources(
        self,
        credentials: ProviderCredentials,
        *,
        connector_key: str,
        parent_id: str | None = None,
        search: str | None = None,
    ) -> tuple[ProviderResource, ...]:
        if connector_key.strip().casefold() != GOOGLE_DRIVE_CONNECTOR_KEY:
            raise IntegrationAuthorizationError(
                f"Google cannot list resources for {connector_key}"
            )
        token = _required_text(credentials.values.get("access_token"), "access token")
        if parent_id is None:
            return (
                ProviderResource(
                    capability=GOOGLE_DRIVE_CONNECTOR_KEY,
                    resource_type="drive",
                    external_id=_MY_DRIVE_ID,
                    name="My Drive",
                    has_children=True,
                ),
                *await self._shared_drives(token, search),
            )
        return await self._folders(token, parent_id, search)

    def connector_runtime_config(self, connector_key: str) -> Mapping[str, Any]:
        if connector_key.strip().casefold() != GOOGLE_DRIVE_CONNECTOR_KEY:
            return {}
        client_id, client_secret, _ = self._client()
        return {
            "_google_drive_client_id": client_id,
            "_google_drive_client_secret": client_secret,
            "_google_drive_token_url": self._token_url,
            "_google_drive_api_url": self._drive_api_url,
            "_google_drive_timeout_seconds": self._timeout_seconds,
        }

    def source_config(self, resource: ProviderResource) -> Mapping[str, Any]:
        if resource.resource_type == "folder":
            return {"folder_id": resource.external_id}
        if resource.external_id == _MY_DRIVE_ID:
            return {}
        return {"shared_drive_id": resource.external_id}

    # -- Internals ----------------------------------------------------------

    def _client(self) -> tuple[str, str, str]:
        if not self.configured:
            raise IntegrationConfigurationError(
                "Google authorization needs BOTHESIS_GOOGLE_OAUTH_CLIENT_ID, "
                "BOTHESIS_GOOGLE_OAUTH_CLIENT_SECRET, and "
                "BOTHESIS_INTEGRATION_OAUTH_REDIRECT_URI"
            )
        assert self._client_id and self._client_secret and self._redirect_uri
        return self._client_id, self._client_secret, self._redirect_uri

    async def _token_request(self, form: Mapping[str, str]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await _post_form(client, self._token_url, form)
        if response.status_code >= 400:
            raise IntegrationAuthorizationError(
                f"Google refused the authorization: {_error_detail(response)}"
            )
        return _json_object(response)

    async def _account(self, access_token: str) -> ProviderAccount:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await _get(client, self._userinfo_url, access_token)
        if response.status_code >= 400:
            raise IntegrationAuthorizationError(
                f"the Google account could not be read: {_error_detail(response)}"
            )
        payload = _json_object(response)
        subject = _optional_text(payload.get("sub"))
        email = _optional_text(payload.get("email"))
        if subject is None:
            raise IntegrationAuthorizationError("Google returned no account identity")
        return ProviderAccount(account_id=subject, label=email or subject)

    async def _shared_drives(
        self, token: str, search: str | None
    ) -> tuple[ProviderResource, ...]:
        resources: list[ProviderResource] = []
        page_token: str | None = None
        for _ in range(_MAX_RESOURCE_PAGES):
            params: dict[str, str] = {"pageSize": "100", "fields": "nextPageToken,drives(id,name)"}
            if page_token:
                params["pageToken"] = page_token
            payload = await self._drive_get("/drives", token, params)
            for drive in payload.get("drives") or []:
                identifier = _optional_text(drive.get("id"))
                if identifier is None:
                    continue
                name = _optional_text(drive.get("name")) or identifier
                if search and search.casefold() not in name.casefold():
                    continue
                resources.append(
                    ProviderResource(
                        capability=GOOGLE_DRIVE_CONNECTOR_KEY,
                        resource_type="shared_drive",
                        external_id=identifier,
                        name=name,
                        has_children=True,
                    )
                )
            page_token = _optional_text(payload.get("nextPageToken"))
            if page_token is None:
                break
        return tuple(resources)

    async def _folders(
        self, token: str, parent_id: str, search: str | None
    ) -> tuple[ProviderResource, ...]:
        shared_drive = parent_id if parent_id != _MY_DRIVE_ID else None
        clauses = [f"mimeType = '{_FOLDER_MIME_TYPE}'", "trashed = false"]
        if shared_drive is None:
            clauses.append("'root' in parents")
        if search:
            clauses.append(f"name contains '{_escaped(search)}'")
        params: dict[str, str] = {
            "q": " and ".join(clauses),
            "pageSize": "100",
            "fields": "files(id,name,parents,webViewLink)",
            "supportsAllDrives": "true",
            "includeItemsFromAllDrives": "true",
        }
        if shared_drive is not None:
            params["corpora"] = "drive"
            params["driveId"] = shared_drive
        payload = await self._drive_get("/files", token, params)
        return tuple(
            ProviderResource(
                capability=GOOGLE_DRIVE_CONNECTOR_KEY,
                resource_type="folder",
                external_id=identifier,
                name=_optional_text(entry.get("name")) or identifier,
                parent_id=parent_id,
                has_children=True,
                url=_optional_text(entry.get("webViewLink")),
            )
            for entry in payload.get("files") or []
            if (identifier := _optional_text(entry.get("id"))) is not None
        )

    async def _drive_get(
        self, path: str, token: str, params: Mapping[str, str]
    ) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            response = await _get(
                client, f"{self._drive_api_url}{path}", token, params=params
            )
        if response.status_code in {401, 403}:
            raise IntegrationAuthorizationError(
                f"Google Drive refused this connection: {_error_detail(response)}"
            )
        if response.status_code >= 400:
            raise IntegrationUnavailableError(
                f"Google Drive could not be read: {_error_detail(response)}"
            )
        return _json_object(response)


async def _post_form(
    client: httpx.AsyncClient, url: str, form: Mapping[str, str]
) -> httpx.Response:
    try:
        return await client.post(url, data=dict(form))
    except httpx.HTTPError as exc:
        raise IntegrationUnavailableError(f"Google is unreachable: {exc}") from exc


async def _get(
    client: httpx.AsyncClient,
    url: str,
    token: str,
    *,
    params: Mapping[str, str] | None = None,
) -> httpx.Response:
    try:
        return await client.get(
            url,
            headers={"Authorization": f"Bearer {token}"},
            params=dict(params or {}),
        )
    except httpx.HTTPError as exc:
        raise IntegrationUnavailableError(f"Google is unreachable: {exc}") from exc


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = response.json()
    except ValueError as exc:
        raise IntegrationUnavailableError("Google returned an unreadable response") from exc
    if not isinstance(payload, dict):
        raise IntegrationUnavailableError("Google returned an unexpected response")
    return payload


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        description = payload.get("error_description") or payload.get("error")
        if isinstance(description, dict):
            description = description.get("message")
        if isinstance(description, str) and description:
            return description
    return f"HTTP {response.status_code}"


def _escaped(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _required_text(value: Any, name: str) -> str:
    result = _optional_text(value)
    if result is None:
        raise IntegrationAuthorizationError(f"Google returned no {name}")
    return result


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = ["GOOGLE_DRIVE_CONNECTOR_KEY", "GOOGLE_PROVIDER_KEY", "GoogleConnectionProvider"]
