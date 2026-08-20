from __future__ import annotations

import os

import pytest
from sqlalchemy import text

from bothesis.db.engine import get_engine


@pytest.mark.asyncio
async def test_document_upload_migration_contract() -> None:
    database_url = os.getenv("TEST_DATABASE_URL")
    if not database_url:
        pytest.skip("TEST_DATABASE_URL is not configured")

    engine = get_engine(database_url)
    async with engine.connect() as connection:
        column_rows = await connection.execute(
            text(
                """
                SELECT table_name, column_name
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name IN (
                    'documents',
                    'tenant_memberships',
                    'document_chunks',
                    'message_documents',
                    'user_principal_tokens',
                    'document_blobs'
                  )
                """
            )
        )
        columns_by_table: dict[str, set[str]] = {}
        for table_name, column_name in column_rows:
            columns_by_table.setdefault(table_name, set()).add(column_name)
        constraints = set(
            await connection.scalars(
                text(
                    """
                    SELECT conname
                    FROM pg_constraint
                    WHERE conrelid = 'documents'::regclass
                    """
                )
            )
        )

    assert {
        "upload_status",
        "content_sha256",
        "upload_idempotency_key",
        "uploaded_at",
    }.issubset(columns_by_table["documents"])
    for table_name in (
        "tenant_memberships",
        "document_chunks",
        "message_documents",
        "user_principal_tokens",
        "document_blobs",
    ):
        assert "deleted_at" in columns_by_table[table_name]
    assert "ck_documents_document_upload_status_is_valid" in constraints
    assert "ck_documents_document_content_sha256_is_valid" in constraints
