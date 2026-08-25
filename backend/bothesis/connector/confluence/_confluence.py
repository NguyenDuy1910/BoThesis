from __future__ import annotations

import logging
from collections.abc import Callable
from collections.abc import Iterator
from typing import Any
from urllib.parse import parse_qsl
from urllib.parse import urlencode
from urllib.parse import urlsplit
from urllib.parse import urlunsplit

log = logging.getLogger(__name__)

_CONFLUENCE_SPACES_API = "api/v2/spaces"
_DEFAULT_PAGINATION_LIMIT = 1000


class FinxConfluence:
    def __init__(
        self,
        config: dict[str, Any],
        url: str,
        timeout_seconds: int = 30,
    ) -> None:
        try:
            from atlassian import Confluence
        except ImportError as exc:
            raise RuntimeError(
                "Confluence connector dependency 'atlassian-python-api' is not installed"
            ) from exc
        self.config = config
        self.base_url = url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.confluence_client = Confluence(
            url=self.base_url,
            username=config.get("username"),
            password=config.get("api_token"),
            timeout=timeout_seconds,
        )

    def _build_spaces_url(
        self,
        limit: int,
        space_keys: list[str] | None,
    ) -> str:
        params: dict[str, str | int] = {"limit": limit}
        if space_keys:
            params["keys"] = ",".join(space_keys)
        return f"{_CONFLUENCE_SPACES_API}?{urlencode(params)}"

    def _log_http_error(self, response: Any, url: str) -> None:
        try:
            body = response.json()
        except Exception:
            body = response.text[:500]
        log.error(
            "Confluence HTTP %s for url=%s — response: %s",
            response.status_code,
            url,
            body,
        )

    def _absolute_next_url(self, next_path: str) -> str:
        if next_path.startswith("http"):
            return next_path
        if next_path.startswith("/wiki/"):
            parsed = urlsplit(self.base_url)
            return f"{parsed.scheme}://{parsed.netloc}{next_path}"
        return f"{self.base_url}/{next_path.lstrip('/')}"

    def _paginate_url(
        self,
        url: str,
        limit: int | None = None,
        next_page_callback: Callable[[str], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        current_url = (
            url if url.startswith("http") else f"{self.base_url}/{url.lstrip('/')}"
        )
        if limit is not None:
            parsed = urlsplit(current_url)
            query = dict(parse_qsl(parsed.query, keep_blank_values=True))
            query.setdefault("limit", str(limit))
            current_url = urlunsplit(
                (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
            )
        while current_url:
            response = self.confluence_client._session.get(
                current_url, timeout=self.timeout_seconds
            )
            if not response.ok:
                self._log_http_error(response, current_url)
                response.raise_for_status()
            data: dict[str, Any] = response.json()
            yield from data.get("results", [])
            next_path = data.get("_links", {}).get("next")
            if not next_path:
                break
            next_url = self._absolute_next_url(next_path)
            if next_page_callback:
                next_page_callback(next_url)
            current_url = next_url

    def _paginate_spaces(
        self,
        limit: int = _DEFAULT_PAGINATION_LIMIT,
        space_keys: list[str] | None = None,
    ) -> Iterator[dict[str, Any]]:
        relative_url = self._build_spaces_url(limit, space_keys)
        full_url = f"{self.base_url}/{relative_url.lstrip('/')}"
        while full_url:
            response = self.confluence_client._session.get(
                full_url, timeout=self.timeout_seconds
            )
            response.raise_for_status()
            data: dict[str, Any] = response.json()
            yield from data.get("results", [])
            next_path = data.get("_links", {}).get("next")
            full_url = self._absolute_next_url(next_path) if next_path else ""

    def retrieve_confluence_spaces(
        self,
        space_keys: list[str] | None = None,
        limit: int = 50,
    ) -> Iterator[dict[str, Any]]:
        # Yield Confluence spaces, optionally filtered by space keys.
        yield from self._paginate_spaces(limit, space_keys)

    def build_cql_url(self, cql: str, expand: str | None = None) -> str:
        # Build a CQL content-search URL with optional field expansion.
        params = {"cql": cql}
        if expand:
            params["expand"] = expand
        return f"rest/api/content/search?{urlencode(params)}"

    def paginated_cql_retrieval(
        self,
        cql: str,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        # Execute a CQL query and yield all results across pages.
        cql_url = self.build_cql_url(cql, expand)
        yield from self._paginate_url(cql_url, limit)

    def paginated_page_retrieval(
        self,
        cql_url: str,
        limit: int,
        next_page_callback: Callable[[str], None] | None = None,
    ) -> Iterator[dict[str, Any]]:
        try:
            yield from self._paginate_url(
                cql_url, limit=limit, next_page_callback=next_page_callback
            )
        except Exception:
            log.exception("Error in paginated_page_retrieval for url=%s", cql_url)
            raise
        

    def get_page_restrictions(self, page_id: str) -> dict[str, Any]:
        # Fetch read/write restriction details for a Confluence page.
        url = (
            f"{self.base_url}/rest/api/content/{page_id}/restriction"
            f"?expand=restrictions.user,restrictions.group"
        )
        response = self.confluence_client._session.get(
            url, timeout=self.timeout_seconds
        )
        response.raise_for_status()
        return response.json()

    def get_page_owner_and_contributors(self, page_id: str) -> dict[str, Any]:
        # Fetch the creator and contributor history for a page.
        url = (
            f"{self.base_url}/rest/api/content/{page_id}"
            f"?expand=history,history.createdBy,history.contributors.publishers"
        )
        response = self.confluence_client._session.get(
            url, timeout=self.timeout_seconds
        )
        response.raise_for_status()
        return response.json()

    def get_page_versions(self, page_id: str) -> list[dict[str, Any]]:
        # Fetch all version records for a Confluence page.
        url = (
            f"{self.base_url}/rest/api/content/{page_id}/version"
            f"?expand=content"
        )
        results: list[dict[str, Any]] = []
        while url:
            response = self.confluence_client._session.get(
                url, timeout=self.timeout_seconds
            )
            response.raise_for_status()
            data = response.json()
            results.extend(data.get("results", []))
            next_path = data.get("_links", {}).get("next")
            url = self._absolute_next_url(next_path) if next_path else ""
        return results

    def get_space_permissions(self, space_id: str) -> list[dict[str, Any]]:
        # Fetch permission entries for a Confluence space via v2 API.
        url = f"{self.base_url}/wiki/api/v2/spaces/{space_id}/permissions"
        results: list[dict[str, Any]] = []
        while url:
            response = self.confluence_client._session.get(
                url, timeout=self.timeout_seconds
            )
            response.raise_for_status()
            data = response.json()
            results.extend(data.get("results", []))
            next_path = data.get("_links", {}).get("next")
            url = self._absolute_next_url(next_path) if next_path else ""
        return results

    def cql_paginate_all_expansions(
        self,
        cql: str,
        expand: str | None = None,
        limit: int | None = None,
    ) -> Iterator[dict[str, Any]]:
        # CQL query that also paginates nested expansion links in results.
        def _traverse_and_update(data: dict[str, Any] | list[Any]) -> None:
            if isinstance(data, dict):
                next_url = data.get("_links", {}).get("next")
                if next_url and "results" in data:
                    data["results"].extend(self._paginate_url(next_url, limit=limit))
                for value in data.values():
                    _traverse_and_update(value)
            elif isinstance(data, list):
                for item in data:
                    _traverse_and_update(item)

        for confluence_object in self.paginated_cql_retrieval(cql, expand, limit):
            _traverse_and_update(confluence_object)
            yield confluence_object
