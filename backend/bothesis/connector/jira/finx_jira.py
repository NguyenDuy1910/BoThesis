from __future__ import annotations

from collections.abc import Generator
from collections.abc import Iterator
from typing import Any
from urllib.parse import urlsplit, urlunsplit

def _is_board_without_sprints_error(exc: Exception) -> bool:
    response = exc.response
    status_code = getattr(response, "status_code", None)
    message = str(exc).lower()
    return status_code == 400 and "does not support sprints" in message


def _normalize_jira_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    if not url:
        return ""

    parsed = urlsplit(url)
    path = parsed.path.lower()
    if parsed.scheme and parsed.netloc and (path == "/wiki" or path.startswith("/wiki/")):
        return urlunsplit((parsed.scheme, parsed.netloc, "", "", ""))
    if not parsed.scheme or not parsed.netloc:
        return url.removesuffix("/wiki")
    return url


class FinxJira:
    def __init__(self, config: dict[str, Any], url: str) -> None:
        try:
            from atlassian import Jira
        except ImportError as exc:
            raise RuntimeError(
                "Jira connector requires the optional 'atlassian-python-api' package"
            ) from exc
        self.base_url = _normalize_jira_base_url(url)
        self.is_cloud = config.get("is_cloud", True)
        username = config.get("username")
        api_token = config.get("api_token")
        token = config.get("token")
        timeout = int(config.get("timeout") or 75)
        verify_ssl = bool(config.get("verify_ssl", True))
        self.jira_client = Jira(
            url=self.base_url,
            username=username,
            password=api_token if username else None,
            token=token if not username else None,
            cloud=self.is_cloud,
            timeout=timeout,
            verify_ssl=verify_ssl,
        )

    def paginated_jql_retrieval(
        self,
        jql: str,
        fields: list[str] | str = "*all",
        expand: str | None = None,
        start: int = 0,
        limit: int = 50,
        next_start_callback: Any | None = None,
    ) -> Generator[dict[str, Any], None, None]:
        current_start = start
        next_page_token: str | None = None
        while True:
            if self.is_cloud:
                response = self.jira_client.enhanced_jql(
                    jql,
                    fields=fields,
                    nextPageToken=next_page_token,
                    limit=limit,
                    expand=expand,
                )
            else:
                response = self.jira_client.jql(
                    jql,
                    fields=fields,
                    start=current_start,
                    limit=limit,
                    expand=expand,
                )
            if not response:
                raise RuntimeError(f"Jira JQL request returned no response: {jql}")

            issues = response.get("issues", [])
            if not issues:
                return

            for issue in issues:
                yield issue

            current_start = int(response.get("startAt", current_start)) + len(issues)
            if next_start_callback:
                next_start_callback(current_start)

            if self.is_cloud:
                next_page_token = response.get("nextPageToken")
                if not next_page_token or response.get("isLast") is True:
                    return
                continue

            total = response.get("total")
            if total is not None and current_start >= int(total):
                return
            if len(issues) < limit:
                return

    def get_attachment_content(self, attachment_id: str) -> bytes:
        return self.jira_client.get_attachment_content(attachment_id)

    def get_project(self, project_key: str) -> dict[str, Any]:
        project = self.jira_client.get_project(project_key)
        return project or {}

    def retrieve_jira_projects(self) -> Iterator[dict[str, Any]]:
        projects = self.jira_client.projects()
        if isinstance(projects, dict):
            yield from projects.get("values") or projects.get("projects") or []
            return
        yield from projects or []

    def paginated_agile_boards(
        self,
        *,
        project_key: str | None = None,
        board_type: str | None = None,
        limit: int = 50,
    ) -> Iterator[dict[str, Any]]:
        start = 0
        page_size = max(1, min(limit, 50))
        while True:
            response = self.jira_client.get_all_agile_boards(
                project_key=project_key,
                board_type=board_type,
                start=start,
                limit=page_size,
            )
            if not response:
                return
            values = response.get("values", [])
            yield from values
            start += len(values)
            if response.get("isLast") is True:
                return
            total = response.get("total")
            if total is not None and start >= int(total):
                return
            if len(values) < page_size:
                return

    def paginated_sprints_from_board(
        self,
        board_id: str | int,
        *,
        state: str | None = None,
        limit: int = 50,
    ) -> Iterator[dict[str, Any]]:
        start = 0
        page_size = max(1, min(limit, 50))
        while True:
            try:
                response = self.jira_client.get_all_sprints_from_board(
                    board_id=board_id,
                    state=state,
                    start=start,
                    limit=page_size,
                )
            except Exception as exc:
                if _is_board_without_sprints_error(exc):
                    return
                raise
            if not response:
                return
            values = response.get("values", [])
            yield from values
            start += len(values)
            if response.get("isLast") is True:
                return
            total = response.get("total")
            if total is not None and start >= int(total):
                return
            if len(values) < page_size:
                return

    def retrieve_jira_sprints(
        self,
        *,
        project_key: str | None = None,
        state: str | None = "active,future",
        limit: int = 200,
    ) -> Iterator[dict[str, Any]]:
        seen: set[str] = set()
        yielded = 0
        for board in self.paginated_agile_boards(project_key=project_key, board_type="scrum"):
            board_id = board.get("id")
            if board_id is None:
                continue
            for sprint in self.paginated_sprints_from_board(board_id, state=state):
                sprint_id = str(sprint.get("id") or "")
                if not sprint_id or sprint_id in seen:
                    continue
                seen.add(sprint_id)
                enriched = dict(sprint)
                enriched["board_id"] = str(board_id)
                enriched["board_name"] = board.get("name")
                location = board.get("location") if isinstance(board.get("location"), dict) else {}
                enriched["project_key"] = project_key or location.get("projectKey")
                yield enriched
                yielded += 1
                if yielded >= limit:
                    return

    def issue(
        self,
        issue_key: str,
        *,
        fields: list[str] | str = "*all",
        expand: str | None = None,
    ) -> dict[str, Any]:
        return self.jira_client.issue(issue_key, fields=fields, expand=expand) or {}

    def get_issue(
        self, issue_key: str, *, fields: list[str] | str = "*all"
    ) -> dict[str, Any]:
        return self.issue(issue_key, fields=fields)

    def get_issue_changelog(self, issue_key: str, *, limit: int = 100) -> list[dict[str, Any]]:
        data = self.issue(issue_key, fields="status", expand="changelog")
        histories = (data.get("changelog") or {}).get("histories") or []
        return histories[:limit]

    def get_issue_comments(self, issue_key: str, *, limit: int = 100) -> list[dict[str, Any]]:
        data = self.issue(issue_key, fields="comment")
        comment = (data.get("fields") or {}).get("comment") or {}
        return (comment.get("comments") or [])[:limit]

    def get_issue_worklogs(self, issue_key: str, *, limit: int = 100) -> list[dict[str, Any]]:
        data = self.issue(issue_key, fields="worklog")
        worklog = (data.get("fields") or {}).get("worklog") or {}
        return (worklog.get("worklogs") or [])[:limit]

    def get_board_config(self, board_id: str | int) -> dict[str, Any]:
        getter = getattr(self.jira_client, "get_agile_board_configuration", None)
        if getter is None:
            return {}
        return getter(board_id) or {}

    def get_fields(self) -> list[dict[str, Any]]:
        getter = getattr(self.jira_client, "get_all_fields", None)
        if getter is None:
            return []
        return getter() or []

    def count_issues(self, jql: str) -> int | None:
        response = self._search_page(jql, fields="id", limit=1)
        total = response.get("total")
        try:
            return int(total) if total is not None else None
        except (TypeError, ValueError):
            return None

    def _search_page(
        self, jql: str, *, fields: list[str] | str = "id", limit: int = 1
    ) -> dict[str, Any]:
        if self.is_cloud:
            return self.jira_client.enhanced_jql(jql, fields=fields, limit=limit) or {}
        return self.jira_client.jql(jql, fields=fields, start=0, limit=limit) or {}

    def find_users(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        finder = getattr(self.jira_client, "user_find_by_user_string", None)
        if finder is None:
            return []
        try:
            result = finder(query=query, start=0, limit=limit)
        except TypeError:
            result = finder(query=query)
        if isinstance(result, dict):
            return result.get("values") or []
        return result or []

    def resolve_assignee(self, query: str) -> str | None:
        users = self.find_users(query, limit=2)
        if not users:
            return None
        user = users[0]
        if self.is_cloud:
            return user.get("accountId")
        return user.get("name") or user.get("key") or user.get("accountId")
