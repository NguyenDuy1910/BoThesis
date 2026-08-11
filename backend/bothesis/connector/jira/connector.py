from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import datetime
from datetime import timezone
from typing import Any

from ..base import CheckpointedConnector
from ..base import CheckpointOutput
from ..base import CredentialsConnector
from ..base import CredentialsProviderInterface
from ..base import GenerateSlimDocumentOutput
from ..base import IndexingHeartbeatInterface
from ..base import SecondsSinceUnixEpoch
from ..base import SlimConnectorWithPermSync
from ..contracts import StorageContract
from ..models import BasicExpertInfo
from ..models import ConnectorFailure
from ..models import Document
from ..models import DocumentFailure
from ..models import DocumentSource
from ..models import ExternalAccess
from ..models import HierarchyNode
from ..models import HierarchyNodeType
from ..models import SlimDocument
from ..models import TextSection
from .checkpoint import JiraCheckpoint
from .finx_jira import FinxJira
from .utils import adf_to_text
from .utils import build_jira_attachment_document_id
from .utils import build_jira_document_id
from .utils import build_jira_issue_link
from .utils import format_jira_jql_datetime
from .utils import parse_jira_datetime
from .utils import process_jira_attachment

log = logging.getLogger(__name__)

_DEFAULT_BATCH_SIZE = 50
_SLIM_DOC_BATCH_SIZE = 5000
_JIRA_FIELDS = [
    "summary",
    "description",
    "comment",
    "issuetype",
    "status",
    "priority",
    "labels",
    "assignee",
    "reporter",
    "creator",
    "updated",
    "created",
    "project",
    "parent",
    "attachment",
    "security",
]


def _jql_string(value: str) -> str:
    escaped = value.replace("\\", "\\\\").replace('"', '\\"')
    return '"' + escaped + '"'


class JiraConnector(
    CheckpointedConnector[JiraCheckpoint],
    SlimConnectorWithPermSync,
    CredentialsConnector,
):
    def __init__(
        self,
        jira_base: str,
        is_cloud: bool = True,
        project_keys: str = "",
        sprint_ids: str = "",
        jql_query: str | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        labels_to_skip: list[str] | None = None,
        statuses_to_skip: list[str] | None = None,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least one")
        if not jira_base.strip():
            raise ValueError("jira_base is required")
        self.jira_base = jira_base.rstrip("/")
        self.is_cloud = is_cloud
        self.project_keys = project_keys
        self.sprint_ids = sprint_ids
        self.jql_query = jql_query
        self.batch_size = batch_size
        self.labels_to_skip = labels_to_skip or []
        self.statuses_to_skip = statuses_to_skip or []
        self._credentials_provider: CredentialsProviderInterface | None = None
        self._jira_client: FinxJira | None = None
        self._seen_hierarchy_node_ids: set[str] = set()
        self._allow_images = False
        self._storage: StorageContract | None = None

    def set_allow_images(self, is_enabled: bool) -> None:
        # Enable or disable Jira image attachment processing.
        self._allow_images = is_enabled

    def set_storage(self, storage: StorageContract) -> None:
        self._storage = storage

    @property
    def jira_client(self) -> FinxJira:
        # Return the initialised Jira client, raising if not set.
        if self._jira_client is None:
            raise RuntimeError("Credentials not initialised — call set_credentials_provider first")
        return self._jira_client

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        # Initialise the Jira client from the given credentials provider.
        self._credentials_provider = credentials_provider
        creds = credentials_provider.get_credentials()
        username = creds.get("jira_username")
        api_token = creds.get("jira_access_token") or creds.get("jira_api_token")
        bearer_token = creds.get("jira_bearer_token")
        if not bearer_token and not (username and api_token):
            raise RuntimeError(
                "Jira credentials are required: set jira.username + jira.access_token or JIRA_USERNAME + JIRA_API_TOKEN"
            )
        self._jira_client = FinxJira(
            config={
                "username": username,
                "api_token": api_token,
                "token": bearer_token,
                "is_cloud": self.is_cloud,
            },
            url=self.jira_base,
        )

    def _construct_issue_jql_query(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        if self.jql_query:
            return self.jql_query

        filters: list[str] = []
        keys = [key.strip() for key in self.project_keys.split(",") if key.strip()]
        if len(keys) == 1:
            filters.append(f"project = {_jql_string(keys[0])}")
        elif keys:
            quoted_keys = ", ".join(_jql_string(key) for key in keys)
            filters.append(f"project in ({quoted_keys})")

        sprint_ids = [sprint.strip() for sprint in self.sprint_ids.split(",") if sprint.strip()]
        if len(sprint_ids) == 1:
            filters.append(f"sprint = {_jql_string(sprint_ids[0])}")
        elif sprint_ids:
            quoted_sprints = ", ".join(_jql_string(sprint) for sprint in sprint_ids)
            filters.append(f"sprint in ({quoted_sprints})")

        if self.labels_to_skip:
            filters.extend(
                f"labels != {_jql_string(label)}" for label in self.labels_to_skip
            )

        if self.statuses_to_skip:
            filters.extend(
                f"status != {_jql_string(status)}" for status in self.statuses_to_skip
            )

        if start:
            start_date = format_jira_jql_datetime(datetime.fromtimestamp(start, tz=timezone.utc))
            filters.append(f"updated >= \"{start_date}\"")

        if end:
            end_date = format_jira_jql_datetime(datetime.fromtimestamp(end, tz=timezone.utc))
            filters.append(f"updated <= \"{end_date}\"")

        base = " and ".join(filters) if filters else "updated is not EMPTY"
        return f"{base} order by updated asc, key asc"

    def _project_node_raw_id(self, project_key: str) -> str:
        return f"jira::project::{project_key}"

    def _issue_node_raw_id(self, issue_key: str) -> str:
        return f"jira::issue::{issue_key}"

    def _yield_project_hierarchy_node(
        self, project: dict[str, Any]
    ) -> HierarchyNode | None:
        project_key = str(project.get("key", ""))
        if not project_key:
            return None
        raw_id = self._project_node_raw_id(project_key)
        if raw_id in self._seen_hierarchy_node_ids:
            return None
        self._seen_hierarchy_node_ids.add(raw_id)
        return HierarchyNode(
            raw_node_id=raw_id,
            display_name=project.get("name") or project_key,
            node_type=HierarchyNodeType.SPACE,
        )

    def _yield_parent_hierarchy_node(
        self, issue: dict[str, Any]
    ) -> HierarchyNode | None:
        fields = issue.get("fields", {})
        parent = fields.get("parent") or {}
        parent_key = parent.get("key")
        if not parent_key:
            return None
        raw_id = self._issue_node_raw_id(parent_key)
        if raw_id in self._seen_hierarchy_node_ids:
            return None
        self._seen_hierarchy_node_ids.add(raw_id)
        parent_fields = parent.get("fields", {})
        project = fields.get("project", {})
        return HierarchyNode(
            raw_node_id=raw_id,
            display_name=parent_fields.get("summary") or parent_key,
            node_type=HierarchyNodeType.PAGE,
            parent_raw_node_id=self._project_node_raw_id(project.get("key", "")),
        )

    def _get_parent_hierarchy_raw_id(self, issue: dict[str, Any]) -> str | None:
        fields = issue.get("fields", {})
        parent = fields.get("parent") or {}
        if parent.get("key"):
            return self._issue_node_raw_id(parent["key"])
        project_key = fields.get("project", {}).get("key")
        return self._project_node_raw_id(project_key) if project_key else None

    def _extract_user(self, raw_user: dict[str, Any] | None) -> BasicExpertInfo | None:
        if not raw_user:
            return None
        name = raw_user.get("displayName") or raw_user.get("name") or raw_user.get("accountId")
        if not name:
            return None
        return BasicExpertInfo(
            name=name,
            email=raw_user.get("emailAddress"),
            username=raw_user.get("accountId") or raw_user.get("name"),
        )

    def _extract_issue_text(self, issue: dict[str, Any]) -> str:
        fields = issue.get("fields", {})
        parts: list[str] = []
        description = adf_to_text(fields.get("description")).strip()
        if description:
            parts.append(description)

        comments = fields.get("comment", {}).get("comments", [])
        for comment in comments:
            author = self._extract_user(comment.get("author"))
            created = comment.get("created", "")
            comment_text = adf_to_text(comment.get("body")).strip()
            if not comment_text:
                continue
            author_name = author.name if author else "Unknown"
            parts.append(f"Comment by {author_name} at {created}:\n{comment_text}")

        return "\n\n".join(parts)

    def _extract_metadata(self, issue: dict[str, Any]) -> dict[str, str | list[str]]:
        fields = issue.get("fields", {})
        metadata: dict[str, str | list[str]] = {
            "issue_key": issue.get("key", ""),
            "project": fields.get("project", {}).get("name", ""),
            "project_key": fields.get("project", {}).get("key", ""),
            "issue_type": fields.get("issuetype", {}).get("name", ""),
            "ticket_type": fields.get("issuetype", {}).get("name", ""),
            "status": fields.get("status", {}).get("name", ""),
            "ticket_status": fields.get("status", {}).get("name", ""),
            "doc_type": "jira_issue",
        }

        priority = fields.get("priority") or {}
        if priority.get("name"):
            metadata["priority"] = priority["name"]

        labels = [str(label) for label in fields.get("labels", []) if label]
        if labels:
            metadata["labels"] = labels

        parent_key = (fields.get("parent") or {}).get("key")
        if parent_key:
            metadata["parent_issue"] = parent_key

        return {key: value for key, value in metadata.items() if value}

    def _extract_external_access(self, issue: dict[str, Any]) -> ExternalAccess:
        fields = issue.get("fields", {})
        security = fields.get("security")
        if not security:
            project_key = str(fields.get("project", {}).get("key") or "").strip()
            return ExternalAccess(
                source_reader_ids={project_key} if project_key else set(),
                is_public=False,
            )
        security_name = security.get("name") or security.get("id")
        return ExternalAccess(
            user_group_ids={f"jira-security::{security_name}"} if security_name else set(),
            is_public=False,
        )

    def _convert_issue_to_document(self, issue: dict[str, Any]) -> Document | ConnectorFailure:
        issue_key = issue.get("key", "")
        issue_link = build_jira_issue_link(self.jira_base, issue_key) if issue_key else ""
        try:
            fields = issue.get("fields", {})
            summary = fields.get("summary") or issue_key
            issue_type = fields.get("issuetype", {}).get("name", "Issue")
            semantic_identifier = f"[{issue_key}] {summary}" if issue_key else summary
            text = self._extract_issue_text(issue)
            if not text:
                text = summary

            assignee = self._extract_user(fields.get("assignee"))
            reporter = self._extract_user(fields.get("reporter"))
            creator = self._extract_user(fields.get("creator"))
            secondary_owners = [user for user in (reporter, creator) if user is not None]

            return Document(
                id=build_jira_document_id(issue_key),
                external_id=build_jira_document_id(issue_key),
                external_version=str(fields.get("updated") or "") or None,
                etag=str(fields.get("updated") or "") or None,
                sections=[TextSection(text=text, link=issue_link)],
                source=DocumentSource.JIRA,
                semantic_identifier=semantic_identifier,
                metadata=self._extract_metadata(issue),
                doc_created_at=parse_jira_datetime(fields.get("created")),
                doc_updated_at=parse_jira_datetime(fields.get("updated")),
                primary_owners=[assignee] if assignee else None,
                secondary_owners=secondary_owners or None,
                external_access=self._extract_external_access(issue),
                source_link=issue_link,
                title=f"{issue_type}: {summary}",
                parent_hierarchy_raw_node_id=self._get_parent_hierarchy_raw_id(issue),
            )
        except Exception:
            log.exception("Failed to convert Jira issue %s", issue_key)
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=issue_key,
                    document_link=issue_link,
                ),
                failure_message=f"Failed to convert Jira issue {issue_key}",
            )

    def _fetch_issue_attachments(
        self, issue: dict[str, Any], parent_doc: Document | None
    ) -> tuple[list[Document], list[ConnectorFailure]]:
        fields = issue.get("fields", {})
        issue_key = issue.get("key", "")
        issue_link = build_jira_issue_link(self.jira_base, issue_key) if issue_key else ""
        results: list[Document] = []
        failures: list[ConnectorFailure] = []

        for attachment in fields.get("attachment", []) or []:
            attachment_id = str(attachment.get("id", ""))
            attachment_title = attachment.get("filename") or attachment_id
            try:
                processed = process_jira_attachment(
                    self.jira_client,
                    attachment,
                    issue_key,
                    self._allow_images,
                    self._storage,
                )
                if processed.error:
                    log.warning(
                        "Attachment %s on Jira issue %s encountered error: %s",
                        attachment_title,
                        issue_key,
                        processed.error,
                    )
                    continue
                if not processed.text:
                    continue

                metadata: dict[str, str | list[str]] = {
                    "issue_key": issue_key,
                    "parent_issue": parent_doc.semantic_identifier if parent_doc else issue_key,
                    "parent_content_id": build_jira_document_id(issue_key),
                    "attachment_id": attachment_id,
                    "doc_type": "jira_attachment",
                }
                if parent_doc:
                    for key in (
                        "project",
                        "project_key",
                        "issue_type",
                        "ticket_type",
                        "status",
                        "ticket_status",
                        "labels",
                    ):
                        if key in parent_doc.metadata:
                            metadata[key] = parent_doc.metadata[key]

                results.append(
                    Document(
                        id=build_jira_attachment_document_id(issue_key, attachment_id),
                        external_id=build_jira_attachment_document_id(issue_key, attachment_id),
                        external_version=(
                            f"{attachment.get('created', '')}:{attachment.get('size', '')}"
                        ),
                        etag=str(attachment.get("id") or "") or None,
                        sections=[TextSection(text=processed.text, link=issue_link)],
                        source=DocumentSource.JIRA,
                        semantic_identifier=attachment_title,
                        metadata=metadata,
                        doc_created_at=parse_jira_datetime(attachment.get("created")),
                        doc_updated_at=parse_jira_datetime(attachment.get("created")),
                        primary_owners=parent_doc.primary_owners if parent_doc else None,
                        secondary_owners=parent_doc.secondary_owners if parent_doc else None,
                        external_access=parent_doc.external_access if parent_doc else None,
                        source_link=issue_link,
                        parent_hierarchy_raw_node_id=parent_doc.parent_hierarchy_raw_node_id if parent_doc else None,
                        raw_storage_bucket=processed.raw_storage_bucket,
                        raw_storage_key=processed.raw_storage_key,
                        raw_storage_region=processed.raw_storage_region,
                        mime_type=processed.mime_type,
                        file_name=processed.file_name,
                        size_bytes=processed.size_bytes,
                    )
                )
            except Exception:
                log.exception("Failed to process Jira attachment %s", attachment_title)
                failures.append(
                    ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=attachment_id,
                            document_link=issue_link,
                        ),
                        failure_message=f"Failed to process Jira attachment {attachment_title}",
                    )
                )

        return results, failures

    def _fetch_document_batches(
        self,
        checkpoint: JiraCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> CheckpointOutput[JiraCheckpoint]:
        effective_start = start
        if checkpoint.last_updated_at:
            parsed_checkpoint = parse_jira_datetime(checkpoint.last_updated_at)
            if parsed_checkpoint:
                effective_start = parsed_checkpoint.timestamp()

        jql = self._construct_issue_jql_query(effective_start, end)
        current_start = checkpoint.start_at
        current_batch: list[Document | HierarchyNode] = []
        latest_updated_at: datetime | None = None

        def _on_next_start(next_start: int) -> None:
            nonlocal current_start
            current_start = next_start

        try:
            for issue in self.jira_client.paginated_jql_retrieval(
                jql=jql,
                fields=_JIRA_FIELDS,
                start=current_start,
                limit=self.batch_size,
                next_start_callback=_on_next_start,
            ):
                project_node = self._yield_project_hierarchy_node(
                    issue.get("fields", {}).get("project", {})
                )
                if project_node:
                    current_batch.append(project_node)

                parent_node = self._yield_parent_hierarchy_node(issue)
                if parent_node:
                    current_batch.append(parent_node)

                issue_result = self._convert_issue_to_document(issue)
                if isinstance(issue_result, ConnectorFailure):
                    log.warning(
                        "Skipping Jira issue %s: %s",
                        issue.get("key"),
                        issue_result.failure_message,
                    )
                    parent_doc_for_attachments = None
                else:
                    current_batch.append(issue_result)
                    parent_doc_for_attachments = issue_result
                    if issue_result.doc_updated_at:
                        latest_updated_at = issue_result.doc_updated_at

                attachments, failures = self._fetch_issue_attachments(
                    issue, parent_doc_for_attachments
                )
                current_batch.extend(attachments)
                for failure in failures:
                    log.warning(
                        "Attachment failure on Jira issue %s: %s",
                        issue.get("key"),
                        failure.failure_message,
                    )

                while len(current_batch) >= self.batch_size:
                    yield current_batch[: self.batch_size]
                    current_batch = current_batch[self.batch_size :]

        except Exception:
            log.exception("Unexpected error during Jira document batch fetch")
            raise

        if current_batch:
            yield current_batch

        checkpoint_value = (
            latest_updated_at.isoformat()
            if latest_updated_at
            else checkpoint.last_updated_at
        )
        return JiraCheckpoint(last_updated_at=checkpoint_value, start_at=0)

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: JiraCheckpoint,
    ) -> CheckpointOutput[JiraCheckpoint]:
        # Yield document batches from Jira using incremental JQL checkpointing.
        self._seen_hierarchy_node_ids = set()
        return (yield from self._fetch_document_batches(checkpoint, start, end))

    def build_dummy_checkpoint(self) -> JiraCheckpoint:
        # Return an empty checkpoint for first-time Jira indexing runs.
        return JiraCheckpoint()

    def validate_checkpoint_json(self, checkpoint_json: str) -> JiraCheckpoint:
        # Deserialise and validate a persisted Jira checkpoint.
        return JiraCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._retrieve_all_slim_docs(start, end, callback, include_permissions=False)

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._retrieve_all_slim_docs(start, end, callback, include_permissions=True)

    def _retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        callback: IndexingHeartbeatInterface | None,
        include_permissions: bool,
    ) -> GenerateSlimDocumentOutput:
        jql = self._construct_issue_jql_query(start, end)
        batch: list[SlimDocument] = []
        for issue in self.jira_client.paginated_jql_retrieval(
            jql=jql,
            fields=["updated", "security"],
            limit=_SLIM_DOC_BATCH_SIZE,
        ):
            issue_key = issue.get("key", "")
            if not issue_key:
                continue
            external_access = None
            if include_permissions:
                external_access = self._extract_external_access(issue)
            batch.append(
                SlimDocument(
                    id=build_jira_document_id(issue_key),
                    perm_sync_data={"issue_key": issue_key} if include_permissions else None,
                    external_access=external_access,
                )
            )
            if len(batch) >= _SLIM_DOC_BATCH_SIZE:
                yield batch
                batch = []
                if callback:
                    callback.heartbeat()
        if batch:
            yield batch

    def validate_connector_settings(self) -> None:
        # Verify the connector can reach Jira with current settings.
        try:
            list(
                self.jira_client.paginated_jql_retrieval(
                    jql=self._construct_issue_jql_query(None, None),
                    fields=["summary"],
                    limit=1,
                )
            )
        except Exception:
            log.exception("Jira connector settings validation failed")
            raise
