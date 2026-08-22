from __future__ import annotations

from bothesis.knowledge.protocol import (
    AccessPolicy,
    CodePart,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    ImagePart,
    LinkPart,
    StructuredPart,
    TablePart,
    SourceIdentity,
    SourceProvider,
    BoundingBox,
    CitationSpan,
    TextPart,
)
from bothesis.connector.qdrant import (
    ChunkingConfig,
    QdrantPayloadContext,
    build_qdrant_records,
)


def test_qdrant_payload_contains_grounding_acl_and_filter_contract() -> None:
    document = DocumentItem(
        id="jira::BANK-42",
        title="Story: Lending policy",
        document_kind=DocumentKind.ISSUE,
        source=SourceIdentity(
            connector_id="connector-1",
            provider=SourceProvider.JIRA,
            external_id="BANK-42",
            external_version="7",
            etag="etag-7",
            url="https://jira.example/browse/BANK-42",
        ),
        hierarchy=Hierarchy(
            parent_id="jira::BANK",
            root_id="jira::root",
            ancestor_ids=["jira::root", "jira::BANK"],
        ),
        metadata={
            "project_key": "BANK",
            "issue_type": "Story",
            "status": "Approved",
            "domains": ["lending"],
            "heading_path": ["Reliability", "Replication"],
            "summary": "Explains the approved lending policy.",
            "page_number": "7",
        },
        access=AccessPolicy.from_reader_ids(
            ["email:Analyst@Example.com", "external_group:Risk-Team"]
        ),
        content=[TextPart(text="A" * 260)],
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
    assert payload.item_id == "jira::BANK-42"
    assert payload.chunk_id == "jira::BANK-42:0"
    assert payload.provider == "jira"
    assert payload.external_id == "BANK-42"
    assert payload.source_url == "https://jira.example/browse/BANK-42"
    assert payload.parent_id == "jira::BANK"
    assert payload.root_id == "jira::root"
    assert payload.ancestor_ids == ["jira::root", "jira::BANK"]
    assert payload.reader_ids == [
        "email:analyst@example.com",
        "external_group:risk-team",
    ]
    assert payload.chunk_text == "A" * 120
    assert "Document: Story: Lending policy" in payload.contextual_text
    assert payload.document_kind == "issue"
    assert payload.content_type == "text"
    assert payload.context_section_path == ["Reliability", "Replication"]
    assert payload.context_summary == "Explains the approved lending policy."
    assert payload.page_start == 7
    assert payload.page_end == 7
    assert payload.citation_section_path == ["Reliability", "Replication"]
    assert payload.citation_spans == (
        CitationSpan(page=7, element_id="element_001", start_offset=0, end_offset=120),
    )
    assert "Section: Reliability > Replication" in payload.contextual_text
    assert payload.is_deleted is False
    serialized = payload.for_qdrant()
    assert serialized["item_id"] == "jira::BANK-42"
    assert "access" not in serialized
    assert "storage" not in serialized

    repeated = build_qdrant_records(
        document,
        context,
        chunking=ChunkingConfig(max_characters=120, overlap_characters=20),
    )
    assert [record.point_id for record in repeated] == [record.point_id for record in records]


def test_public_acl_is_explicit_not_implicit() -> None:
    private = AccessPolicy()
    public = AccessPolicy.from_reader_ids(["public"])

    assert private.to_reader_ids() == []
    assert public.to_reader_ids() == ["public"]


def test_content_parts_become_typed_textual_chunks() -> None:
    item = DocumentItem(
        id="item-1",
        title="Mixed content",
        document_kind=DocumentKind.DOCUMENT,
        source=SourceIdentity(
            connector_id="connector-1",
            provider=SourceProvider.FILE,
            external_id="item-1",
        ),
        content=[
            ImagePart(description="Architecture diagram", ocr_text="Leader"),
            TablePart(rows=[["Role", "Owner"], ["Leader", "Platform"]]),
            StructuredPart(data={"status": "approved", "version": 2}),
            LinkPart(title="Runbook", url="https://example.test/runbook"),
            CodePart(language="python", code="print('ok')"),
        ],
    )

    records = build_qdrant_records(
        item,
        QdrantPayloadContext(tenant_id="tenant-1", connector_id="connector-1"),
        chunking=ChunkingConfig(max_characters=100, overlap_characters=0),
    )

    assert [record.payload.content_type for record in records] == [
        "image",
        "table",
        "structured",
        "link",
        "code",
    ]
    assert "Architecture diagram" in records[0].payload.chunk_text
    assert "Leader | Platform" in records[1].payload.chunk_text
    assert '"status": "approved"' in records[2].payload.chunk_text
    assert "Runbook: https://example.test/runbook" in records[3].payload.chunk_text
    assert records[3].payload.source_url is None
    assert "print('ok')" in records[4].payload.chunk_text
    assert all(record.payload.contextual_text.startswith("Document: Mixed content") for record in records)


def test_citation_locator_round_trips_for_pdf_and_normalized_elements() -> None:
    item = DocumentItem(
        id="item-pdf",
        title="Kafka Design",
        document_kind=DocumentKind.PDF,
        source=SourceIdentity(
            connector_id="connector-1",
            provider=SourceProvider.CONFLUENCE,
            external_id="page-42",
            url="https://confluence.example/pages/42",
        ),
        content=[
            TextPart(
                element_id="paragraph_002",
                page=7,
                section="Replication",
                section_path=("Reliability", "Replication"),
                anchor="replication",
                text="The partition leader handles all reads and writes for the partition.",
            ),
            ImagePart(
                element_id="image_001",
                page=7,
                bounding_box=BoundingBox(x=0.1, y=0.2, width=0.5, height=0.4),
                description="Replication topology",
            ),
        ],
    )

    record = build_qdrant_records(
        item,
        QdrantPayloadContext(tenant_id="tenant-1", connector_id="connector-1"),
    )[0]
    payload = record.payload
    assert payload.page_start == 7
    assert payload.citation_section == "Replication"
    assert payload.citation_section_path == ["Reliability", "Replication"]
    assert payload.citation_anchor == "replication"
    assert payload.citation_spans[0] == CitationSpan(
        page=7,
        element_id="paragraph_002",
        start_offset=0,
        end_offset=len(payload.chunk_text),
    )

    restored = type(payload).model_validate(payload.for_qdrant())
    assert restored.citation_spans[0].bounding_box is None

    image_payload = build_qdrant_records(
        item,
        QdrantPayloadContext(tenant_id="tenant-1", connector_id="connector-1"),
    )[1].payload
    assert image_payload.citation_spans[0].element_id == "image_001"
    assert image_payload.citation_spans[0].bounding_box == BoundingBox(
        x=0.1, y=0.2, width=0.5, height=0.4
    )


def test_multi_element_citation_and_signed_source_url_round_trip() -> None:
    item = DocumentItem(
        id="pdf-large",
        title="Large report",
        document_kind=DocumentKind.PDF,
        source=SourceIdentity(
            connector_id="connector-1",
            provider=SourceProvider.FILE,
            external_id="pdf-large",
            url="https://objects.example.test/raw.pdf?X-Amz-Signature=secret",
        ),
        content=[
            TextPart(element_id="p120_para18", page=120, text="first page evidence"),
            TextPart(element_id="p121_para01", page=121, text="second page evidence"),
        ],
    )

    payload = build_qdrant_records(
        item,
        QdrantPayloadContext(tenant_id="tenant-1", connector_id="connector-1"),
        chunking=ChunkingConfig(max_characters=100, overlap_characters=0),
    )[0].payload

    assert [span.element_id for span in payload.citation_spans] == [
        "p120_para18",
        "p121_para01",
    ]
    assert [span.page for span in payload.citation_spans] == [120, 121]
    assert payload.page_start == 120
    assert payload.page_end == 121
    assert payload.source_url is None
    assert "citation_spans" in payload.for_qdrant()
    assert "X-Amz-Signature" not in str(payload.for_qdrant())
