"""The OAuth lifecycle for connector authorizations.

Connecting an account and choosing what to read from it are two different
decisions, and this service owns only the first: it starts an authorization,
proves the callback belongs to the person who started it, and hands the
resulting grant to the Connection service. It never creates a source, and it
never lets a provider's secret reach the browser.
"""

from __future__ import annotations

import secrets
from urllib.parse import urlparse
from uuid import UUID

from bothesis.integrations import (
    AuthorizationGrant,
    ConnectionProvider,
    IntegrationAuthorizationError,
    IntegrationConfigurationError,
    IntegrationError,
    PendingAuthorization,
    pkce_pair,
)
from bothesis.integrations.oauth_state import OAuthStateCodec
from bothesis.integrations.registry import ConnectionProviderRegistry
from bothesis.services import (
    OWNER_TENANT,
    ControlPlaneExternalUnavailableError,
    ControlPlaneValidationError,
    AuthContext,
    AuthorizationError,
    AuthorizationStart,
    CompletedAuthorization,
)


class IntegrationAuthorizationService:
    """Start and complete a provider authorization without a session cookie."""

    def __init__(
        self,
        providers: ConnectionProviderRegistry,
        *,
        state: OAuthStateCodec,
        client_origin: str | None,
    ) -> None:
        self._providers = providers
        self._state = state
        self._client_origin = (client_origin or "").strip().rstrip("/")

    @property
    def client_origin(self) -> str:
        """The single origin the callback page is allowed to talk back to."""

        if not self._client_origin:
            raise ControlPlaneExternalUnavailableError(
                "BOTHESIS_INTEGRATION_OAUTH_CLIENT_ORIGIN is not configured"
            )
        parsed = urlparse(self._client_origin)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ControlPlaneExternalUnavailableError(
                "BOTHESIS_INTEGRATION_OAUTH_CLIENT_ORIGIN must be an absolute origin"
            )
        return f"{parsed.scheme}://{parsed.netloc}"

    def start(
        self,
        actor: AuthContext,
        *,
        connector_key: str,
        owner_type: str = OWNER_TENANT,
        integration_connection_id: UUID | None = None,
    ) -> AuthorizationStart:
        """Build the consent URL for one caller, one connector, one ownership."""

        if actor.tenant_id is None:
            raise AuthorizationError("an active workspace membership is required")
        provider = self._provider(connector_key)
        verifier, challenge = pkce_pair()
        pending = PendingAuthorization(
            tenant_id=str(actor.tenant_id),
            user_id=str(actor.user_id),
            provider_key=provider.definition.key,
            connector_key=connector_key.strip().casefold(),
            owner_type=owner_type,
            connection_id=(
                str(integration_connection_id)
                if integration_connection_id is not None
                else None
            ),
            code_verifier=verifier,
            nonce=secrets.token_urlsafe(16),
        )
        try:
            state = self._state.issue(pending)
            return AuthorizationStart(
                authorization_url=provider.authorization_url(
                    state=state, code_challenge=challenge
                ),
                nonce=pending.nonce,
            )
        except IntegrationConfigurationError as exc:
            raise ControlPlaneExternalUnavailableError(str(exc)) from exc

    def read_state(self, state: str) -> CompletedAuthorization:
        """Recover the identity that started an authorization from its state."""

        try:
            pending = self._state.read(state)
        except IntegrationConfigurationError as exc:
            raise ControlPlaneExternalUnavailableError(str(exc)) from exc
        except IntegrationAuthorizationError as exc:
            raise ControlPlaneValidationError(str(exc)) from exc
        try:
            return CompletedAuthorization(
                pending=pending,
                tenant_id=UUID(pending.tenant_id),
                user_id=UUID(pending.user_id),
                connection_id=(
                    UUID(pending.connection_id) if pending.connection_id else None
                ),
            )
        except ValueError as exc:
            raise ControlPlaneValidationError("authorization state is invalid") from exc

    async def exchange(
        self, completed: CompletedAuthorization, *, code: str
    ) -> AuthorizationGrant:
        """Trade the provider's one-time code for a grant."""

        provider = self._provider(completed.pending.connector_key)
        if provider.definition.key != completed.pending.provider_key:
            raise ControlPlaneValidationError("authorization state does not match its provider")
        try:
            return await provider.exchange(
                code=code, code_verifier=completed.pending.code_verifier
            )
        except IntegrationConfigurationError as exc:
            raise ControlPlaneExternalUnavailableError(str(exc)) from exc
        except IntegrationAuthorizationError as exc:
            raise ControlPlaneValidationError(str(exc)) from exc
        except IntegrationError as exc:
            raise ControlPlaneExternalUnavailableError(str(exc)) from exc

    def _provider(self, connector_key: str) -> ConnectionProvider:
        provider = self._providers.for_connector(connector_key)
        if provider is None:
            raise ControlPlaneValidationError(
                f"{connector_key} is not connected by authorizing an account"
            )
        if not provider.configured:
            raise ControlPlaneExternalUnavailableError(
                f"{provider.definition.display_name} authorization is not configured "
                "in this deployment"
            )
        return provider


__all__ = ["IntegrationAuthorizationService"]
