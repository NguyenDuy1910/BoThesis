from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from bothesis.db.engine import get_engine, get_session_factory
from bothesis.db.models import Base
from bothesis.services import AuthContext
from bothesis.services.identity_access.jwt_tokens import JwtTokenService
from bothesis.services.identity_access.passwords import PasswordCredentialService


EXPECTED_TABLES = {
    "access_sessions",
    "approval_requests",
    "artifact_revisions",
    "audit_logs",
    "auth_identities",
    "conversations",
    "citations",
    "group_memberships",
    "groups",
    "item_uploads",
    "external_resources",
    "items",
    "memories",
    "message_items",
    "permissions",
    "messages",
    "ingestion_sources",
    "integration_connections",
    "integration_credentials",
    "role_assignments",
    "role_permissions",
    "roles",
    "sandbox_sessions",
    "tenant_memberships",
    "tenants",
    "users",
}


def test_all_dbml_tables_compile_for_postgresql() -> None:
    configure_mappers()

    assert set(Base.metadata.tables) == EXPECTED_TABLES
    for table in Base.metadata.sorted_tables:
        ddl = str(CreateTable(table).compile(dialect=postgresql.dialect()))
        assert f"CREATE TABLE {table.name}" in ddl


def test_user_status_is_a_required_boolean() -> None:
    columns = Base.metadata.tables["users"].c
    column = columns.status

    assert column.type.python_type is bool
    assert column.nullable is False


def test_username_uniqueness_matches_normalized_local_login_rule() -> None:
    users = Base.metadata.tables["users"]
    username_index = next(
        index for index in users.indexes if index.name == "uq_users_username"
    )

    assert username_index.unique is True
    assert str(username_index.expressions[0]) == "lower(users.username)"


def test_local_passwords_are_scrypt_hashes_and_never_compare_as_plaintext() -> None:
    encoded = PasswordCredentialService.hash("correct horse battery staple")

    assert encoded.startswith("scrypt$")
    assert PasswordCredentialService.verify("correct horse battery staple", encoded)
    assert not PasswordCredentialService.verify("wrong password", encoded)


def test_users_carry_no_administration_flag() -> None:
    """Identity is not authorization: no admin boolean may return to users."""

    forbidden = {"is_root_admin", "is_admin", "is_superuser", "role_id"}

    assert forbidden.isdisjoint(Base.metadata.tables["users"].c.keys())
    assert "role_id" not in Base.metadata.tables["tenant_memberships"].c.keys()
    assert "permission_codes" not in Base.metadata.tables["roles"].c.keys()


def test_guest_identity_and_public_workspace_are_explicit() -> None:
    users = Base.metadata.tables["users"].c
    sessions = Base.metadata.tables["access_sessions"].c
    tenants = Base.metadata.tables["tenants"].c

    assert "identity_kind" not in users
    assert "guest_session_id" not in users
    assert "guest_expires_at" not in users
    assert sessions.user_id.nullable is True
    assert sessions.expires_at.nullable is False
    assert tenants.visibility.nullable is False
    assert tenants.public_access_role_id.nullable is True


def test_guest_access_token_preserves_session_type() -> None:
    guest_session_id = uuid4()
    context = AuthContext(
        session_id=guest_session_id,
        session_kind="guest",
        user_id=None,
        email=None,
        display_name="Guest",
        tenant_id=uuid4(),
        permission_codes=("knowledge.read",),
        group_ids=(),
        role_codes=("guest",),
    )
    tokens = JwtTokenService(
        secret="t" * 32,
        issuer="bothesis",
        audience="bothesis-api",
        expires_in_seconds=900,
    )

    token, _ = tokens.issue(context)
    claims = tokens.verify(token)

    assert claims.session_kind == "guest"
    assert claims.session_id == guest_session_id
    assert claims.user_id is None


def test_engine_normalizes_standard_postgres_url_and_is_cached() -> None:
    database_url = "postgresql://user:password@localhost/bothesis"

    first = get_engine(database_url, echo=False)
    second = get_engine(database_url, echo=False)

    assert first is second
    assert first.url.drivername == "postgresql+asyncpg"
    assert get_session_factory(first).kw["bind"] is first


def test_engine_rejects_non_postgres_urls() -> None:
    with pytest.raises(ValueError, match="must use PostgreSQL"):
        get_engine("sqlite:///bothesis.db")
