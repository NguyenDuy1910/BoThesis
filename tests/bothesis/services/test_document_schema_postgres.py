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
                    'user_principal_tokens',
                    'connector_credentials',
                    'connector_scopes',
                    'sync_runs'
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
        "connector_credentials",
        "connector_scopes",
        "sync_runs",
    }.issubset(table_names)
    assert {
        "documents",
        "document_blobs",
        "document_chunks",
        "message_documents",
    }.isdisjoint(table_names)
    assert {
        "item_type",
        "document_kind",
        "collection_kind",
        "parent_item_id",
        "storage_key",
        "content_sha256",
        "allowed_principal_tokens",
        "denied_principal_tokens",
        "status",
        "deleted_at",
    }.issubset(columns_by_table["items"])
    assert "encrypted_payload" in columns_by_table["connector_credentials"]
    assert column_types[("connector_credentials", "encrypted_payload")] == "text"
    assert "sync_checkpoint" in columns_by_table["connector_scopes"]
    assert "generation" not in columns_by_table["sync_runs"]
    assert "active_generation" not in columns_by_table["connector_scopes"]
    assert "ck_items_item_type_is_valid" in constraints
    assert "ck_items_item_kind_matches_type" in constraints
    assert "ck_items_item_status_is_valid" in constraints
    assert "ck_items_item_content_sha256_is_valid" in constraints

    assert binary_columns == set()
