"""Provider-neutral contracts for authorizing an external account.

A *provider* owns one external identity system and nothing else: it builds an
authorization redirect, exchanges the code it returns, refreshes and revokes
the grant, lists what the grant can reach, and says which endpoints the
matching connector runtime needs. It never touches the database, the Item
lifecycle, or any BoThesis permission.

Business services depend on :class:`ConnectionProvider`, never on a concrete
provider, so an external integration-auth broker can replace these
implementations without reaching into connection, source, or ingestion code.
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Protocol, runtime_checkable

#: Ownership of a Connection. ``user`` acts as one person; ``tenant`` is the
#: shared workspace account whose knowledge every member may already query.
OwnerType = str

#: What a provider grant can be used for. A capability is the pairing of a
#: provider with one connector runtime, which is why Confluence and Jira can be
#: two capabilities of a single Atlassian authorization.
Capability = str


class IntegrationError(RuntimeError):
    """Base class for every failure raised out of a provider."""


class IntegrationConfigurationError(IntegrationError):
    """The deployment has not configured this provider's OAuth client."""


class IntegrationAuthorizationError(IntegrationError):
    """The provider refused the authorization, the code, or the token."""


class IntegrationUnavailableError(IntegrationError):
    """The provider could not be reached, or answered something unusable."""


@dataclass(frozen=True, slots=True)
class ProviderCapability:
    """One connector runtime an authorization can feed."""

    #: Matches a registered ``ConnectorDefinition.key``.
    connector_key: str
    display_name: str
    #: The resource kind a source of this capability selects.
    resource_type: str


@dataclass(frozen=True, slots=True)
class ProviderDefinition:
    """What a provider is, before any account has authorized it."""

    key: str
    display_name: str
    #: ``oauth`` providers own an authorization redirect; ``credentials``
    #: providers are configured by entering a secret directly.
    authorization_type: str
    capabilities: tuple[ProviderCapability, ...]
    #: Scopes requested at authorization time. Least privilege is a property of
    #: this list, so it is stated once, here.
    scopes: tuple[str, ...] = ()

    def capability(self, connector_key: str) -> ProviderCapability | None:
        key = connector_key.strip().casefold()
        return next(
            (item for item in self.capabilities if item.connector_key == key), None
        )


@dataclass(frozen=True, slots=True)
class ProviderAccount:
    """The external account an authorization resolved to."""

    #: The provider's stable identifier for the account.
    account_id: str
    #: Safe to display: an email address, a site host, a workspace name.
    label: str
    #: The bounded resource the grant covers, when a provider issues one grant
    #: per site or drive rather than one per account.
    resource_id: str | None = None
    resource_label: str | None = None


@dataclass(frozen=True, slots=True)
class ProviderCredentials:
    """Secret material for one connection, as the provider hands it over.

    ``values`` is written straight into the encrypted credential record and is
    never logged, returned from an API, or copied into connection config.
    """

    values: Mapping[str, Any] = field(repr=False)
    expires_at: datetime | None = None

    def merged(self, changes: Mapping[str, Any]) -> ProviderCredentials:
        return ProviderCredentials(
            values={**dict(self.values), **dict(changes)}, expires_at=self.expires_at
        )


@dataclass(frozen=True, slots=True)
class AuthorizationGrant:
    """A completed authorization, ready to become one stored Connection."""

    account: ProviderAccount
    credentials: ProviderCredentials
    scopes: tuple[str, ...] = ()
    #: Non-secret facts the grant established about this account, merged into
    #: the Connection's config. An Atlassian grant is bound to one site, so the
    #: API base for that site is a property of the connection, not of the
    #: provider or of any single source.
    config: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ProviderResource:
    """One thing an authorized account can reach, offered for selection.

    This is discovery output, not stored state: it becomes an Ingestion Source
    only when someone selects it.
    """

    capability: Capability
    resource_type: str
    external_id: str
    name: str
    #: Set when resources nest, so a picker can offer a folder's children.
    parent_id: str | None = None
    #: Whether this resource can itself contain further resources.
    has_children: bool = False
    url: str | None = None


@dataclass(frozen=True, slots=True)
class PendingAuthorization:
    """Everything an in-flight authorization must remember across the redirect.

    It travels inside the signed ``state`` parameter rather than a server-side
    table: the provider hands it back verbatim, and binding the caller's
    identity into it is what makes the callback safe to expose unauthenticated.
    """

    tenant_id: str
    user_id: str
    provider_key: str
    connector_key: str
    owner_type: OwnerType
    #: Set when re-authorizing an existing Connection instead of adding one.
    connection_id: str | None
    code_verifier: str = field(repr=False, default="")
    #: Opaque value echoed back to the browser so the opener can match it.
    nonce: str = ""


@runtime_checkable
class ConnectionProvider(Protocol):
    """Everything BoThesis needs from one external identity system."""

    @property
    def definition(self) -> ProviderDefinition: ...

    @property
    def configured(self) -> bool:
        """Whether this deployment can actually run this provider's flow."""

    def authorization_url(self, *, state: str, code_challenge: str) -> str:
        """Build the provider consent URL for one pending authorization."""

    async def exchange(
        self, *, code: str, code_verifier: str
    ) -> AuthorizationGrant: ...

    async def refresh(
        self, credentials: ProviderCredentials
    ) -> ProviderCredentials | None:
        """Return rotated credentials, or ``None`` when none were needed."""

    async def revoke(self, credentials: ProviderCredentials) -> None:
        """Ask the provider to invalidate the grant. Best effort."""

    async def list_resources(
        self,
        credentials: ProviderCredentials,
        *,
        connector_key: str,
        parent_id: str | None = None,
        search: str | None = None,
    ) -> tuple[ProviderResource, ...]: ...

    def connector_runtime_config(self, connector_key: str) -> Mapping[str, Any]:
        """Endpoints and client identifiers the connector runtime needs.

        Keeping this with the provider is what stops connector-specific
        branches from accumulating in the shared connection service.
        """

    def source_config(self, resource: ProviderResource) -> Mapping[str, Any]:
        """Translate one selected resource into Ingestion Source config."""


def pkce_pair() -> tuple[str, str]:
    """Return one ``(code_verifier, code_challenge)`` pair for S256 PKCE."""

    verifier = base64.urlsafe_b64encode(secrets.token_bytes(64)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


def expiry_from_seconds(
    expires_in: Any, *, now: datetime
) -> datetime | None:
    """Read an OAuth ``expires_in`` without trusting its type."""

    if isinstance(expires_in, bool) or not isinstance(expires_in, (int, float)):
        return None
    if expires_in <= 0:
        return None
    return now + timedelta(seconds=int(expires_in))


def granted_scopes(value: Any) -> tuple[str, ...]:
    """Normalize the space-delimited ``scope`` an OAuth response returns."""

    if isinstance(value, str):
        return tuple(part for part in value.split() if part)
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return tuple(str(part) for part in value if str(part))
    return ()


__all__ = [
    "AuthorizationGrant",
    "Capability",
    "ConnectionProvider",
    "IntegrationAuthorizationError",
    "IntegrationConfigurationError",
    "IntegrationError",
    "IntegrationUnavailableError",
    "OwnerType",
    "PendingAuthorization",
    "ProviderAccount",
    "ProviderCapability",
    "ProviderCredentials",
    "ProviderDefinition",
    "ProviderResource",
    "expiry_from_seconds",
    "granted_scopes",
    "pkce_pair",
]
