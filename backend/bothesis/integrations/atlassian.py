"""Atlassian account authorization for the Confluence connector.

One Atlassian authorization is granted against one site and can carry several
product scopes, so Confluence is modelled as a *capability* of the connection
rather than as an integration of its own. Adding Jira later is a capability and
a connector, not a second authorization for the same account.
"""

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

ATLASSIAN_PROVIDER_KEY = "atlassian"
CONFLUENCE_CONNECTOR_KEY = "confluence"

_AUTHORIZATION_URL = "https://auth.atlassian.com/authorize"
_TOKEN_URL = "https://auth.atlassian.com/oauth/token"
_API_URL = "https://api.atlassian.com"
_AUDIENCE = "api.atlassian.com"

#: Read-only Confluence, plus the refresh grant and the caller's identity.
_SCOPES = (
    "read:confluence-space.summary",
    "read:confluence-content.all",
    "read:confluence-content.summary",
    "read:me",
    "offline_access",
)

_MAX_RESOURCE_PAGES = 20


class AtlassianConnectionProvider:
    """Authorize one Atlassian site and enumerate the spaces it can read."""

    def __init__(
        self,
        *,
        client_id: str | None,
        client_secret: str | None,
        redirect_uri: str | None,
        timeout_seconds: float = 20.0,
        authorization_url: str = _AUTHORIZATION_URL,
        token_url: str = _TOKEN_URL,
        api_url: str = _API_URL,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._timeout_seconds = timeout_seconds
        self._authorization_url = authorization_url
        self._token_url = token_url
        self._api_url = api_url.rstrip("/")

    @property
    def definition(self) -> ProviderDefinition:
        return ProviderDefinition(
            key=ATLASSIAN_PROVIDER_KEY,
            display_name="Atlassian",
            authorization_type="oauth",
            capabilities=(
                ProviderCapability(
                    connector_key=CONFLUENCE_CONNECTOR_KEY,
                    display_name="Confluence",
                    resource_type="space",
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
                "audience": _AUDIENCE,
                "client_id": client_id,
                "scope": " ".join(_SCOPES),
                "redirect_uri": redirect_uri,
                "state": state,
                "response_type": "code",
                "prompt": "consent",
                "code_challenge": code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{self._authorization_url}?{query}"

    async def exchange(self, *, code: str, code_verifier: str) -> AuthorizationGrant:
        client_id, client_secret, redirect_uri = self._client()
        payload = await self._token_request(
            {
                "grant_type": "authorization_code",
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": code_verifier,
            }
        )
        credentials = self._credentials_from(payload, previous=None)
        access_token = str(credentials.values["access_token"])
        site = await self._site(access_token)
        account = await self._account(access_token, site)
        return AuthorizationGrant(
            account=account,
            credentials=credentials.merged({"cloud_id": site.resource_id}),
            scopes=granted_scopes(payload.get("scope")) or _SCOPES,
            config=self.site_config(site.resource_id or ""),
        )

    async def refresh(
        self, credentials: ProviderCredentials
    ) -> ProviderCredentials | None:
        client_id, client_secret, _ = self._client()
        refresh_token = _optional_text(credentials.values.get("refresh_token"))
        if refresh_token is None:
            raise IntegrationAuthorizationError(
                "this Atlassian connection has no refresh token and must be reconnected"
            )
        payload = await self._token_request(
            {
                "grant_type": "refresh_token",
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": refresh_token,
            }
        )
        return self._credentials_from(payload, previous=credentials)

    async def revoke(self, credentials: ProviderCredentials) -> None:
        # Atlassian publishes no token-revocation endpoint for 3LO apps; a grant
        # is withdrawn by the account owner or by deleting the app install.
        # Forgetting the stored secret is the whole of what this deployment can
        # do, and the caller does that whether or not this call exists.
        del credentials

    async def list_resources(
        self,
        credentials: ProviderCredentials,
        *,
        connector_key: str,
        parent_id: str | None = None,
        search: str | None = None,
    ) -> tuple[ProviderResource, ...]:
        if connector_key.strip().casefold() != CONFLUENCE_CONNECTOR_KEY:
            raise IntegrationAuthorizationError(
                f"Atlassian cannot list resources for {connector_key}"
            )
        if parent_id is not None:
            return ()
        token = _required_text(credentials.values.get("access_token"), "access token")
        cloud_id = _required_text(credentials.values.get("cloud_id"), "site identifier")
        return await self._spaces(token, cloud_id, search)

    def connector_runtime_config(self, connector_key: str) -> Mapping[str, Any]:
        # Every endpoint a Confluence runtime needs is already on the connection
        # (``wiki_base``), because an Atlassian grant is bound to one site.
        del connector_key
        return {}

    def source_config(self, resource: ProviderResource) -> Mapping[str, Any]:
        return {"space": resource.external_id}

    def site_config(self, cloud_id: str) -> dict[str, Any]:
        """Connection config that points the Confluence runtime at one site."""

        return {
            "wiki_base": f"{self._api_url}/ex/confluence/{cloud_id}/wiki",
            "is_cloud": True,
        }

    # -- Internals ----------------------------------------------------------

    def _client(self) -> tuple[str, str, str]:
        if not self.configured:
            raise IntegrationConfigurationError(
                "Atlassian authorization needs BOTHESIS_ATLASSIAN_OAUTH_CLIENT_ID, "
                "BOTHESIS_ATLASSIAN_OAUTH_CLIENT_SECRET, and "
                "BOTHESIS_INTEGRATION_OAUTH_REDIRECT_URI"
            )
        assert self._client_id and self._client_secret and self._redirect_uri
        return self._client_id, self._client_secret, self._redirect_uri

    def _credentials_from(
        self, payload: Mapping[str, Any], *, previous: ProviderCredentials | None
    ) -> ProviderCredentials:
        access_token = _required_text(payload.get("access_token"), "access token")
        carried = dict(previous.values) if previous is not None else {}
        # Atlassian rotates the refresh token on every use and only issues one
        # at all for an ``offline_access`` grant.
        refresh_token = _optional_text(
            payload.get("refresh_token")
        ) or _optional_text(carried.get("refresh_token"))
        if refresh_token is None:
            raise IntegrationAuthorizationError(
                "Atlassian returned no refresh token; the offline_access scope "
                "must be granted"
            )
        expires_at = expiry_from_seconds(
            payload.get("expires_in"), now=datetime.now(UTC)
        )
        return ProviderCredentials(
            values={
                "access_token": access_token,
                "refresh_token": refresh_token,
                "expires_at": expires_at.isoformat() if expires_at else None,
                # The site the grant is bound to never changes on refresh.
                "cloud_id": _optional_text(carried.get("cloud_id")),
            },
            expires_at=expires_at,
        )

    async def _token_request(self, form: Mapping[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                response = await client.post(self._token_url, json=dict(form))
            except httpx.HTTPError as exc:
                raise IntegrationUnavailableError(
                    f"Atlassian is unreachable: {exc}"
                ) from exc
        if response.status_code >= 400:
            raise IntegrationAuthorizationError(
                f"Atlassian refused the authorization: {_error_detail(response)}"
            )
        return _json_object(response)

    async def _site(self, access_token: str) -> ProviderAccount:
        payload = await self._api_get(
            "/oauth/token/accessible-resources", access_token, expect="list"
        )
        sites = [entry for entry in payload if isinstance(entry, dict)]
        if not sites:
            raise IntegrationAuthorizationError(
                "this Atlassian account granted access to no site"
            )
        # A 3LO grant may cover several sites. One Connection is one site, so the
        # first is taken and the rest are reachable by authorizing again; that
        # keeps a connection's scope, health, and revocation unambiguous.
        site = sites[0]
        cloud_id = _required_text(site.get("id"), "site identifier")
        url = _optional_text(site.get("url")) or ""
        return ProviderAccount(
            account_id="",
            label="",
            resource_id=cloud_id,
            resource_label=_optional_text(site.get("name")) or url or cloud_id,
        )

    async def _account(self, access_token: str, site: ProviderAccount) -> ProviderAccount:
        payload = await self._api_get("/me", access_token, expect="object")
        account_id = _required_text(payload.get("account_id"), "account identity")
        label = (
            _optional_text(payload.get("email"))
            or _optional_text(payload.get("name"))
            or account_id
        )
        return ProviderAccount(
            account_id=account_id,
            label=label,
            resource_id=site.resource_id,
            resource_label=site.resource_label,
        )

    async def _spaces(
        self, token: str, cloud_id: str, search: str | None
    ) -> tuple[ProviderResource, ...]:
        resources: list[ProviderResource] = []
        path: str | None = f"/ex/confluence/{cloud_id}/wiki/api/v2/spaces?limit=100"
        for _ in range(_MAX_RESOURCE_PAGES):
            if path is None:
                break
            payload = await self._api_get(path, token, expect="object")
            for entry in payload.get("results") or []:
                if not isinstance(entry, dict):
                    continue
                key = _optional_text(entry.get("key"))
                if key is None:
                    continue
                name = _optional_text(entry.get("name")) or key
                if search and search.casefold() not in f"{name} {key}".casefold():
                    continue
                resources.append(
                    ProviderResource(
                        capability=CONFLUENCE_CONNECTOR_KEY,
                        resource_type="space",
                        external_id=key,
                        name=name,
                    )
                )
            links = payload.get("_links")
            next_path = (
                _optional_text(links.get("next")) if isinstance(links, dict) else None
            )
            # v2 returns a site-relative link such as ``/wiki/api/v2/spaces?...``;
            # the gateway prefix has to be put back in front of it.
            path = (
                f"/ex/confluence/{cloud_id}{next_path}"
                if next_path and next_path.startswith("/")
                else None
            )
        return tuple(resources)

    async def _api_get(
        self, path: str, token: str, *, expect: str
    ) -> Any:
        url = path if path.startswith("http") else f"{self._api_url}{path}"
        async with httpx.AsyncClient(timeout=self._timeout_seconds) as client:
            try:
                response = await client.get(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Accept": "application/json",
                    },
                )
            except httpx.HTTPError as exc:
                raise IntegrationUnavailableError(
                    f"Atlassian is unreachable: {exc}"
                ) from exc
        if response.status_code in {401, 403}:
            raise IntegrationAuthorizationError(
                f"Atlassian refused this connection: {_error_detail(response)}"
            )
        if response.status_code >= 400:
            raise IntegrationUnavailableError(
                f"Atlassian could not be read: {_error_detail(response)}"
            )
        return _json_object(response) if expect == "object" else _json_list(response)


def _json_object(response: httpx.Response) -> dict[str, Any]:
    payload = _json(response)
    if not isinstance(payload, dict):
        raise IntegrationUnavailableError("Atlassian returned an unexpected response")
    return payload


def _json_list(response: httpx.Response) -> list[Any]:
    payload = _json(response)
    if not isinstance(payload, list):
        raise IntegrationUnavailableError("Atlassian returned an unexpected response")
    return payload


def _json(response: httpx.Response) -> Any:
    try:
        return response.json()
    except ValueError as exc:
        raise IntegrationUnavailableError(
            "Atlassian returned an unreadable response"
        ) from exc


def _error_detail(response: httpx.Response) -> str:
    try:
        payload = response.json()
    except ValueError:
        return f"HTTP {response.status_code}"
    if isinstance(payload, dict):
        for key in ("error_description", "message", "error"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return f"HTTP {response.status_code}"


def _required_text(value: Any, name: str) -> str:
    result = _optional_text(value)
    if result is None:
        raise IntegrationAuthorizationError(f"Atlassian returned no {name}")
    return result


def _optional_text(value: Any) -> str | None:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


__all__ = [
    "ATLASSIAN_PROVIDER_KEY",
    "CONFLUENCE_CONNECTOR_KEY",
    "AtlassianConnectionProvider",
]
