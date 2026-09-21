"""The Connection resource: one authorized external account, reused by sources.

A Connection answers *whose access is this and is it still good*. It never
knows which documents are indexed, and it carries no provider branch: anything
specific to Google or Atlassian lives behind the ``ConnectionProvider`` this
service resolves from the registry.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, NoReturn
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import joinedload, selectinload

from bothesis.connector import ConnectorDefinition
from bothesis.connector.registry import ConnectorRegistry
from bothesis.db.models import IngestionSource, IntegrationConnection
from bothesis.integrations import (
    AuthorizationGrant,
    IntegrationAuthorizationError,
    IntegrationConfigurationError,
    IntegrationError,
    ProviderCredentials,
    ProviderResource,
)
from bothesis.integrations.registry import ConnectionProviderRegistry
from bothesis.services import (
    CONNECTION_CONNECTED,
    CONNECTION_DISCONNECTED,
    CONNECTION_DRAFT,
    CONNECTION_EXPIRED,
    CONNECTION_NEEDS_AUTHORIZATION,
    CONNECTION_REAUTH_REQUIRED,
    CONNECTION_STATUSES,
    OWNER_TENANT,
    OWNER_TYPES,
    OWNER_USER,
    SOURCE_CONNECTION_REQUIRED,
    SOURCE_MANAGE_PERMISSION,
    SOURCE_READY,
    ControlPlaneConflictError,
    ControlPlaneExternalUnavailableError,
    ControlPlaneNotFoundError,
    ControlPlaneValidationError,
    AuthContext,
    AuthorizationError,
    ConnectionAuthorizationRequiredError,
    normalize_page,
    normalize_required_text,
    timestamp,
)
from bothesis.services.audit import AuditService
from bothesis.services.integration_credential import (
    CLEARED_PAYLOAD,
    IntegrationCredentialService,
)

_SECRET_KEY_TERMS = {
    "access_key",
    "api_key",
    "authorization",
    "password",
    "secret",
    "token",
}
#: Refresh this far ahead of expiry so a long sync does not start on a token
#: that dies mid-run.
_REFRESH_MARGIN = timedelta(minutes=5)


class IntegrationConnectionService:
    """Own Connection state: ownership, credentials, health, and discovery."""

    def __init__(
        self,
        session: AsyncSession,
        *,
        providers: ConnectionProviderRegistry | None = None,
        registry: ConnectorRegistry | None = None,
        credential_encryption_key: str | None = None,
        audit: AuditService | None = None,
    ) -> None:
        self._session = session
        self._providers = providers or ConnectionProviderRegistry()
        self._registry = registry or ConnectorRegistry.default()
        self._credential_encryption_key = credential_encryption_key
        self._audit = audit or AuditService(session)

    # -- Catalogue ----------------------------------------------------------

    async def capabilities(self, actor: AuthContext) -> dict[str, Any]:
        """What this deployment can connect, and how each one is authorized."""

        _require_tenant(actor)
        connectors = []
        for definition in self._registry.list():
            provider = self._providers.for_connector(definition.key)
            # A connector can offer both paths. Confluence Cloud is best
            # authorized through Atlassian, but Server and Data Center have no
            # such flow at all, so the API token stays a first-class option and
            # is what an unconfigured deployment is left with.
            connectors.append(
                {
                    "connector_key": definition.key,
                    "display_name": definition.display_name,
                    "authentication_type": definition.authentication_type,
                    "capabilities": list(definition.capabilities),
                    "accepts_credentials": definition.authentication_type
                    in {"credentials", "none"},
                    "provider_key": (
                        provider.definition.key if provider is not None else None
                    ),
                    "provider_display_name": (
                        provider.definition.display_name
                        if provider is not None
                        else None
                    ),
                    # What one authorization of this provider can feed. Atlassian
                    # is the reason this is a list: Confluence is a capability of
                    # the account, not an integration of its own.
                    "provider_capabilities": (
                        [
                            {
                                "connector_key": item.connector_key,
                                "display_name": item.display_name,
                                "resource_type": item.resource_type,
                            }
                            for item in provider.definition.capabilities
                        ]
                        if provider is not None
                        else []
                    ),
                    # Registered but unconfigured is a different answer from
                    # unsupported, and the page that offers the button needs it.
                    "authorization_available": provider is not None
                    and provider.configured,
                    "available": definition.authentication_type != "oauth"
                    or (provider is not None and provider.configured),
                }
            )
        return {"connectors": connectors}

    # -- Reads --------------------------------------------------------------

    async def list_connections(
        self,
        actor: AuthContext,
        *,
        page: int = 1,
        page_size: int = 20,
        connector_key: str | None = None,
        status: str | None = None,
        owner_type: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        tenant_id = _require_tenant(actor)
        page, page_size, offset = normalize_page(page, page_size)
        filters: list[Any] = [
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.deleted_at.is_(None),
            self.visibility(actor),
        ]
        if connector_key:
            filters.append(
                IntegrationConnection.connector_key == connector_key.strip().casefold()
            )
        if status:
            filters.append(IntegrationConnection.status == _valid_status(status))
        if owner_type:
            filters.append(IntegrationConnection.owner_type == _valid_owner(owner_type))
        if search and search.strip():
            term = f"%{search.strip()}%"
            filters.append(
                or_(
                    IntegrationConnection.display_name.ilike(term),
                    IntegrationConnection.connector_key.ilike(term),
                    IntegrationConnection.provider_account_label.ilike(term),
                )
            )
        total = await self._session.scalar(
            select(func.count()).select_from(
                select(IntegrationConnection.id).where(*filters).subquery()
            )
        )
        connections = list(
            await self._session.scalars(
                select(IntegrationConnection)
                .options(
                    selectinload(IntegrationConnection.ingestion_sources),
                    joinedload(IntegrationConnection.credential),
                )
                .where(*filters)
                .order_by(IntegrationConnection.display_name, IntegrationConnection.id)
                .limit(page_size)
                .offset(offset)
            )
        )
        return {
            "items": [self._payload(value) for value in connections],
            "total": int(total or 0),
            "page": page,
            "page_size": page_size,
        }

    async def get_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        return self._payload(
            await self._readable(actor, integration_connection_id, loaded=True)
        )

    # -- Writes -------------------------------------------------------------

    async def create_connection(
        self,
        actor: AuthContext,
        *,
        connector_key: str,
        display_name: str,
        config: Mapping[str, Any],
        credentials: Mapping[str, Any] | None = None,
        credential_type: str | None = None,
        owner_type: str = OWNER_TENANT,
    ) -> dict[str, Any]:
        """Create a connection that is configured with a secret, not authorized.

        Providers with an authorization flow are never reached this way: their
        connections only ever come from a completed grant, so a token cannot be
        pasted past the consent screen.
        """

        tenant_id = _require_tenant(actor)
        normalized_key = normalize_required_text(
            connector_key, "connector key", 64
        ).casefold()
        definition = self._definition(normalized_key)
        normalized_owner = _valid_owner(owner_type)
        _require_owner_permission(actor, normalized_owner)
        if definition.authentication_type == "oauth":
            raise ControlPlaneValidationError(
                f"{definition.display_name} is connected by authorizing an account, "
                "not by entering a credential"
            )
        if definition.authentication_type != "none" and not credentials:
            raise ControlPlaneValidationError(
                f"{definition.display_name} credentials are required"
            )
        connection = IntegrationConnection(
            tenant_id=tenant_id,
            connector_key=normalized_key,
            owner_type=normalized_owner,
            owner_user_id=actor.user_id if normalized_owner == OWNER_USER else None,
            display_name=await self._available_name(tenant_id, display_name),
            config=self.non_secret_config(config),
            status=CONNECTION_DRAFT,
            created_by_user_id=actor.user_id,
        )
        self._session.add(connection)
        await self._session.flush()
        if credentials:
            await self._credentials().store(
                connection.id,
                credential_type=credential_type or normalized_key,
                payload=credentials,
            )
            connection.connected_at = datetime.now(UTC)
        await self._audit.record(
            actor,
            action="integration.connection.created",
            resource_type="integration_connection",
            resource_id=str(connection.id),
            details={"connector_key": normalized_key, "owner_type": normalized_owner},
        )
        return await self.get_connection(actor, connection.id)

    async def record_authorization(
        self,
        actor: AuthContext,
        *,
        connector_key: str,
        grant: AuthorizationGrant,
        owner_type: str,
        integration_connection_id: UUID | None = None,
    ) -> dict[str, Any]:
        """Turn a completed grant into the one Connection it belongs to.

        Authorizing the same provider account twice reuses the existing record
        rather than adding a second one, so every source built on it keeps
        working and a reconnection is indistinguishable from the first connect.
        """

        tenant_id = _require_tenant(actor)
        normalized_key = normalize_required_text(
            connector_key, "connector key", 64
        ).casefold()
        self._definition(normalized_key)
        normalized_owner = _valid_owner(owner_type)
        _require_owner_permission(actor, normalized_owner)
        connection = (
            await self._writable(actor, integration_connection_id)
            if integration_connection_id is not None
            else await self._by_provider_account(
                tenant_id,
                connector_key=normalized_key,
                owner_type=normalized_owner,
                owner_user_id=actor.user_id if normalized_owner == OWNER_USER else None,
                account=grant.account,
            )
        )
        now = datetime.now(UTC)
        if connection is None:
            connection = IntegrationConnection(
                tenant_id=tenant_id,
                connector_key=normalized_key,
                owner_type=normalized_owner,
                owner_user_id=(
                    actor.user_id if normalized_owner == OWNER_USER else None
                ),
                display_name=await self._available_name(
                    tenant_id, _grant_name(normalized_key, grant)
                ),
                created_by_user_id=actor.user_id,
            )
            self._session.add(connection)
        connection.provider_account_id = grant.account.account_id
        connection.provider_account_label = grant.account.label
        connection.provider_resource_id = grant.account.resource_id
        connection.provider_resource_label = grant.account.resource_label
        connection.scopes = list(grant.scopes)
        connection.config = self.non_secret_config(
            {**dict(connection.config or {}), **dict(grant.config)}
        )
        connection.status = CONNECTION_CONNECTED
        connection.status_detail = None
        connection.expires_at = grant.credentials.expires_at
        connection.connected_at = now
        connection.disconnected_at = None
        connection.last_checked_at = now
        await self._session.flush()
        await self._credentials().store(
            connection.id,
            credential_type=f"{normalized_key}_oauth",
            payload=grant.credentials.values,
            expires_at=grant.credentials.expires_at,
        )
        await self._restore_sources(connection.id)
        await self._audit.record(
            actor,
            action="integration.connection.authorized",
            resource_type="integration_connection",
            resource_id=str(connection.id),
            details={
                "connector_key": normalized_key,
                "owner_type": normalized_owner,
                "provider_account": grant.account.label,
            },
        )
        return await self.get_connection(actor, connection.id)

    async def update_connection(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        *,
        display_name: str | None = None,
        config: Mapping[str, Any] | None = None,
        credentials: Mapping[str, Any] | None = None,
        credential_type: str | None = None,
    ) -> dict[str, Any]:
        connection = await self._writable(actor, integration_connection_id)
        if connection is None:
            raise ControlPlaneNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        if display_name is not None:
            connection.display_name = await self._available_name(
                connection.tenant_id, display_name, excluding=connection.id
            )
        if config is not None:
            connection.config = self.non_secret_config(config)
        if credentials is not None:
            # An authorized connection is identified by its provider account;
            # renewing it means authorizing again, not pasting a secret over it.
            if connection.provider_account_id is not None:
                raise ControlPlaneValidationError(
                    "an authorized connection is renewed by authorizing again"
                )
            await self._credentials().store(
                connection.id,
                credential_type=credential_type or connection.connector_key,
                payload=credentials,
            )
            connection.status = CONNECTION_DRAFT
            connection.status_detail = None
        await self._session.flush()
        await self._audit.record(
            actor,
            action="integration.connection.updated",
            resource_type="integration_connection",
            resource_id=str(connection.id),
        )
        return await self.get_connection(actor, connection.id)

    async def disconnect_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        """Revoke the grant and forget the secret, keeping the record and sources.

        Disconnecting is reversible by design: the sources built on this
        connection stay, stop running, and say why, so reconnecting the same
        account resumes them instead of asking anyone to rebuild them.
        """

        connection = await self._writable(actor, integration_connection_id)
        if connection is None:
            raise ControlPlaneNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        provider = self._providers.for_connector(connection.connector_key)
        if provider is not None:
            stored = await self._stored_credentials(connection)
            if stored is not None:
                try:
                    await provider.revoke(stored)
                except IntegrationError:
                    # The grant may already be gone. Forgetting the local secret
                    # is the part this deployment controls, and it still happens.
                    pass
        await self._credentials().clear(connection.id)
        now = datetime.now(UTC)
        connection.status = CONNECTION_DISCONNECTED
        connection.status_detail = "Disconnected from BoThesis"
        connection.expires_at = None
        connection.disconnected_at = now
        connection.last_checked_at = now
        await self._suspend_sources(connection.id, "The account was disconnected")
        await self._session.flush()
        await self._audit.record(
            actor,
            action="integration.connection.disconnected",
            resource_type="integration_connection",
            resource_id=str(connection.id),
        )
        return await self.get_connection(actor, connection.id)

    async def delete_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> None:
        connection = await self._writable(actor, integration_connection_id)
        if connection is None:
            raise ControlPlaneNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        await self.disconnect_connection(actor, connection.id)
        now = datetime.now(UTC)
        for source in await self._active_sources(connection.id):
            source.deleted_at = now
        connection.deleted_at = now
        await self._session.flush()
        await self._audit.record(
            actor,
            action="integration.connection.deleted",
            resource_type="integration_connection",
            resource_id=str(connection.id),
        )

    async def validate_connection(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> dict[str, Any]:
        """Prove the stored grant still reaches the provider, and record it."""

        connection = await self._writable(actor, integration_connection_id)
        if connection is None:
            raise ControlPlaneNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        try:
            runtime = await self.runtime_for(connection, source_config={})
            connected = await runtime.test_connection()
        except ConnectionAuthorizationRequiredError:
            raise
        except ControlPlaneValidationError:
            raise
        except Exception as exc:
            # The caller records the unhealthy state; raising here rolls this
            # transaction back, so writing it now would be writing it nowhere.
            raise ControlPlaneExternalUnavailableError(
                f"{connection.connector_key} connection validation failed: {exc}"
            ) from exc
        if not connected:
            raise ControlPlaneExternalUnavailableError(
                f"{connection.connector_key} connection validation failed: "
                "the provider rejected these credentials"
            )
        connection.status = CONNECTION_CONNECTED
        connection.status_detail = None
        connection.last_checked_at = datetime.now(UTC)
        await self._restore_sources(connection.id)
        await self._session.flush()
        await self._audit.record(
            actor,
            action="integration.connection.validated",
            resource_type="integration_connection",
            resource_id=str(connection.id),
        )
        return {"valid": True, "status": connection.status}

    # -- Discovery ----------------------------------------------------------

    async def list_resources(
        self,
        actor: AuthContext,
        integration_connection_id: UUID,
        *,
        connector_key: str | None = None,
        parent_id: str | None = None,
        search: str | None = None,
    ) -> dict[str, Any]:
        """What this authorized account can reach, for a resource picker."""

        connection = await self._readable(actor, integration_connection_id)
        provider = self._providers.for_connector(connection.connector_key)
        if provider is None:
            raise ControlPlaneValidationError(
                f"{connection.connector_key} cannot list resources"
            )
        if connection.provider_account_id is None:
            # Discovery asks the provider what an account can reach, so there
            # has to be an account. A connection configured with an API token
            # names its resource directly instead.
            raise ControlPlaneValidationError(
                f"{connection.display_name} was configured with a credential "
                "rather than an authorized account, so its resources cannot be "
                "listed"
            )
        capability = (connector_key or connection.connector_key).strip().casefold()
        if provider.definition.capability(capability) is None:
            raise ControlPlaneValidationError(
                f"{connection.display_name} does not provide {capability}"
            )
        credentials = await self._usable_credentials(connection)
        try:
            resources = await provider.list_resources(
                credentials,
                connector_key=capability,
                parent_id=parent_id,
                search=search,
            )
        except IntegrationAuthorizationError as exc:
            await self._require_reauthorization(connection, str(exc))
        except IntegrationError as exc:
            raise ControlPlaneExternalUnavailableError(str(exc)) from exc
        return {
            "connector_key": capability,
            "parent_id": parent_id,
            "resources": [
                {
                    "resource_type": resource.resource_type,
                    "external_id": resource.external_id,
                    "name": resource.name,
                    "parent_id": resource.parent_id,
                    "has_children": resource.has_children,
                    "url": resource.url,
                }
                for resource in resources
            ],
        }

    async def resource_source_config(
        self,
        connection: IntegrationConnection,
        *,
        resource_type: str,
        external_resource_id: str,
    ) -> dict[str, Any]:
        """Translate a selected resource into the config its source runs on."""

        provider = self._providers.for_connector(connection.connector_key)
        if provider is None:
            return {}
        return dict(
            provider.source_config(
                ProviderResource(
                    capability=connection.connector_key,
                    resource_type=resource_type,
                    external_id=external_resource_id,
                    name=external_resource_id,
                )
            )
        )

    # -- Runtime ------------------------------------------------------------

    async def runtime_for(
        self,
        connection: IntegrationConnection,
        *,
        source_config: Mapping[str, Any],
    ) -> Any:
        """Build the connector runtime for one connection and one source."""

        definition = self._definition(connection.connector_key)
        provider = self._providers.for_connector(connection.connector_key)
        credentials = await self._usable_credentials(connection)
        runtime_config = {
            **dict(connection.config),
            **(
                dict(provider.connector_runtime_config(connection.connector_key))
                if provider is not None
                else {}
            ),
            "_tenant_id": str(connection.tenant_id),
            "_integration_connection_id": str(connection.id),
            "connector_id": str(connection.id),
        }
        try:
            return definition.factory(
                runtime_config, source_config, dict(credentials.values)
            )
        except ValueError as exc:
            raise ControlPlaneValidationError(str(exc)) from exc

    async def persist_rotated_credentials(
        self, integration_connection_id: UUID, values: Mapping[str, Any]
    ) -> None:
        """Write back credentials a connector rotated while it was running.

        Without this a refresh token Google rotated mid-sync would be lost and
        the connection would need a person the next time it ran.
        """

        connection = await self._session.get(
            IntegrationConnection, integration_connection_id
        )
        if connection is None or connection.deleted_at is not None:
            return
        expires_at = _parse_timestamp(values.get("expires_at"))
        await self._credentials().store(
            connection.id,
            credential_type=f"{connection.connector_key}_oauth",
            payload=values,
            expires_at=expires_at,
        )
        connection.expires_at = expires_at
        await self._session.flush()

    # -- Shared helpers -----------------------------------------------------

    @staticmethod
    def non_secret_config(values: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(values, Mapping):
            raise ControlPlaneValidationError("integration config must be a JSON object")
        result = dict(values)
        for key, value in result.items():
            normalized_key = str(key).casefold()
            if any(term in normalized_key for term in _SECRET_KEY_TERMS):
                raise ControlPlaneValidationError(
                    "secret values must use Integration Credentials, not config"
                )
            if isinstance(value, Mapping):
                IntegrationConnectionService.non_secret_config(value)
        return result

    async def connection_for_authorization(
        self, actor: AuthContext, integration_connection_id: UUID
    ) -> IntegrationConnection:
        """Load a connection the caller may re-authorize."""

        connection = await self._writable(actor, integration_connection_id)
        if connection is None:
            raise ControlPlaneNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        return connection

    # -- Internals ----------------------------------------------------------

    def visibility(self, actor: AuthContext) -> Any:
        """Shared connections for a source manager; own personal ones always.

        Public because the Source service scopes its own reads through exactly
        this rule: a source is visible when its connection is.
        """

        own = IntegrationConnection.owner_user_id == actor.user_id
        if actor.has_permissions(SOURCE_MANAGE_PERMISSION):
            return or_(IntegrationConnection.owner_type == OWNER_TENANT, own)
        return own

    async def _readable(
        self, actor: AuthContext, integration_connection_id: UUID, *, loaded: bool = False
    ) -> IntegrationConnection:
        tenant_id = _require_tenant(actor)
        statement = select(IntegrationConnection).where(
            IntegrationConnection.id == integration_connection_id,
            IntegrationConnection.tenant_id == tenant_id,
            IntegrationConnection.deleted_at.is_(None),
            self.visibility(actor),
        )
        if loaded:
            statement = statement.options(
                selectinload(IntegrationConnection.ingestion_sources),
                joinedload(IntegrationConnection.credential),
            )
        connection = await self._session.scalar(statement)
        if connection is None:
            raise ControlPlaneNotFoundError(
                f"integration connection not found: {integration_connection_id}"
            )
        return connection

    async def _writable(
        self, actor: AuthContext, integration_connection_id: UUID | None
    ) -> IntegrationConnection | None:
        if integration_connection_id is None:
            return None
        connection = await self._readable(actor, integration_connection_id)
        _require_owner_permission(actor, connection.owner_type)
        if (
            connection.owner_type == OWNER_USER
            and connection.owner_user_id != actor.user_id
        ):
            raise AuthorizationError("a personal connection belongs to its owner")
        return connection

    async def _by_provider_account(
        self,
        tenant_id: UUID,
        *,
        connector_key: str,
        owner_type: str,
        owner_user_id: UUID | None,
        account: Any,
    ) -> IntegrationConnection | None:
        if not account.account_id:
            return None
        return await self._session.scalar(
            select(IntegrationConnection).where(
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.connector_key == connector_key,
                IntegrationConnection.owner_type == owner_type,
                IntegrationConnection.owner_user_id.is_(None)
                if owner_user_id is None
                else IntegrationConnection.owner_user_id == owner_user_id,
                IntegrationConnection.provider_account_id == account.account_id,
                IntegrationConnection.provider_resource_id.is_(None)
                if account.resource_id is None
                else IntegrationConnection.provider_resource_id == account.resource_id,
                IntegrationConnection.deleted_at.is_(None),
            )
        )

    async def _available_name(
        self, tenant_id: UUID, display_name: str, *, excluding: UUID | None = None
    ) -> str:
        """Keep the tenant-unique display name without failing a valid connect."""

        base = normalize_required_text(display_name, "connection display name", 255)
        for attempt in range(1, 20):
            candidate = base if attempt == 1 else f"{base[:248]} ({attempt})"
            filters = [
                IntegrationConnection.tenant_id == tenant_id,
                IntegrationConnection.display_name == candidate,
                IntegrationConnection.deleted_at.is_(None),
            ]
            if excluding is not None:
                filters.append(IntegrationConnection.id != excluding)
            if await self._session.scalar(
                select(IntegrationConnection.id).where(*filters)
            ) is None:
                return candidate
        raise ControlPlaneConflictError("connection display name already exists")

    def _definition(self, key: str) -> ConnectorDefinition:
        try:
            return self._registry.get(key)
        except LookupError as exc:
            raise ControlPlaneValidationError(str(exc)) from exc

    def _credentials(self) -> IntegrationCredentialService:
        if not self._credential_encryption_key:
            raise ControlPlaneExternalUnavailableError(
                "BOTHESIS_INTEGRATION_ENCRYPTION_KEY is not configured"
            )
        return IntegrationCredentialService(
            self._session, self._credential_encryption_key
        )

    async def _stored_credentials(
        self, connection: IntegrationConnection
    ) -> ProviderCredentials | None:
        try:
            record = await self._credentials().resolve(connection.id)
        except LookupError:
            return None
        return ProviderCredentials(values=record, expires_at=connection.expires_at)

    async def _usable_credentials(
        self, connection: IntegrationConnection
    ) -> ProviderCredentials:
        """Return credentials that will still work, refreshing them if needed."""

        definition = self._definition(connection.connector_key)
        if definition.authentication_type == "none":
            return ProviderCredentials(values={})
        if connection.status in CONNECTION_NEEDS_AUTHORIZATION:
            raise ConnectionAuthorizationRequiredError(
                f"{connection.display_name} must be connected again: "
                f"{connection.status_detail or connection.status}"
            )
        stored = await self._stored_credentials(connection)
        if stored is None:
            await self._require_reauthorization(
                connection, "no credential is stored for this connection"
            )
        provider = self._providers.for_connector(connection.connector_key)
        # Only a provider-authorized connection can be refreshed. A connection
        # configured with a long-lived API token has nothing to rotate, even
        # when its connector also has a provider registered.
        if (
            provider is None
            or connection.provider_account_id is None
            or not self._expiring(connection.expires_at)
        ):
            assert stored is not None
            return stored
        assert stored is not None
        try:
            refreshed = await provider.refresh(stored)
        except IntegrationAuthorizationError as exc:
            await self._require_reauthorization(connection, str(exc))
        except IntegrationConfigurationError as exc:
            raise ControlPlaneExternalUnavailableError(str(exc)) from exc
        except IntegrationError as exc:
            raise ControlPlaneExternalUnavailableError(str(exc)) from exc
        if refreshed is None:
            return stored
        await self._credentials().store(
            connection.id,
            credential_type=f"{connection.connector_key}_oauth",
            payload=refreshed.values,
            expires_at=refreshed.expires_at,
        )
        connection.expires_at = refreshed.expires_at
        connection.status = CONNECTION_CONNECTED
        connection.status_detail = None
        await self._session.flush()
        return refreshed

    async def _require_reauthorization(
        self, connection: IntegrationConnection, detail: str
    ) -> NoReturn:
        status = (
            CONNECTION_EXPIRED
            if self._expiring(connection.expires_at)
            else CONNECTION_REAUTH_REQUIRED
        )
        raise ConnectionAuthorizationRequiredError(
            f"{connection.display_name} must be connected again: {detail}",
            status=status,
            detail=detail,
        )

    async def record_health(
        self,
        integration_connection_id: UUID,
        *,
        status: str,
        detail: str,
    ) -> None:
        """Write down what a failed attempt discovered about a connection.

        Called from a transaction of its own after the one that failed rolled
        back, so the UI can offer a reconnect instead of rediscovering the same
        failure on every read.
        """

        connection = await self._session.get(
            IntegrationConnection, integration_connection_id
        )
        if connection is None or connection.deleted_at is not None:
            return
        connection.status = status
        connection.status_detail = detail[:1_000]
        connection.last_checked_at = datetime.now(UTC)
        if status in CONNECTION_NEEDS_AUTHORIZATION:
            await self._suspend_sources(connection.id, detail[:1_000])
        await self._session.flush()

    @staticmethod
    def _expiring(expires_at: datetime | None) -> bool:
        if expires_at is None:
            return False
        return expires_at <= datetime.now(UTC) + _REFRESH_MARGIN

    async def _active_sources(
        self, integration_connection_id: UUID
    ) -> list[IngestionSource]:
        return list(
            await self._session.scalars(
                select(IngestionSource).where(
                    IngestionSource.integration_connection_id
                    == integration_connection_id,
                    IngestionSource.deleted_at.is_(None),
                )
            )
        )

    async def _suspend_sources(
        self, integration_connection_id: UUID, detail: str
    ) -> None:
        """Make every dependent source say it is waiting on the connection."""

        for source in await self._active_sources(integration_connection_id):
            if source.status == SOURCE_READY:
                source.status = SOURCE_CONNECTION_REQUIRED
                source.status_detail = detail

    async def _restore_sources(self, integration_connection_id: UUID) -> None:
        for source in await self._active_sources(integration_connection_id):
            if source.status == SOURCE_CONNECTION_REQUIRED:
                source.status = SOURCE_READY
                source.status_detail = None

    @staticmethod
    def _payload(connection: IntegrationConnection) -> dict[str, Any]:
        sources = connection.__dict__.get("ingestion_sources", ())
        credential = connection.__dict__.get("credential")
        # A cleared credential is a record that a secret once existed, not a
        # secret. Reporting it as configured would say this connection works.
        has_credential = (
            credential is not None and credential.encrypted_payload != CLEARED_PAYLOAD
        )
        return {
            "id": str(connection.id),
            "tenant_id": str(connection.tenant_id),
            "connector_key": connection.connector_key,
            "display_name": connection.display_name,
            "account": {
                "id": connection.provider_account_id,
                "label": connection.provider_account_label,
                "resource_id": connection.provider_resource_id,
                "resource_label": connection.provider_resource_label,
            },
            "config": dict(connection.config),
            "scopes": list(connection.scopes or ()),
            "credential_configured": has_credential,
            "owner_type": connection.owner_type,
            "owner_user_id": (
                str(connection.owner_user_id) if connection.owner_user_id else None
            ),
            "status": connection.status,
            "status_detail": connection.status_detail,
            "source_count": len(
                [source for source in sources if source.deleted_at is None]
            ),
            "expires_at": timestamp(connection.expires_at),
            "connected_at": timestamp(connection.connected_at),
            "disconnected_at": timestamp(connection.disconnected_at),
            "last_checked_at": timestamp(connection.last_checked_at),
            "created_at": timestamp(connection.created_at),
            "updated_at": timestamp(connection.updated_at),
        }


def _require_tenant(actor: AuthContext) -> UUID:
    if actor.tenant_id is None:
        raise AuthorizationError("an active workspace membership is required")
    return actor.tenant_id


def _require_owner_permission(actor: AuthContext, owner_type: str) -> None:
    """Shared access is administered; a personal connection is the member's own."""

    if owner_type == OWNER_TENANT and not actor.has_permissions(
        SOURCE_MANAGE_PERMISSION
    ):
        raise AuthorizationError(
            f"missing required permissions: {SOURCE_MANAGE_PERMISSION}"
        )


def _valid_owner(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in OWNER_TYPES:
        raise ControlPlaneValidationError("connection owner_type must be user or tenant")
    return normalized


def _valid_status(value: str) -> str:
    normalized = value.strip().casefold()
    if normalized not in CONNECTION_STATUSES:
        raise ControlPlaneValidationError("unsupported connection status")
    return normalized


def _grant_name(connector_key: str, grant: AuthorizationGrant) -> str:
    label = grant.account.resource_label or grant.account.label or connector_key
    return f"{connector_key.replace('_', ' ').title()} — {label}"[:255]


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


__all__ = ["IntegrationConnectionService"]
