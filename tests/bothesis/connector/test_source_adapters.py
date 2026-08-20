from __future__ import annotations

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlsplit

from bothesis.connector.confluence.checkpoint import ConfluenceCheckpoint
from bothesis.connector.confluence.connector import ConfluenceConnector


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
