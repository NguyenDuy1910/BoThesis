from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from bothesis.connector.confluence.checkpoint import ConfluenceCheckpoint
from bothesis.connector.confluence.connector import ConfluenceConnector
from bothesis.connector.jira.connector import JiraConnector
from bothesis.connector.models import Document


def test_confluence_cql_escapes_configured_values() -> None:
    connector = ConfluenceConnector(
        "https://example.atlassian.net/wiki",
        is_cloud=True,
        space="BANK'OPS",
        labels_to_skip=["do'not-index"],
    )

    query = connector._construct_page_cql_query()

    assert "space='BANK\\'OPS'" in query
    assert "label != 'do\\'not-index'" in query


def test_confluence_checkpoint_bounds_the_next_incremental_query() -> None:
    class FakeConfluence:
        requested_url = ""

        def retrieve_confluence_spaces(self, **kwargs):
            del kwargs
            return iter(())

        def paginated_page_retrieval(self, *, cql_url, **kwargs):
            del kwargs
            self.requested_url = cql_url
            return iter(())

    connector = ConfluenceConnector("https://example.atlassian.net/wiki", is_cloud=True)
    fake = FakeConfluence()
    connector._confluence_client = fake  # type: ignore[assignment]
    end = datetime(2026, 8, 10, tzinfo=timezone.utc).timestamp()
    generator = connector._fetch_document_batches(
        ConfluenceCheckpoint(last_updated_at="2026-08-01T00:00:00Z"),
        start=0,
        end=end,
    )

    try:
        next(generator)
    except StopIteration as stop:
        completed = stop.value

    cql = parse_qs(urlsplit(fake.requested_url).query)["cql"][0]
    assert "lastmodified >= '2026-08-01 00:00'" in cql
    assert completed.last_updated_at == "2026-08-10T00:00:00+00:00"


def test_jira_document_has_version_lineage_and_project_scoped_access() -> None:
    connector = JiraConnector(
        "https://example.atlassian.net",
        project_keys="BANK",
    )
    issue = {
        "id": "10042",
        "key": "BANK-42",
        "fields": {
            "summary": "Lending policy",
            "description": {
                "type": "doc",
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Grounded details"}],
                    }
                ],
            },
            "comment": {"comments": []},
            "issuetype": {"name": "Story"},
            "status": {"name": "Approved"},
            "labels": ["governed"],
            "project": {"key": "BANK", "name": "Bank"},
            "updated": "2026-08-10T08:30:00.000+0700",
            "created": "2026-08-01T08:30:00.000+0700",
            "security": None,
        },
    }

    document = connector._convert_issue_to_document(issue)

    assert isinstance(document, Document)
    assert document.external_id == "jira::BANK-42"
    assert document.external_version == "2026-08-10T08:30:00.000+0700"
    assert document.metadata["ticket_type"] == "Story"
    assert document.metadata["ticket_status"] == "Approved"
    assert document.external_access is not None
    assert document.external_access.is_public is False
    assert document.external_access.source_reader_ids == {"bank"}
    assert document.get_text_content() == "Grounded details"


def test_jira_jql_quotes_user_controlled_filters() -> None:
    connector = JiraConnector(
        "https://example.atlassian.net",
        project_keys='BANK,OPS"TEAM',
        labels_to_skip=['do"not-index'],
    )

    query = connector._construct_issue_jql_query()

    assert 'project in ("BANK", "OPS\\"TEAM")' in query
    assert 'labels != "do\\"not-index"' in query
