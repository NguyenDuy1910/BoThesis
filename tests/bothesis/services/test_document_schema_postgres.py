from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from bothesis.db.engine import get_engine


@pytest.mark.asyncio
async def test_final_source_storage_schema_contract() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    engine = get_engine(database_url)
    async with engine.connect() as connection:
        table_names = set(
            await connection.scalars(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = current_schema()
                    """
                )
            )
        )
        column_rows = await connection.execute(
            text(
                """
                SELECT table_name, column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name IN (
                    'items',
                    'item_uploads',
                    'tenant_memberships',
                    'message_items',
                    'integration_connections',
                    'integration_credentials',
                    'ingestion_sources',
                    'external_resources'
                  )
                """
            )
        )
        columns_by_table: dict[str, set[str]] = {}
        column_types: dict[tuple[str, str], str] = {}
        for table_name, column_name, data_type in column_rows:
            columns_by_table.setdefault(table_name, set()).add(column_name)
            column_types[(table_name, column_name)] = data_type
        constraints = set(
            await connection.scalars(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'items'::regclass
                    """
                )
            )
        )
        binary_columns = set(
            await connection.execute(
                text(
                    """
                    SELECT table_name, column_name
                    FROM information_schema.columns
                    WHERE table_schema = current_schema()
                      AND data_type = 'bytea'
                    """
                )
            )
        )

    assert {
        "items",
        "item_uploads",
        "message_items",
        "integration_connections",
        "integration_credentials",
        "ingestion_sources",
        "external_resources",
    }.issubset(table_names)
    assert {
        "documents",
        "document_blobs",
        "document_chunks",
        "message_documents",
    }.isdisjoint(table_names)
    assert {
        "item_type",
        "document_type",
        "parent_item_id",
        "parent_relation",
        "storage_key",
        "status",
        "deleted_at",
    }.issubset(columns_by_table["items"])
    assert {
        "connector_key",
        "config",
        "status",
    }.issubset(columns_by_table["integration_connections"])
    assert "encrypted_payload" in columns_by_table["integration_credentials"]
    assert column_types[("integration_credentials", "encrypted_payload")] == "text"
    assert {
        "integration_connection_id",
        "target_item_id",
        "checkpoint",
        "last_ingested_at",
    }.issubset(columns_by_table["ingestion_sources"])
    assert {
        "ingestion_source_id",
        "item_id",
        "external_id",
        "external_version",
        "etag",
    }.issubset(columns_by_table["external_resources"])
    assert "ck_items_item_type_is_valid" in constraints
    assert "ck_items_item_document_type_matches_type" in constraints
    assert "ck_items_item_status_is_valid" in constraints

    assert binary_columns == set()
