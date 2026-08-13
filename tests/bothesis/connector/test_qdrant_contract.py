from __future__ import annotations

from datetime import datetime, timezone

from bothesis.connector.models import (
    BasicExpertInfo,
    DocumentSource,
    SourceACL,
    SourceDocument,
    TextSection,
)
from bothesis.connector.qdrant import (
    ChunkingConfig,
    QdrantPayloadContext,
    build_qdrant_records,
)


def test_qdrant_payload_contains_grounding_acl_and_filter_contract() -> None:
    document = SourceDocument(
        external_id="jira::BANK-42",
        external_version="7",
        etag="etag-7",
        source=DocumentSource.JIRA,
        semantic_identifier="[BANK-42] Lending policy",
        title="Story: Lending policy",
        sections=[TextSection(text="A" * 260, link="https://jira.example/browse/BANK-42")],
        metadata={
            "project_key": "BANK",
            "issue_type": "Story",
            "status": "Approved",
            "domains": ["lending"],
        },
        acl=SourceACL(
            user_emails={"Analyst@Example.com"},
            user_group_ids={"Risk-Team"},
        ),
        primary_owners=[BasicExpertInfo(name="Owner", email="owner@example.com")],
        doc_updated_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
    )
    context = QdrantPayloadContext(
        tenant_id="tenant-1",
        connector_id="connector-1",
        scope_id="scope-1",
        embedding_model="embed-v1",
    )

    records = build_qdrant_records(
        document,
        context,
        chunking=ChunkingConfig(max_characters=120, overlap_characters=20),
    )

    assert len(records) == 3
    assert len({record.point_id for record in records}) == 3
    payload = records[0].payload
    assert payload.tenant_id == "tenant-1"
    assert payload.document_id == "jira::BANK-42"
    assert payload.source_type == "jira"
    assert payload.source_link == "https://jira.example/browse/BANK-42"
    assert payload.project_key == "BANK"
    assert payload.ticket_type == "Story"
    assert payload.ticket_status == "Approved"
    assert payload.access_control_list == [
        "email:analyst@example.com",
        "external_group:risk-team",
    ]
    assert payload.is_deleted is False
    assert payload.for_qdrant()["doc_updated_at"] == "2026-08-10T00:00:00Z"

    repeated = build_qdrant_records(
        document,
        context,
        chunking=ChunkingConfig(max_characters=120, overlap_characters=20),
    )
    assert [record.point_id for record in repeated] == [record.point_id for record in records]


def test_public_acl_is_explicit_not_implicit() -> None:
    private = SourceACL()
    public = SourceACL(is_public=True)

    assert private.to_reader_ids() == []
    assert public.to_reader_ids() == ["public"]
