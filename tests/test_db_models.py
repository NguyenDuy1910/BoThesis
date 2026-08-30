from __future__ import annotations

import pytest
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import configure_mappers
from sqlalchemy.schema import CreateTable

from bothesis.db.engine import get_engine, get_session_factory
from bothesis.db.models import Base


EXPECTED_TABLES = {
    "access_requests",
    "audit_logs",
    "collection_access",
    "conversations",
    "group_memberships",
    "groups",
    "item_uploads",
    "external_resources",
    "items",
    "memories",
    "message_items",
    "messages",
    "ingestion_sources",
    "integration_connections",
    "integration_credentials",
    "roles",
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
