"""The whole connector authorization flow, against a real database.

Only the provider's HTTP endpoints are replaced. Everything else — the signed
state, the token exchange, the encrypted credential, the connection record, the
resource picker's discovery, and the source it produces — is the code that runs
in production, so this covers the seam the unit tests cannot: that a completed
Atlassian consent actually becomes a Confluence source pointed at a collection.
"""

from __future__ import annotations

import base64
import os
from collections.abc import AsyncIterator
from typing import Any
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from bothesis.db.models import Base, IngestionSource, IntegrationConnection, Item
from bothesis.integrations.atlassian import AtlassianConnectionProvider
from bothesis.integrations.oauth_state import OAuthStateCodec
from bothesis.integrations.registry import ConnectionProviderRegistry
from bothesis.services import (
    ControlPlaneConflictError,
    ControlPlaneNotFoundError,
    ControlPlaneValidationError,
    AuthContext,
    AuthorizationError,
    ConnectionAuthorizationRequiredError,
)
from bothesis.services.identity_access.identity_store import IdentityStoreService
from bothesis.services.identity_access.role_assignments import RoleAssignmentService
from bothesis.services.ingestion_sources import IngestionSourceService
from bothesis.services.integration_authorization import (
    IntegrationAuthorizationService,
)
from bothesis.services.integration_connections import IntegrationConnectionService
from bothesis.services.integration_credential import IntegrationCredentialService

TEST_DATABASE_URL = os.getenv("TEST_DATABASE_URL")

pytestmark = pytest.mark.skipif(
    not TEST_DATABASE_URL,
    reason="TEST_DATABASE_URL is required for PostgreSQL connection-flow tests",
)

ENCRYPTION_KEY = base64.urlsafe_b64encode(b"k" * 32).decode().rstrip("=")
STATE_SECRET = "connection-flow-test-state-secret"
CLOUD_ID = "11111111-aaaa-bbbb-cccc-222222222222"
ACCOUNT_ID = "557058:abcdef"


@pytest_asyncio.fixture
async def session_factory() -> AsyncIterator[async_sessionmaker[AsyncSession]]:
    assert TEST_DATABASE_URL is not None
    schema = f"test_connections_{uuid4().hex}"
    admin_engine = create_async_engine(TEST_DATABASE_URL)
    async with admin_engine.begin() as connection:
        await connection.execute(text(f'CREATE SCHEMA "{schema}"'))

    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"server_settings": {"search_path": schema}},
    )
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)

    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory.begin() as session:
        await IdentityStoreService(session).sync_system_roles()

    try:
        yield factory
    finally:
        await engine.dispose()
        async with admin_engine.begin() as connection:
            await connection.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        await admin_engine.dispose()


class FakeAtlassian:
    """Atlassian's endpoints, answering the way the documented API does."""

    def __init__(self) -> None:
        self.issued_refresh_tokens = ["refresh-1"]
        self.exchanges = 0
        self.spaces = [
            {"id": "1", "key": "ENG", "name": "Engineering"},
            {"id": "2", "key": "DATA", "name": "Data Platform"},
            {"id": "3", "key": "HR", "name": "People"},
        ]

    def handler(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if url.endswith("/oauth/token"):
            self.exchanges += 1
            # Atlassian rotates the refresh token on every use.
            issued = f"refresh-{len(self.issued_refresh_tokens) + 1}"
            self.issued_refresh_tokens.append(issued)
            return httpx.Response(
                200,
                json={
                    "access_token": f"access-{self.exchanges}",
                    "refresh_token": issued,
                    "expires_in": 3600,
                    "scope": "read:confluence-content.all offline_access",
                },
            )
        if url.endswith("/oauth/token/accessible-resources"):
            return httpx.Response(
                200,
                json=[
                    {
                        "id": CLOUD_ID,
                        "url": "https://galaxyfinx.atlassian.net",
                        "name": "Galaxy FinX",
                    }
                ],
            )
        if url.endswith("/me"):
            return httpx.Response(
                200,
                json={
                    "account_id": ACCOUNT_ID,
                    "email": "duy@company.com",
                    "name": "Duy",
                },
            )
        if "/wiki/api/v2/spaces" in url:
            return httpx.Response(200, json={"results": self.spaces, "_links": {}})
        return httpx.Response(404, json={"message": f"unexpected call: {url}"})


@pytest.fixture
def atlassian(monkeypatch: pytest.MonkeyPatch) -> FakeAtlassian:
    fake = FakeAtlassian()
    original = httpx.AsyncClient.__init__

    def patched(self: httpx.AsyncClient, *args: Any, **kwargs: Any) -> None:
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        original(self, *args, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "__init__", patched)
    return fake


def _providers() -> ConnectionProviderRegistry:
    return ConnectionProviderRegistry(
        (
            AtlassianConnectionProvider(
                client_id="client",
                client_secret="secret",
                redirect_uri="https://api.example/callback",
            ),
        )
    )


def _connections(session: AsyncSession) -> IntegrationConnectionService:
    return IntegrationConnectionService(
        session, providers=_providers(), credential_encryption_key=ENCRYPTION_KEY
    )


def _sources(session: AsyncSession) -> IngestionSourceService:
    return IngestionSourceService(
        session, providers=_providers(), credential_encryption_key=ENCRYPTION_KEY
    )


def _authorization() -> IntegrationAuthorizationService:
    return IntegrationAuthorizationService(
        _providers(),
        state=OAuthStateCodec(STATE_SECRET),
        client_origin="https://app.example",
    )


async def _workspace(
    session: AsyncSession, *, permissions: tuple[str, ...] = ("source.manage",)
) -> tuple[AuthContext, Item]:
    """One tenant, one member with the given permissions, one collection."""

    identities = IdentityStoreService(session)
    tenant = await identities.create_tenant(f"acme-{uuid4().hex[:8]}", "Acme")
    user = await identities.create_user(f"{uuid4().hex[:8]}@example.com")
    role = await identities.create_role(
        tenant.id, "manager", "Manager", permission_codes=list(permissions)
    )
    await identities.assign_membership(user.id, tenant.id)
    await RoleAssignmentService(session).replace_tenant_roles(
        user_id=user.id, tenant_id=tenant.id, role_ids=[role.id]
    )
    collection = Item(
        tenant_id=tenant.id,
        item_type="collection",
        title="Engineering knowledge",
        status="ready",
        created_by_user_id=user.id,
    )
    session.add(collection)
    await session.flush()
    return await identities.get_context(user.id, tenant_id=tenant.id), collection


async def _authorize(
    session: AsyncSession, actor: AuthContext, *, owner_type: str = "tenant"
) -> dict[str, Any]:
    """Run one complete consent round trip and return the stored connection."""

    service = _authorization()
    started = service.start(actor, connector_key="confluence", owner_type=owner_type)
    state = _state_from(started.authorization_url)
    completed = service.read_state(state)
    grant = await service.exchange(completed, code="provider-code")
    return await _connections(session).record_authorization(
        actor,
        connector_key=completed.pending.connector_key,
        grant=grant,
        owner_type=completed.pending.owner_type,
        integration_connection_id=completed.connection_id,
    )


def _state_from(authorization_url: str) -> str:
    from urllib.parse import parse_qs, urlsplit

    return parse_qs(urlsplit(authorization_url).query)["state"][0]


@pytest.mark.asyncio
async def test_a_completed_consent_becomes_a_usable_connection(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        actor, _ = await _workspace(session)

        connection = await _authorize(session, actor)

        assert connection["status"] == "connected"
        assert connection["account"]["label"] == "duy@company.com"
        assert connection["account"]["resource_label"] == "Galaxy FinX"
        assert connection["credential_configured"] is True
        assert "offline_access" in connection["scopes"]
        # The grant is bound to one site, so the site's API base is a fact about
        # the connection rather than about the provider or any single source.
        assert connection["config"]["wiki_base"].endswith(
            f"/ex/confluence/{CLOUD_ID}/wiki"
        )
        assert connection["expires_at"] is not None


@pytest.mark.asyncio
async def test_the_secret_is_encrypted_and_never_in_the_connection(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        actor, _ = await _workspace(session)
        connection = await _authorize(session, actor)
        connection_id = UUID(connection["id"])

        stored = await IntegrationCredentialService(session, ENCRYPTION_KEY).resolve(
            connection_id
        )
        record = await session.get(IntegrationConnection, connection_id)

        assert stored["access_token"] == "access-1"
        assert stored["cloud_id"] == CLOUD_ID
        # Nothing secret may reach the row the API serialises.
        assert "access-1" not in str(record.config)
        assert "access-1" not in str(connection)
        assert "refresh" not in str(connection).lower()


@pytest.mark.asyncio
async def test_authorizing_the_same_account_twice_reuses_one_connection(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    """Reconnecting must not orphan the sources already built on the account."""

    async with session_factory.begin() as session:
        actor, collection = await _workspace(session)
        first = await _authorize(session, actor)
        await _sources(session).create_source(
            actor,
            UUID(first["id"]),
            target_item_id=collection.id,
            display_name="Engineering",
            resource_type="space",
            external_resource_id="ENG",
        )

        second = await _authorize(session, actor)

        assert second["id"] == first["id"]
        assert second["source_count"] == 1
        listed = await _connections(session).list_connections(actor)
        assert listed["total"] == 1


@pytest.mark.asyncio
async def test_discovery_offers_the_spaces_the_account_can_read(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        actor, _ = await _workspace(session)
        connection = await _authorize(session, actor)

        page = await _connections(session).list_resources(
            actor, UUID(connection["id"])
        )
        filtered = await _connections(session).list_resources(
            actor, UUID(connection["id"]), search="data"
        )

        assert [item["external_id"] for item in page["resources"]] == [
            "ENG",
            "DATA",
            "HR",
        ]
        assert all(item["resource_type"] == "space" for item in page["resources"])
        assert [item["external_id"] for item in filtered["resources"]] == ["DATA"]


@pytest.mark.asyncio
async def test_a_selected_space_becomes_a_source_the_connector_can_run(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    """The picker names a space; the provider turns it into connector config."""

    async with session_factory.begin() as session:
        actor, collection = await _workspace(session)
        connection = await _authorize(session, actor)

        source = await _sources(session).create_source(
            actor,
            UUID(connection["id"]),
            target_item_id=collection.id,
            display_name="Data Platform",
            resource_type="space",
            external_resource_id="DATA",
            sync_mode="scheduled",
        )

        assert source["config"] == {"space": "DATA"}
        assert source["status"] == "ready"
        assert source["sync_mode"] == "scheduled"
        assert source["target_item_id"] == str(collection.id)
        assert source["integration_connection"]["account_label"] == "duy@company.com"


@pytest.mark.asyncio
async def test_one_connection_feeds_many_spaces_without_reauthorizing(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        actor, collection = await _workspace(session)
        connection = await _authorize(session, actor)
        exchanges_after_connect = atlassian.exchanges

        for space in ("ENG", "DATA", "HR"):
            await _sources(session).create_source(
                actor,
                UUID(connection["id"]),
                target_item_id=collection.id,
                display_name=space,
                resource_type="space",
                external_resource_id=space,
            )

        listed = await _sources(session).list_sources(actor)
        assert listed["total"] == 3
        # Adding content must not cost another consent screen.
        assert atlassian.exchanges == exchanges_after_connect


@pytest.mark.asyncio
async def test_disconnecting_stops_the_sources_and_reconnecting_resumes_them(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        actor, collection = await _workspace(session)
        connection = await _authorize(session, actor)
        connection_id = UUID(connection["id"])
        source = await _sources(session).create_source(
            actor,
            connection_id,
            target_item_id=collection.id,
            display_name="Engineering",
            resource_type="space",
            external_resource_id="ENG",
        )

        disconnected = await _connections(session).disconnect_connection(
            actor, connection_id
        )
        stopped = await _sources(session).get_source(actor, UUID(source["id"]))

        assert disconnected["status"] == "disconnected"
        assert disconnected["credential_configured"] is False
        assert stopped["status"] == "connection_required"
        assert stopped["status_detail"]

        # The secret is destroyed, not merely marked gone.
        with pytest.raises(LookupError):
            await IntegrationCredentialService(session, ENCRYPTION_KEY).resolve(
                connection_id
            )

        reconnected = await _authorize(session, actor)
        resumed = await _sources(session).get_source(actor, UUID(source["id"]))

        assert reconnected["id"] == str(connection_id)
        assert reconnected["status"] == "connected"
        assert resumed["status"] == "ready"


@pytest.mark.asyncio
async def test_a_source_cannot_run_while_its_connection_is_disconnected(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    """The worker must refuse rather than fail halfway through a sync."""

    async with session_factory.begin() as session:
        actor, collection = await _workspace(session)
        connection = await _authorize(session, actor)
        source = await _sources(session).create_source(
            actor,
            UUID(connection["id"]),
            target_item_id=collection.id,
            display_name="Engineering",
            resource_type="space",
            external_resource_id="ENG",
        )
        await _connections(session).disconnect_connection(
            actor, UUID(connection["id"])
        )

        with pytest.raises(ControlPlaneNotFoundError, match="runnable ingestion source"):
            await _sources(session).runtime_for_source(UUID(source["id"]))


@pytest.mark.asyncio
async def test_a_member_cannot_connect_an_account_for_the_whole_workspace(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        actor, _ = await _workspace(session, permissions=("knowledge.read",))

        with pytest.raises(AuthorizationError, match="source.manage"):
            await _authorize(session, actor, owner_type="tenant")


@pytest.mark.asyncio
async def test_a_member_may_connect_their_own_account(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    """A personal connection acts as one person and is nobody else's business."""

    async with session_factory.begin() as session:
        actor, _ = await _workspace(session, permissions=("knowledge.read",))

        connection = await _authorize(session, actor, owner_type="user")

        assert connection["owner_type"] == "user"
        assert connection["owner_user_id"] == str(actor.user_id)
        assert (await _connections(session).list_connections(actor))["total"] == 1


@pytest.mark.asyncio
async def test_one_persons_connection_is_invisible_to_another(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        owner, _ = await _workspace(session, permissions=("knowledge.read",))
        connection = await _authorize(session, owner, owner_type="user")

        identities = IdentityStoreService(session)
        other = await identities.create_user(f"{uuid4().hex[:8]}@example.com")
        role = await identities.create_role(
            owner.tenant_id, "source-admin", "Source Admin",
            permission_codes=["source.manage"],
        )
        await identities.assign_membership(other.id, owner.tenant_id)
        await RoleAssignmentService(session).replace_tenant_roles(
            user_id=other.id, tenant_id=owner.tenant_id, role_ids=[role.id]
        )
        intruder = await identities.get_context(other.id, tenant_id=owner.tenant_id)

        # Even a source manager does not inherit someone else's personal account.
        assert (await _connections(session).list_connections(intruder))["total"] == 0
        with pytest.raises(ControlPlaneNotFoundError):
            await _connections(session).get_connection(
                intruder, UUID(connection["id"])
            )


@pytest.mark.asyncio
async def test_a_connection_from_another_workspace_is_not_reachable(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        first, _ = await _workspace(session)
        second, _ = await _workspace(session)
        connection = await _authorize(session, first)

        with pytest.raises(ControlPlaneNotFoundError):
            await _connections(session).get_connection(second, UUID(connection["id"]))
        assert (await _connections(session).list_connections(second))["total"] == 0


@pytest.mark.asyncio
async def test_the_same_space_cannot_be_synchronized_twice(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        actor, collection = await _workspace(session)
        connection = await _authorize(session, actor)
        for _ in range(1):
            await _sources(session).create_source(
                actor,
                UUID(connection["id"]),
                target_item_id=collection.id,
                display_name="Engineering",
                resource_type="space",
                external_resource_id="ENG",
            )

        with pytest.raises(ControlPlaneConflictError, match="already synchronized"):
            await _sources(session).create_source(
                actor,
                UUID(connection["id"]),
                target_item_id=collection.id,
                display_name="Engineering again",
                resource_type="space",
                external_resource_id="ENG",
            )


@pytest.mark.asyncio
async def test_a_lapsed_grant_reports_that_someone_must_reconnect(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    """A revoked account must not read as a transient outage."""

    async with session_factory.begin() as session:
        actor, _ = await _workspace(session)
        connection = await _authorize(session, actor)
        connection_id = UUID(connection["id"])
        await _connections(session).disconnect_connection(actor, connection_id)

        with pytest.raises(ConnectionAuthorizationRequiredError):
            await _connections(session).list_resources(actor, connection_id)


@pytest.mark.asyncio
async def test_state_from_another_deployment_is_refused(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    async with session_factory.begin() as session:
        actor, _ = await _workspace(session)
        forged = IntegrationAuthorizationService(
            _providers(),
            state=OAuthStateCodec("a-different-deployment-secret"),
            client_origin="https://app.example",
        ).start(actor, connector_key="confluence", owner_type="tenant")

        with pytest.raises(ControlPlaneValidationError, match="invalid"):
            _authorization().read_state(_state_from(forged.authorization_url))


@pytest.mark.asyncio
async def test_removing_a_connection_keeps_its_indexed_items(
    session_factory: async_sessionmaker[AsyncSession], atlassian: FakeAtlassian
) -> None:
    """Documents already answered from stay searchable; lineage is not deleted."""

    async with session_factory.begin() as session:
        actor, collection = await _workspace(session)
        connection = await _authorize(session, actor)
        source = await _sources(session).create_source(
            actor,
            UUID(connection["id"]),
            target_item_id=collection.id,
            display_name="Engineering",
            resource_type="space",
            external_resource_id="ENG",
        )

        await _connections(session).delete_connection(actor, UUID(connection["id"]))

        stored_source = await session.get(IngestionSource, UUID(source["id"]))
        stored_collection = await session.get(Item, collection.id)
        stored_connection = await session.get(
            IntegrationConnection, UUID(connection["id"])
        )

        # Tombstoned, never erased.
        assert stored_connection is not None
        assert stored_connection.deleted_at is not None
        assert stored_source is not None
        assert stored_source.deleted_at is not None
        assert stored_collection is not None
        assert stored_collection.deleted_at is None
