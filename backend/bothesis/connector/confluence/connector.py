from __future__ import annotations

import logging
from collections.abc import Generator
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from typing import Any
from urllib.parse import urlencode

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
from ..models import ImageSection
from ..models import SlimDocument
from ..models import TextSection
from ._confluence import FinxConfluence
from .checkpoint import ConfluenceCheckpoint
from .utils import build_confluence_document_id
from .utils import convert_attachment_to_content
from .utils import datetime_from_string

log = logging.getLogger(__name__)

_PAGE_EXPAND = (
    "body.storage.value,version,space,metadata.labels,history.lastUpdated,ancestors"
)
_VERSION_ONLY_EXPAND = "version,space"
_ATTACHMENT_EXPAND = "version,space,metadata.labels"
_SLIM_DOC_BATCH_SIZE = 5000
_DEFAULT_BATCH_SIZE = 50


def _get_page_id(page: dict[str, Any], allow_missing: bool = False) -> str:
    if allow_missing and "id" not in page:
        return "unknown"
    return str(page["id"])


def _remove_macro_stylings(soup: Any) -> None:
    for element in soup.find_all("ac:parameter"):
        element.decompose()


def _format_soup_text(soup: Any) -> str:
    raw = soup.get_text(separator=" ", strip=True)
    return " ".join(raw.split())


def _sanitize_attachment_filename(filename: str) -> str:
    return filename.replace('"', "").replace("'", "")


def _cql_string(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _http_status(exc: BaseException) -> int | None:
    response = getattr(exc, "response", None)
    return getattr(response, "status_code", None)


class ConfluenceConnector(
    CheckpointedConnector[ConfluenceCheckpoint],
    SlimConnectorWithPermSync,
    CredentialsConnector,
):
    def __init__(
        self,
        wiki_base: str,
        is_cloud: bool,
        space: str = "",
        page_id: str = "",
        index_recursively: bool = False,
        cql_query: str | None = None,
        batch_size: int = _DEFAULT_BATCH_SIZE,
        labels_to_skip: list[str] | None = None,
        timezone_offset: float = 0.0,
    ) -> None:
        if batch_size < 1:
            raise ValueError("batch_size must be at least one")
        if not wiki_base.strip():
            raise ValueError("wiki_base is required")
        self.wiki_base = wiki_base.rstrip("/")
        self.is_cloud = is_cloud
        self.space = space
        self.page_id = page_id
        self.index_recursively = index_recursively
        self.cql_query = cql_query
        self.batch_size = batch_size
        self.labels_to_skip = labels_to_skip or []
        self.timezone = timezone(timedelta(hours=timezone_offset))
        self._credentials_provider: CredentialsProviderInterface | None = None
        self._confluence_client: FinxConfluence | None = None
        self._seen_hierarchy_node_ids: set[str] = set()
        self._included_page_text_cache: dict[str, str | None] = {}
        self._user_display_name_cache: dict[str, str] = {}
        self._allow_images: bool = False
        self._storage: StorageContract | None = None

    def set_allow_images(self, is_enabled: bool) -> None:
        # Enable or disable image attachment processing.
        self._allow_images = is_enabled

    def set_storage(self, storage: StorageContract) -> None:
        self._storage = storage

    @property
    def confluence_client(self) -> FinxConfluence:
        # Return the initialised Confluence client, raising if not set.
        if self._confluence_client is None:
            raise RuntimeError(
                "Credentials not initialised — call set_credentials_provider first"
            )
        return self._confluence_client

    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        # Initialise the Confluence client from the given credentials provider.
        self._credentials_provider = credentials_provider
        creds = credentials_provider.get_credentials()
        self._confluence_client = FinxConfluence(
            config={
                "username": creds.get("confluence_username"),
                "api_token": creds.get("confluence_access_token"),
                "is_cloud": self.is_cloud,
            },
            url=self.wiki_base,
        )

    def _construct_page_cql_query(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> str:
        if self.cql_query:
            return self.cql_query

        if self.page_id:
            base = (
                f"type=page and (id={self.page_id} or ancestor={self.page_id})"
                if self.index_recursively
                else f"type=page and id={self.page_id}"
            )
        elif self.space:
            keys = [k.strip() for k in self.space.split(",") if k.strip()]
            if len(keys) == 1:
                base = f"type=page and space='{_cql_string(keys[0])}'"
            else:
                space_filter = " or ".join(
                    f"space='{_cql_string(key)}'" for key in keys
                )
                base = f"type=page and ({space_filter})"
        else:
            base = "type=page"

        if self.labels_to_skip:
            label_filter = " and ".join(
                f"label != '{_cql_string(label)}'" for label in self.labels_to_skip
            )
            base += f" and ({label_filter})"

        if start:
            fmt = datetime.fromtimestamp(start, tz=self.timezone).strftime(
                "%Y-%m-%d %H:%M"
            )
            base += f" and lastmodified >= '{fmt}'"

        if end:
            fmt = datetime.fromtimestamp(end, tz=self.timezone).strftime(
                "%Y-%m-%d %H:%M"
            )
            base += f" and lastmodified <= '{fmt}'"

        return base + " order by lastmodified asc"

    def _yield_space_hierarchy_nodes(self) -> Generator[HierarchyNode, None, None]:
        space_keys = (
            [k.strip() for k in self.space.split(",") if k.strip()]
            if self.space
            else None
        )
        try:
            for space in self.confluence_client.retrieve_confluence_spaces(
                space_keys=space_keys
            ):
                raw_id = space.get("key", "")
                if raw_id and raw_id not in self._seen_hierarchy_node_ids:
                    self._seen_hierarchy_node_ids.add(raw_id)
                    yield HierarchyNode(
                        raw_node_id=raw_id,
                        display_name=space.get("name", raw_id),
                        node_type=HierarchyNodeType.SPACE,
                    )
        except Exception:
            log.exception("Failed to fetch space hierarchy nodes")

    def _yield_ancestor_hierarchy_nodes(
        self, page: dict[str, Any]
    ) -> Generator[HierarchyNode, None, None]:
        ancestors = page.get("ancestors", [])
        space_key = page.get("space", {}).get("key", "")
        for idx, ancestor in enumerate(ancestors):
            ancestor_id = f"confluence::{ancestor.get('id', '')}"
            if ancestor_id in self._seen_hierarchy_node_ids:
                continue
            self._seen_hierarchy_node_ids.add(ancestor_id)
            parent_raw_id: str | None
            if idx == 0:
                parent_raw_id = space_key or None
            else:
                prev = ancestors[idx - 1]
                parent_raw_id = f"confluence::{prev.get('id', '')}"
            yield HierarchyNode(
                raw_node_id=ancestor_id,
                display_name=ancestor.get("title", str(ancestor.get("id", ""))),
                node_type=HierarchyNodeType.PAGE,
                parent_raw_node_id=parent_raw_id,
            )

    def _get_parent_hierarchy_raw_id(self, page: dict[str, Any]) -> str | None:
        ancestors = page.get("ancestors", [])
        space_key = page.get("space", {}).get("key", "")
        if not ancestors:
            return space_key or None
        last = ancestors[-1]
        return f"confluence::{last.get('id', '')}"

    def _maybe_yield_page_hierarchy_node(
        self, page: dict[str, Any], stable_id: str
    ) -> HierarchyNode | None:
        if stable_id in self._seen_hierarchy_node_ids:
            return None
        self._seen_hierarchy_node_ids.add(stable_id)
        return HierarchyNode(
            raw_node_id=stable_id,
            display_name=page.get("title", stable_id),
            node_type=HierarchyNodeType.PAGE,
            parent_raw_node_id=self._get_parent_hierarchy_raw_id(page),
        )

    def _extract_page_text(self, page: dict[str, Any]) -> str:
        body = page.get("body", {})
        html = body.get("storage", body.get("view", {})).get("value", "")
        if not html:
            return ""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "Confluence HTML extraction requires the optional 'beautifulsoup4' package"
            ) from exc

        soup = BeautifulSoup(html, "html.parser")
        _remove_macro_stylings(soup)

        for user_tag in soup.findAll("ri:user"):
            user_id = user_tag.attrs.get("ri:account-id") or user_tag.attrs.get(
                "ri:userkey", ""
            )
            if user_id:
                display_name = self._user_display_name_cache.get(user_id)
                if display_name is None:
                    try:
                        raw = self.confluence_client.confluence_client.get_user_details_by_accountid(
                            user_id
                        )
                        display_name = raw.get("displayName", user_id)
                    except Exception:
                        display_name = user_id
                    self._user_display_name_cache[user_id] = display_name
                user_tag.replaceWith(f"@{display_name}")

        for macro in soup.findAll("ac:structured-macro"):
            if macro.attrs.get("ac:name") != "include":
                continue
            page_data = macro.find("ri:page")
            if not page_data:
                continue
            page_title = page_data.attrs.get("ri:content-title")
            if not page_title:
                continue
            if page_title in self._included_page_text_cache:
                cached_text = self._included_page_text_cache[page_title]
                if cached_text:
                    macro.replaceWith(cached_text)
                continue
            # A sentinel prevents recursive include cycles.
            self._included_page_text_cache[page_title] = None
            try:
                cql = f"type=page and title='{_cql_string(page_title)}'"
                included: dict[str, Any] | None = None
                for result in self.confluence_client.paginated_cql_retrieval(
                    cql=cql, expand="body.storage.value", limit=1
                ):
                    included = result
                    break
                if included:
                    included_text = self._extract_page_text(included)
                    self._included_page_text_cache[page_title] = included_text
                    macro.replaceWith(included_text)
            except Exception:
                log.exception("Failed to expand included page '%s'", page_title)

        for link_body in soup.findAll("ac:link-body"):
            try:
                link_body.replaceWith(f"(LINK TEXT: {link_body.text})")
            except Exception:
                log.exception("Failed to process link body")

        for attachment_ref in soup.findAll("ri:attachment"):
            try:
                filename = _sanitize_attachment_filename(
                    attachment_ref.attrs.get("ri:filename", "")
                )
                attachment_ref.replaceWith(f"<attachment>{filename}</attachment>")
            except Exception:
                log.exception("Failed to process attachment reference")

        return _format_soup_text(soup)

    def _fetch_page_restrictions(
        self, page_id: str, space_key: str
    ) -> ExternalAccess | None:
        try:
            data = self.confluence_client.get_page_restrictions(page_id)
            results = data.get("results", [])
            user_emails: set[str] = set()
            group_ids: set[str] = set()
            has_read_restriction = False

            for restriction in results:
                if restriction.get("operation") != "read":
                    continue
                has_read_restriction = True
                users = (
                    restriction.get("restrictions", {})
                    .get("user", {})
                    .get("results", [])
                )
                for user in users:
                    email = user.get("email")
                    if email:
                        user_emails.add(email)
                groups = (
                    restriction.get("restrictions", {})
                    .get("group", {})
                    .get("results", [])
                )
                for group in groups:
                    group_id = group.get("id") or group.get("name")
                    if group_id:
                        group_ids.add(group_id)

            if not has_read_restriction:
                # Page restrictions are only one layer. Preserve the space
                # boundary instead of treating the page as globally public.
                return ExternalAccess(
                    source_reader_ids={space_key} if space_key else set(),
                    is_public=False,
                )

            return ExternalAccess(
                user_emails=user_emails,
                user_group_ids=group_ids,
                is_public=False,
            )
        except Exception:
            log.exception("Failed to fetch restrictions for page %s", page_id)
            return None

    def _fetch_secondary_owners(
        self, page_id: str, primary_email: str | None
    ) -> list[BasicExpertInfo]:
        try:
            data = self.confluence_client.get_page_owner_and_contributors(page_id)
            seen_names: set[str] = set()
            secondary: list[BasicExpertInfo] = []

            creator = data.get("history", {}).get("createdBy", {})
            if creator:
                creator_name = creator.get("displayName", "")
                creator_email = creator.get("email")
                if creator_name and creator_name not in seen_names:
                    if not primary_email or creator_email != primary_email:
                        seen_names.add(creator_name)
                        secondary.append(
                            BasicExpertInfo(name=creator_name, email=creator_email)
                        )

            publishers = (
                data.get("history", {})
                .get("contributors", {})
                .get("publishers", {})
                .get("users", [])
            )
            for user in publishers:
                name = user.get("displayName", "")
                email = user.get("email")
                if name and name not in seen_names:
                    if not primary_email or email != primary_email:
                        seen_names.add(name)
                        secondary.append(BasicExpertInfo(name=name, email=email))

            return secondary
        except Exception:
            log.exception("Failed to fetch contributors for page %s", page_id)
            return []

    def _convert_page_to_document(
        self, page: dict[str, Any]
    ) -> Document | ConnectorFailure:
        page_id = ""
        page_url = ""
        try:
            page_id = _get_page_id(page)
            page_title = page["title"]
            page_url = build_confluence_document_id(
                self.wiki_base, page["_links"]["webui"], self.is_cloud
            )
            stable_id = f"confluence::{page_id}"

            page_text = self._extract_page_text(page)
            sections: list[TextSection | ImageSection] = [
                TextSection(text=page_text, link=page_url)
            ]

            metadata: dict[str, str | list[str]] = {
                "doc_type": "confluence_page"
            }
            if "space" in page:
                metadata["space"] = page["space"].get("name", "")
                metadata["space_key"] = page["space"].get("key", "")

            labels = [
                lbl.get("name", "")
                for lbl in page.get("metadata", {}).get("labels", {}).get("results", [])
                if lbl.get("name")
            ]
            if labels:
                metadata["labels"] = labels

            primary_owners: list[BasicExpertInfo] = []
            version_by = page.get("version", {}).get("by", {})
            primary_email: str | None = None
            if version_by:
                primary_email = version_by.get("email")
                primary_owners.append(
                    BasicExpertInfo(
                        name=version_by.get("displayName", "Unknown"),
                        email=primary_email,
                    )
                )

            secondary_owners = self._fetch_secondary_owners(page_id, primary_email)
            external_access = self._fetch_page_restrictions(
                page_id, str(page.get("space", {}).get("key") or "")
            )

            return Document(
                id=stable_id,
                external_id=stable_id,
                external_version=str(page.get("version", {}).get("number") or "") or None,
                etag=str(page.get("version", {}).get("when") or "") or None,
                sections=sections,
                source=DocumentSource.CONFLUENCE,
                semantic_identifier=page_title,
                metadata=metadata,
                doc_updated_at=datetime_from_string(page["version"]["when"]),
                doc_created_at=(
                    datetime_from_string(page["history"]["createdDate"])
                    if page.get("history", {}).get("createdDate")
                    else None
                ),
                primary_owners=primary_owners or None,
                secondary_owners=secondary_owners or None,
                external_access=external_access,
                source_link=page_url,
                parent_hierarchy_raw_node_id=self._get_parent_hierarchy_raw_id(page),
            )
        except Exception:
            log.exception("Failed to convert page %s", page_id)
            return ConnectorFailure(
                failed_document=DocumentFailure(
                    document_id=page_id,
                    document_link=page_url,
                ),
                failure_message=f"Failed to convert page {page_id}",
            )

    def _convert_attachment_to_document(
        self,
        *,
        page: dict[str, Any],
        page_id: str,
        attachment: dict[str, Any],
        parent_doc: Document | None,
    ) -> Document | None:
        attachment_id = str(attachment.get("id", ""))
        attachment_title = attachment.get("title", attachment_id)
        stable_page_id = f"confluence::{page_id}"
        stable_att_id = f"{stable_page_id}::att::{attachment_id}"
        attachment_url = build_confluence_document_id(
            self.wiki_base,
            attachment.get("_links", {}).get(
                "download",
                f"/download/attachments/{page_id}/{attachment_title}",
            ),
            self.is_cloud,
        )
        content = convert_attachment_to_content(
            confluence_client=self.confluence_client,
            attachment=attachment,
            page_id=page_id,
            allow_images=self._allow_images,
            storage=self._storage,
            document_id=stable_att_id,
        )
        if content is None or not content.text:
            return None

        metadata: dict[str, str | list[str]] = {
            "space": page.get("space", {}).get("name", ""),
            "space_key": page.get("space", {}).get("key", ""),
            "attachment_id": attachment_id,
            "parent_content_id": stable_page_id,
            "doc_type": "confluence_attachment",
        }
        if parent_doc:
            if "labels" in parent_doc.metadata:
                metadata["labels"] = parent_doc.metadata["labels"]
            metadata["parent_page"] = parent_doc.semantic_identifier

        version_when = attachment.get("version", {}).get("when")
        return Document(
            id=stable_att_id,
            external_id=stable_att_id,
            external_version=str(attachment.get("version", {}).get("number") or "") or None,
            etag=str(version_when or "") or None,
            sections=[TextSection(text=content.text, link=attachment_url)],
            source=DocumentSource.CONFLUENCE,
            semantic_identifier=attachment_title,
            metadata=metadata,
            doc_updated_at=(datetime_from_string(version_when) if version_when else None),
            primary_owners=parent_doc.primary_owners if parent_doc else None,
            secondary_owners=parent_doc.secondary_owners if parent_doc else None,
            external_access=parent_doc.external_access if parent_doc else None,
            source_link=attachment_url,
            parent_hierarchy_raw_node_id=stable_page_id,
            raw_storage_bucket=content.raw_storage_bucket,
            raw_storage_key=content.raw_storage_key,
            raw_storage_region=content.raw_storage_region,
            mime_type=content.mime_type,
            file_name=content.file_name,
            size_bytes=content.size_bytes,
        )

    def _fetch_page_attachments(
        self,
        page: dict[str, Any],
        parent_doc: Document | None = None,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> tuple[list[Document | HierarchyNode], list[ConnectorFailure]]:
        del start, end
        page_id = _get_page_id(page)
        stable_page_id = f"confluence::{page_id}"
        results: list[Document | HierarchyNode] = []
        failures: list[ConnectorFailure] = []

        cql = f"type=attachment and container={page_id}"
        log.info("Fetching attachments for page %s with CQL: %s", page_id, cql)

        attachment_count = 0
        try:
            for attachment in self.confluence_client.paginated_cql_retrieval(
                cql=cql, expand=_ATTACHMENT_EXPAND
            ):
                attachment_count += 1
                if attachment_count == 1:
                    page_node = self._maybe_yield_page_hierarchy_node(
                        page, stable_page_id
                    )
                    if page_node:
                        results.append(page_node)

                try:
                    document = self._convert_attachment_to_document(
                        page=page,
                        page_id=page_id,
                        attachment=attachment,
                        parent_doc=parent_doc,
                    )
                    if document is not None:
                        results.append(document)
                except Exception as exc:
                    attachment_id = str(attachment.get("id", ""))
                    attachment_title = attachment.get("title", attachment_id)
                    log.exception(
                        "Failed to process attachment %s for page %s",
                        attachment_title,
                        page_id,
                    )
                    failures.append(
                        ConnectorFailure(
                            failed_document=DocumentFailure(document_id=attachment_id),
                            failure_message=f"Failed to process attachment {attachment_title}",
                            exception=exc,
                        )
                    )
        except Exception as exc:
            log.exception("Failed to fetch or process attachments for page %s", page_id)
            failures.append(
                ConnectorFailure(
                    failed_document=DocumentFailure(document_id=page_id),
                    failure_message=f"Failed to fetch or process attachments for page {page_id}",
                    exception=exc,
                )
            )

        log.info("Found %d attachments for page %s", attachment_count, page_id)

        return results, failures

    def _build_page_retrieval_url(
        self,
        start: SecondsSinceUnixEpoch | None,
        end: SecondsSinceUnixEpoch | None,
        limit: int,
    ) -> str:
        cql = self._construct_page_cql_query(start, end)
        params = urlencode(
            {
                "cql": cql,
                "expand": _PAGE_EXPAND,
                "limit": limit,
            }
        )
        return f"rest/api/content/search?{params}"

    def fetch_page_versions(self) -> dict[str, str]:
        # Return {stable_id: version_when} for all pages without fetching body content.
        cql = self._construct_page_cql_query()
        versions: dict[str, str] = {}
        for page in self.confluence_client.paginated_cql_retrieval(
            cql=cql,
            expand=_VERSION_ONLY_EXPAND,
            limit=_SLIM_DOC_BATCH_SIZE,
        ):
            page_id = str(page.get("id", ""))
            stable_id = f"confluence::{page_id}"
            version_when = page.get("version", {}).get("when", "")
            if page_id and version_when:
                versions[stable_id] = version_when
        return versions

    def fetch_pages_by_ids(self, stable_ids: set[str]) -> list[Document]:
        # Fetch full page content for a specific subset of pages.
        raw_ids = [
            sid.removeprefix("confluence::")
            for sid in stable_ids
            if sid.startswith("confluence::")
        ]
        if not raw_ids:
            return []
        documents: list[Document] = []
        for batch_start in range(0, len(raw_ids), _DEFAULT_BATCH_SIZE):
            batch = raw_ids[batch_start : batch_start + _DEFAULT_BATCH_SIZE]
            id_filter = " or ".join(f"id={pid}" for pid in batch)
            cql = f"type=page and ({id_filter})"
            for page in self.confluence_client.paginated_cql_retrieval(
                cql=cql,
                expand=_PAGE_EXPAND,
                limit=_DEFAULT_BATCH_SIZE,
            ):
                result = self._convert_page_to_document(page)
                if isinstance(result, Document):
                    documents.append(result)
                else:
                    log.warning(
                        "Failed to convert page %s during reindex fetch: %s",
                        page.get("id"),
                        result.failure_message,
                    )
        return documents

    def _fetch_document_batches(
        self,
        checkpoint: ConfluenceCheckpoint,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> CheckpointOutput[ConfluenceCheckpoint]:
        if checkpoint.last_updated_at:
            checkpoint_start = datetime_from_string(
                checkpoint.last_updated_at
            ).timestamp()
            start = max(start or checkpoint_start, checkpoint_start)
        is_first_run = checkpoint.next_page_url is None
        cql_url = checkpoint.next_page_url or self._build_page_retrieval_url(
            start, end, self.batch_size
        )

        if is_first_run:
            space_nodes = list(self._yield_space_hierarchy_nodes())
            for start_index in range(0, len(space_nodes), self.batch_size):
                yield space_nodes[start_index : start_index + self.batch_size]

        current_batch: list[Document | HierarchyNode] = []

        def _on_next_page(url: str) -> None:
            nonlocal cql_url
            cql_url = url

        def _iterate_pages(url: str) -> Generator:
            nonlocal current_batch
            for page in self.confluence_client.paginated_page_retrieval(
                cql_url=url,
                limit=self.batch_size,
                next_page_callback=_on_next_page,
            ):
                ancestor_nodes = list(self._yield_ancestor_hierarchy_nodes(page))
                current_batch.extend(ancestor_nodes)

                page_result = self._convert_page_to_document(page)
                if isinstance(page_result, ConnectorFailure):
                    log.warning(
                        "Skipping page %s: %s",
                        page.get("id"),
                        page_result.failure_message,
                    )
                    parent_doc_for_attachments = None
                else:
                    current_batch.append(page_result)
                    parent_doc_for_attachments = page_result

                attachment_results, attachment_failures = self._fetch_page_attachments(
                    page, parent_doc_for_attachments, start, end
                )
                current_batch.extend(attachment_results)
                for failure in attachment_failures:
                    log.warning(
                        "Attachment failure on page %s: %s",
                        page.get("id"),
                        failure.failure_message,
                    )

                while len(current_batch) >= self.batch_size:
                    yield current_batch[: self.batch_size]
                    current_batch = current_batch[self.batch_size :]

        try:
            yield from _iterate_pages(cql_url)
        except Exception as exc:
            if (
                _http_status(exc) == 400
                and is_first_run
            ):
                log.info("CQL query returned 400, retrying without end-date filter")
                fallback_url = self._build_page_retrieval_url(
                    start, None, self.batch_size
                )
                try:
                    yield from _iterate_pages(fallback_url)
                except Exception:
                    log.exception("Fallback CQL query also failed")
                    raise
            else:
                log.exception("HTTP error during document batch fetch")
                raise

        if current_batch:
            yield current_batch

        completed_at = datetime.fromtimestamp(
            end if end is not None else datetime.now(timezone.utc).timestamp(),
            tz=timezone.utc,
        )
        return ConfluenceCheckpoint(
            next_page_url=None,
            last_updated_at=completed_at.isoformat(),
        )

    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: ConfluenceCheckpoint,
    ) -> CheckpointOutput[ConfluenceCheckpoint]:
        # Yield document batches from Confluence using incremental checkpoint.
        self._seen_hierarchy_node_ids = set()
        self._included_page_text_cache = {}
        self._user_display_name_cache = {}
        return (yield from self._fetch_document_batches(checkpoint, start, end))

    def build_dummy_checkpoint(self) -> ConfluenceCheckpoint:
        # Return an empty checkpoint for first-time indexing runs.
        return ConfluenceCheckpoint()

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConfluenceCheckpoint:
        # Deserialise and validate a persisted Confluence checkpoint.
        return ConfluenceCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._retrieve_all_slim_docs(
            start=start, end=end, callback=callback, include_permissions=False
        )

    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        yield from self._retrieve_all_slim_docs(
            start=start, end=end, callback=callback, include_permissions=True
        )

    def _retrieve_all_slim_docs(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        include_permissions: bool = True,
    ) -> GenerateSlimDocumentOutput:
        cql = self._construct_page_cql_query(start, end)
        batch: list[SlimDocument] = []
        for page in self.confluence_client.paginated_cql_retrieval(
            cql=cql,
            expand="space,version",
            limit=_SLIM_DOC_BATCH_SIZE,
        ):
            try:
                slim_page_id = str(page.get("id", ""))
                stable_id = f"confluence::{slim_page_id}"
                perm_sync_data: dict[str, Any] | None = None
                if include_permissions:
                    perm_sync_data = {
                        "space_key": page.get("space", {}).get("key", ""),
                        "page_id": slim_page_id,
                    }
                batch.append(SlimDocument(id=stable_id, perm_sync_data=perm_sync_data))
            except Exception:
                log.exception("Failed to create slim doc for page %s", page.get("id"))

            if len(batch) >= _SLIM_DOC_BATCH_SIZE:
                yield batch
                batch = []
                if callback:
                    callback.heartbeat()

        if batch:
            yield batch

    def validate_connector_settings(self) -> None:
        # Verify the connector can reach Confluence with current settings.
        try:
            cql = f"type=page and space='{self.space}'" if self.space else "type=page"
            list(
                self.confluence_client.paginated_cql_retrieval(
                    cql=cql, expand="version", limit=1
                )
            )
        except Exception:
            log.exception("Confluence connector settings validation failed")
            raise
