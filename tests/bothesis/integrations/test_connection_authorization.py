"""The authorization boundary: state, providers, and resource translation."""

from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from bothesis.connector.confluence._confluence import FinxConfluence
from bothesis.integrations import (
    IntegrationAuthorizationError,
    IntegrationConfigurationError,
    PendingAuthorization,
    ProviderCredentials,
    ProviderResource,
    expiry_from_seconds,
    granted_scopes,
    pkce_pair,
)
from bothesis.integrations.atlassian import AtlassianConnectionProvider
from bothesis.integrations.google import GoogleConnectionProvider
from bothesis.integrations.oauth_state import OAuthStateCodec
from bothesis.integrations.registry import ConnectionProviderRegistry

_SECRET = "a-local-test-state-secret-value"


class _RivalConfluenceProvider(AtlassianConnectionProvider):
    """A second provider claiming Confluence. The registry must refuse it."""

    def __init__(self) -> None:
        super().__init__(client_id="c", client_secret="s", redirect_uri="https://r")

    @property
    def definition(self) -> Any:
        return replace(super().definition, key="rival")


def _pending(**overrides: Any) -> PendingAuthorization:
    values: dict[str, Any] = {
        "tenant_id": "11111111-1111-1111-1111-111111111111",
        "user_id": "22222222-2222-2222-2222-222222222222",
        "provider_key": "google",
        "connector_key": "google_drive",
        "owner_type": "tenant",
        "connection_id": None,
        "code_verifier": "verifier-value",
        "nonce": "nonce-value",
    }
    values.update(overrides)
    return PendingAuthorization(**values)


def _google() -> GoogleConnectionProvider:
    return GoogleConnectionProvider(
        client_id="client", client_secret="secret", redirect_uri="https://api/callback"
    )


def _atlassian() -> AtlassianConnectionProvider:
    return AtlassianConnectionProvider(
        client_id="client", client_secret="secret", redirect_uri="https://api/callback"
    )


class TestOAuthState:
    def test_round_trip_preserves_the_pending_authorization(self) -> None:
        codec = OAuthStateCodec(_SECRET)
        pending = _pending(connection_id="33333333-3333-3333-3333-333333333333")

        assert codec.read(codec.issue(pending)) == pending

    def test_the_verifier_is_not_readable_from_the_state(self) -> None:
        """PKCE is pointless if the redirect carries the verifier in the clear."""

        state = OAuthStateCodec(_SECRET).issue(_pending(code_verifier="s3cret-verifier"))

        assert "s3cret-verifier" not in state

    def test_a_state_signed_with_another_secret_is_rejected(self) -> None:
        state = OAuthStateCodec("a-different-deployment-secret").issue(_pending())

        with pytest.raises(IntegrationAuthorizationError):
            OAuthStateCodec(_SECRET).read(state)

    @pytest.mark.parametrize("position", [0, 11, 40])
    def test_a_tampered_state_is_rejected(self, position: int) -> None:
        """Positions inside the nonce and inside the ciphertext, not the tail.

        The final base64 character carries spare bits that can decode to the
        same bytes, so flipping it is not reliably a change at all.
        """

        codec = OAuthStateCodec(_SECRET)
        state = codec.issue(_pending())
        original = state[position]
        replacement = "A" if original != "A" else "B"
        tampered = state[:position] + replacement + state[position + 1 :]

        with pytest.raises(IntegrationAuthorizationError):
            codec.read(tampered)

    def test_an_expired_state_cannot_be_replayed(self) -> None:
        codec = OAuthStateCodec(_SECRET, lifetime_seconds=-1)

        with pytest.raises(IntegrationAuthorizationError, match="expired"):
            OAuthStateCodec(_SECRET).read(codec.issue(_pending()))

    def test_an_unconfigured_deployment_says_so(self) -> None:
        with pytest.raises(IntegrationConfigurationError):
            OAuthStateCodec(None).issue(_pending())


class TestPkce:
    def test_the_challenge_is_the_s256_digest_of_the_verifier(self) -> None:
        import base64
        import hashlib

        verifier, challenge = pkce_pair()
        expected = (
            base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
            .rstrip(b"=")
            .decode()
        )

        assert challenge == expected
        assert "=" not in verifier and "=" not in challenge

    def test_each_pair_is_distinct(self) -> None:
        assert pkce_pair()[0] != pkce_pair()[0]


class TestProviderRegistry:
    def test_a_connector_resolves_to_the_provider_that_authorizes_it(self) -> None:
        registry = ConnectionProviderRegistry((_google(), _atlassian()))

        assert registry.for_connector("google_drive").definition.key == "google"
        assert registry.for_connector("confluence").definition.key == "atlassian"

    def test_a_connector_with_no_provider_is_a_supported_answer(self) -> None:
        """Managed file uploads are a connector that nothing authorizes."""

        assert ConnectionProviderRegistry((_google(),)).for_connector("file") is None

    def test_two_providers_cannot_claim_one_connector(self) -> None:
        """Routing a connector to two authorizations has no right answer."""

        registry = ConnectionProviderRegistry((_atlassian(),))

        with pytest.raises(ValueError, match="already provided"):
            registry.register(_RivalConfluenceProvider())


class TestGoogleProvider:
    def test_the_consent_url_asks_for_an_offline_pkce_grant(self) -> None:
        url = _google().authorization_url(state="ST", code_challenge="CH")

        assert "code_challenge=CH" in url
        assert "code_challenge_method=S256" in url
        # Without both of these Google issues no refresh token, and the
        # connection would need a person again within the hour.
        assert "access_type=offline" in url
        assert "prompt=consent" in url

    def test_it_asks_only_for_read_access(self) -> None:
        url = _google().authorization_url(state="ST", code_challenge="CH")

        assert "drive.readonly" in url
        assert "auth%2Fdrive&" not in url

    def test_an_unconfigured_deployment_cannot_build_a_url(self) -> None:
        provider = GoogleConnectionProvider(
            client_id=None, client_secret=None, redirect_uri=None
        )

        assert provider.configured is False
        with pytest.raises(IntegrationConfigurationError):
            provider.authorization_url(state="ST", code_challenge="CH")

    @pytest.mark.parametrize(
        ("resource_type", "external_id", "expected"),
        [
            ("drive", "my-drive", {}),
            ("shared_drive", "0ABC", {"shared_drive_id": "0ABC"}),
            ("folder", "1xyz", {"folder_id": "1xyz"}),
        ],
    )
    def test_a_selected_resource_becomes_the_config_the_connector_runs_on(
        self, resource_type: str, external_id: str, expected: dict[str, Any]
    ) -> None:
        """A caller picks a drive; it never has to know the connector's keys."""

        resource = ProviderResource(
            capability="google_drive",
            resource_type=resource_type,
            external_id=external_id,
            name="Anything",
        )

        assert _google().source_config(resource) == expected

    def test_the_drive_runtime_gets_its_client_from_the_provider(self) -> None:
        """No connector branch in the connection service means no leak."""

        config = _google().connector_runtime_config("google_drive")

        assert config["_google_drive_client_id"] == "client"
        assert config["_google_drive_token_url"].startswith("https://")
        assert _google().connector_runtime_config("confluence") == {}

    @pytest.mark.asyncio
    async def test_a_refresh_that_returns_no_new_refresh_token_keeps_the_old_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Google omits the field when it did not rotate; dropping it ends the grant."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"access_token": "new-access", "expires_in": 3600}
            )

        _install_transport(monkeypatch, handler)
        refreshed = await _google().refresh(
            ProviderCredentials(values={"refresh_token": "original-refresh"})
        )

        assert refreshed is not None
        assert refreshed.values["access_token"] == "new-access"
        assert refreshed.values["refresh_token"] == "original-refresh"
        assert refreshed.expires_at is not None

    @pytest.mark.asyncio
    async def test_a_rotated_refresh_token_replaces_the_old_one(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "rotated-refresh",
                    "expires_in": 3600,
                },
            )

        _install_transport(monkeypatch, handler)
        refreshed = await _google().refresh(
            ProviderCredentials(values={"refresh_token": "original-refresh"})
        )

        assert refreshed is not None
        assert refreshed.values["refresh_token"] == "rotated-refresh"

    @pytest.mark.asyncio
    async def test_a_revoked_grant_is_reported_as_needing_authorization(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                400,
                json={
                    "error": "invalid_grant",
                    "error_description": "Token has been expired or revoked.",
                },
            )

        _install_transport(monkeypatch, handler)
        with pytest.raises(IntegrationAuthorizationError, match="revoked"):
            await _google().refresh(
                ProviderCredentials(values={"refresh_token": "dead-refresh"})
            )

    @pytest.mark.asyncio
    async def test_an_exchange_without_a_refresh_token_is_refused(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A grant that cannot be refreshed would break on its first sync."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200, json={"access_token": "access-only", "expires_in": 3600}
            )

        _install_transport(monkeypatch, handler)
        with pytest.raises(IntegrationAuthorizationError, match="refresh token"):
            await _google().exchange(code="CODE", code_verifier="VERIFIER")

    @pytest.mark.asyncio
    async def test_discovery_lists_my_drive_and_every_shared_drive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["Authorization"] == "Bearer access"
            return httpx.Response(
                200,
                json={"drives": [{"id": "0ABC", "name": "Engineering"}]},
            )

        _install_transport(monkeypatch, handler)
        resources = await _google().list_resources(
            ProviderCredentials(values={"access_token": "access"}),
            connector_key="google_drive",
        )

        assert [resource.external_id for resource in resources] == ["my-drive", "0ABC"]
        assert resources[1].resource_type == "shared_drive"


class TestAtlassianProvider:
    def test_confluence_is_a_capability_of_the_account_authorization(self) -> None:
        definition = _atlassian().definition

        assert definition.capability("confluence") is not None
        assert definition.capability("google_drive") is None

    def test_the_grant_asks_for_offline_access(self) -> None:
        """Atlassian issues a refresh token only for an offline_access grant."""

        url = _atlassian().authorization_url(state="ST", code_challenge="CH")

        assert "offline_access" in url
        assert "code_challenge_method=S256" in url

    def test_a_site_becomes_the_connection_api_base(self) -> None:
        config = _atlassian().site_config("cloud-id-1")

        assert config["wiki_base"].endswith("/ex/confluence/cloud-id-1/wiki")

    def test_a_selected_space_becomes_the_connector_scope(self) -> None:
        resource = ProviderResource(
            capability="confluence",
            resource_type="space",
            external_id="ENG",
            name="Engineering",
        )

        assert _atlassian().source_config(resource) == {"space": "ENG"}

    @pytest.mark.asyncio
    async def test_a_refresh_carries_the_site_and_rotated_token_forward(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Atlassian rotates on every use and never repeats the cloud id."""

        async def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "access_token": "new-access",
                    "refresh_token": "rotated",
                    "expires_in": 3600,
                },
            )

        _install_transport(monkeypatch, handler)
        refreshed = await _atlassian().refresh(
            ProviderCredentials(
                values={"refresh_token": "original", "cloud_id": "cloud-id-1"}
            )
        )

        assert refreshed is not None
        assert refreshed.values["refresh_token"] == "rotated"
        assert refreshed.values["cloud_id"] == "cloud-id-1"


class TestConfluencePagination:
    """A next link is site-relative; the gateway prefix must survive it."""

    def test_a_site_base_resolves_a_wiki_relative_link(self) -> None:
        client = FinxConfluence(
            {"username": "u", "api_token": "t", "is_cloud": True},
            "https://team.atlassian.net/wiki",
        )

        assert (
            client._absolute_next_url("/wiki/rest/api/content?cursor=x")
            == "https://team.atlassian.net/wiki/rest/api/content?cursor=x"
        )

    def test_the_oauth_gateway_base_keeps_its_cloud_id(self) -> None:
        client = FinxConfluence(
            {"access_token": "bearer-token", "is_cloud": True},
            "https://api.atlassian.com/ex/confluence/CID/wiki",
        )

        assert client._absolute_next_url("/wiki/rest/api/content?cursor=x") == (
            "https://api.atlassian.com/ex/confluence/CID/wiki/rest/api/content?cursor=x"
        )

    def test_a_bearer_token_wins_over_basic_auth(self) -> None:
        """An authorized connection must not also send an account password."""

        client = FinxConfluence(
            {"username": "u", "api_token": "t", "access_token": "bearer-token"},
            "https://api.atlassian.com/ex/confluence/CID/wiki",
        )
        session = client.confluence_client._session

        assert session.headers.get("Authorization") == "Bearer bearer-token"
        assert client.confluence_client.username is None

    def test_an_api_token_still_authenticates_a_site_connection(self) -> None:
        client = FinxConfluence(
            {"username": "u@example.com", "api_token": "t", "is_cloud": True},
            "https://team.atlassian.net/wiki",
        )

        assert client.confluence_client.username == "u@example.com"
        assert client.confluence_client._session.headers.get("Authorization") is None


class TestOAuthValueParsing:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [("a b  c", ("a", "b", "c")), (["a", "b"], ("a", "b")), (None, ()), (7, ())],
    )
    def test_scopes_are_read_without_trusting_their_type(
        self, value: Any, expected: tuple[str, ...]
    ) -> None:
        assert granted_scopes(value) == expected

    @pytest.mark.parametrize("value", [None, "3600", True, 0, -1])
    def test_a_non_numeric_expiry_is_no_expiry(self, value: Any) -> None:
        assert expiry_from_seconds(value, now=datetime.now(UTC)) is None

    def test_a_numeric_expiry_is_offset_from_now(self) -> None:
        now = datetime(2026, 1, 1, tzinfo=UTC)

        assert expiry_from_seconds(3600, now=now) == now + timedelta(hours=1)


def _install_transport(
    monkeypatch: pytest.MonkeyPatch, handler: Any
) -> None:
    """Answer every provider call from this test instead of the network."""

    original = httpx.AsyncClient.__init__

    def patched(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)


def test_the_completion_page_cannot_be_injected_into() -> None:
    """A provider's error text must not be able to close this script tag."""

    from api.routers.connections import _completion_page

    hostile = "</script><img src=x onerror=alert(1)>"
    response = _completion_page(
        "https://app.example", {"status": "error", "message": hostile}
    )
    body = response.body.decode()
    literal = body.split("var message = ", 1)[1].split("; var target", 1)[0]

    # Nothing in the payload reaches the document as markup...
    assert "<img" not in body
    assert body.count("</script>") == 1
    # ...and the message still arrives intact at the opener.
    assert json.loads(literal)["message"] == hostile
    assert response.headers["Cache-Control"] == "no-store"


def test_a_provider_error_reaches_the_reader_verbatim() -> None:
    """An unapproved scope is fixable; "authorization failed" is not."""

    from api.routers.connections import _provider_error

    assert "read:confluence-content.all" in _provider_error(
        "invalid_scope", "read:confluence-content.all is not configured for this app"
    )
    assert _provider_error("access_denied", None) == (
        "The account owner declined this authorization."
    )
    assert "invalid_request" in _provider_error("invalid_request", None)
    assert _provider_error(None, None).startswith("The provider did not")


def test_the_completion_page_talks_to_exactly_one_origin() -> None:
    """A wildcard target would hand the result to any page that opened it."""

    body = _page_body("https://app.example")

    assert '"https://app.example"' in body
    assert '"*"' not in body


def _page_body(origin: str) -> str:
    from api.routers.connections import _completion_page

    return _completion_page(origin, {"status": "connected"}).body.decode()
