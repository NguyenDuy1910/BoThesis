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
from ..base import GenerateSlimItemOutput
from ..base import IndexingHeartbeatInterface
from ..base import SecondsSinceUnixEpoch
from ..base import SlimConnectorWithPermSync
from ..protocol import ConnectorFailure
from ..protocol import ItemFailure
from ..protocol import SlimItem
from bothesis.connector.protocol import (
    AccessPolicy,
    AnyItem,
    Chunk,
    CollectionItem,
    CollectionKind,
    DocumentItem,
    DocumentKind,
    Hierarchy,
    ImagePart,
    SourceIdentity,
    SourceProvider,
    StorageObject,
    TextPart,
)
from bothesis.connector.file import FileProcessor
from bothesis.connector.protocol import RawObjectStore
from ._confluence import FinxConfluence
from .checkpoint import ConfluenceCheckpoint
from .utils import AttachmentProcessingResult, build_confluence_document_id
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


def _attachment_storage_object(
    content: AttachmentProcessingResult,
) -> StorageObject | None:
    if not content.raw_storage_key:
        return None
    return StorageObject(
        provider=content.raw_storage_provider,
        bucket=content.raw_storage_bucket,
        region=content.raw_storage_region,
        key=content.raw_storage_key,
        file_name=content.file_name,
        size_bytes=content.size_bytes,
        content_type=content.mime_type,
        checksum_sha256=content.checksum_sha256,
    )


def _attachment_document_kind(mime_type: str | None) -> DocumentKind:
    normalized = (mime_type or "").casefold()
    if normalized.startswith("image/"):
        return DocumentKind.IMAGE
    if normalized == "application/pdf":
        return DocumentKind.PDF
    if normalized in {"text/html", "application/xhtml+xml"}:
        return DocumentKind.WEB_PAGE
    return DocumentKind.DOCUMENT


def _page_hierarchy(page: dict[str, Any]) -> Hierarchy:
    ancestors = [
        f"confluence::{ancestor.get('id', '')}"
        for ancestor in page.get("ancestors", [])
        if ancestor.get("id")
    ]
    space_key = str(page.get("space", {}).get("key") or "") or None
    parent_id = ancestors[-1] if ancestors else space_key
    return Hierarchy(
        parent_id=parent_id,
        root_id=space_key or (ancestors[0] if ancestors else None),
        ancestor_ids=ancestors,
        depth=len(ancestors) + (1 if parent_id else 0),
    )


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
        self._storage: RawObjectStore | None = None
        self._file_processor = FileProcessor()
        self._processed_chunks: dict[str, tuple[Chunk, ...]] = {}

    def set_allow_images(self, is_enabled: bool) -> None:
        # Enable or disable image attachment processing.
        self._allow_images = is_enabled

    def set_storage(self, storage: RawObjectStore) -> None:
        self._storage = storage

    async def fetch_chunks(self, item: DocumentItem) -> tuple[Chunk, ...] | None:
        """Return attachment chunks produced by the same Docling pass."""

        return self._processed_chunks.pop(item.id, None)

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

    def _yield_space_hierarchy_nodes(self) -> Generator[CollectionItem, None, None]:
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
                    yield self._collection_item(
                        raw_id,
                        space.get("name", raw_id),
                        CollectionKind.SPACE,
                    )
        except Exception:
            log.exception("Failed to fetch space hierarchy nodes")

    def _yield_ancestor_hierarchy_nodes(
        self, page: dict[str, Any]
    ) -> Generator[CollectionItem, None, None]:
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
            yield self._collection_item(
                ancestor_id,
                ancestor.get("title", str(ancestor.get("id", ""))),
                CollectionKind.COLLECTION,
                parent_id=parent_raw_id,
                root_id=space_key or None,
                ancestor_ids=[
                    f"confluence::{ancestor.get('id', '')}"
                    for ancestor in ancestors[:idx]
                    if ancestor.get("id")
                ],
                depth=idx + 1,
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
    ) -> CollectionItem | None:
        if stable_id in self._seen_hierarchy_node_ids:
            return None
        self._seen_hierarchy_node_ids.add(stable_id)
        return self._collection_item(
            stable_id,
            page.get("title", stable_id),
            CollectionKind.COLLECTION,
            parent_id=self._get_parent_hierarchy_raw_id(page),
        )

    def _collection_item(
        self,
        item_id: str,
        title: str,
        collection_kind: CollectionKind,
        *,
        parent_id: str | None = None,
        root_id: str | None = None,
        ancestor_ids: list[str] | None = None,
        depth: int = 0,
    ) -> CollectionItem:
        return CollectionItem(
            id=item_id,
            title=title or item_id,
            collection_kind=collection_kind,
            source=SourceIdentity(
                connector_id=self._connector_id(),
                provider=SourceProvider.CONFLUENCE,
                external_id=item_id,
            ),
            hierarchy=Hierarchy(
                parent_id=parent_id,
                root_id=root_id,
                ancestor_ids=ancestor_ids or [],
                depth=depth,
            ),
        )

    def _connector_id(self) -> str:
        return (
            self._credentials_provider.get_provider_key()
            if self._credentials_provider is not None
            else SourceProvider.CONFLUENCE.value
        )

    def _normalized_page_soup(self, page: dict[str, Any]) -> Any:
        body = page.get("body", {})
        html = body.get("storage", body.get("view", {})).get("value", "")
        if not html:
            return None

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:
            raise RuntimeError(
                "Confluence HTML extraction requires the optional 'beautifulsoup4' package"
            ) from exc

        soup = BeautifulSoup(html, "html.parser")
        _remove_macro_stylings(soup)

        for user_tag in soup.find_all("ri:user"):
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
                user_tag.replace_with(f"@{display_name}")

        for macro in soup.find_all("ac:structured-macro"):
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
                    macro.replace_with(cached_text)
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
                    macro.replace_with(included_text)
            except Exception:
                log.exception("Failed to expand included page '%s'", page_title)

        for link_body in soup.find_all("ac:link-body"):
            try:
                link_body.replace_with(f"(LINK TEXT: {link_body.text})")
            except Exception:
                log.exception("Failed to process link body")

        for attachment_ref in soup.find_all("ri:attachment"):
            try:
                filename = _sanitize_attachment_filename(
                    attachment_ref.attrs.get("ri:filename", "")
                )
                attachment_ref.replace_with(f"<attachment>{filename}</attachment>")
            except Exception:
                log.exception("Failed to process attachment reference")

        return soup

    def _extract_page_text(self, page: dict[str, Any]) -> str:
        soup = self._normalized_page_soup(page)
        return _format_soup_text(soup) if soup is not None else ""

    def _extract_page_html(self, page: dict[str, Any]) -> str:
        """Retain normalized HTML structure for Docling conversion."""

        soup = self._normalized_page_soup(page)
        return str(soup) if soup is not None else ""

    def _fetch_page_restrictions(
        self, page_id: str, space_key: str
    ) -> AccessPolicy | None:
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
                return AccessPolicy.from_reader_ids([space_key] if space_key else [])

            return AccessPolicy.from_reader_ids(
                [
                    *(f"email:{email}" for email in user_emails),
                    *(f"external_group:{group_id}" for group_id in group_ids),
                ]
            )
        except Exception:
            log.exception("Failed to fetch restrictions for page %s", page_id)
            return None

    def _fetch_secondary_owners(
        self, page_id: str, primary_email: str | None
    ) -> list[str]:
        try:
            data = self.confluence_client.get_page_owner_and_contributors(page_id)
            seen_names: set[str] = set()
            secondary: list[str] = []

            creator = data.get("history", {}).get("createdBy", {})
            if creator:
                creator_name = creator.get("displayName", "")
                creator_email = creator.get("email")
                if creator_name and creator_name not in seen_names:
                    if not primary_email or creator_email != primary_email:
                        seen_names.add(creator_name)
                        secondary.append(creator_email or creator_name)

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
                        secondary.append(email or name)

            return secondary
        except Exception:
            log.exception("Failed to fetch contributors for page %s", page_id)
            return []

    def _convert_page_to_document(
        self, page: dict[str, Any]
    ) -> DocumentItem | ConnectorFailure:
        page_id = ""
        page_url = ""
        try:
            page_id = _get_page_id(page)
            page_title = page["title"]
            page_url = build_confluence_document_id(
                self.wiki_base, page["_links"]["webui"], self.is_cloud
            )
            stable_id = f"confluence::{page_id}"
            self._processed_chunks.pop(stable_id, None)

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

            primary_owners: list[str] = []
            version_by = page.get("version", {}).get("by", {})
            primary_email: str | None = None
            if version_by:
                primary_email = version_by.get("email")
                primary_owners.append(
                    primary_email or version_by.get("displayName", "Unknown")
                )

            secondary_owners = self._fetch_secondary_owners(page_id, primary_email)
            page_access = self._fetch_page_restrictions(
                page_id, str(page.get("space", {}).get("key") or "")
            )

            if primary_owners:
                metadata["primary_owners"] = primary_owners
            if secondary_owners:
                metadata["secondary_owners"] = secondary_owners
            source = SourceIdentity(
                connector_id=self._connector_id(),
                provider=SourceProvider.CONFLUENCE,
                external_id=stable_id,
                external_version=(
                    str(page.get("version", {}).get("number") or "") or None
                ),
                etag=str(page.get("version", {}).get("when") or "") or None,
                url=page_url,
            )
            processed = self._file_processor.process_bytes(
                self._extract_page_html(page).encode("utf-8"),
                file_name=f"{page_id}.html",
                item_id=stable_id,
                title=page_title,
                source=source,
                document_kind=DocumentKind.PAGE,
                hierarchy=_page_hierarchy(page),
                access=page_access or AccessPolicy(),
                metadata=metadata,
            )
            self._processed_chunks[stable_id] = processed.chunks
            return processed.item.model_copy(
                update={
                    "updated_at": datetime_from_string(page["version"]["when"]),
                    "created_at": (
                        datetime_from_string(page["history"]["createdDate"])
                        if page.get("history", {}).get("createdDate")
                        else None
                    ),
                }
            )
        except Exception:
            log.exception("Failed to convert page %s", page_id)
            return ConnectorFailure(
                failed_item=ItemFailure(
                    item_id=page_id,
                    item_url=page_url,
                ),
                failure_message=f"Failed to convert page {page_id}",
            )

    def _convert_attachment_to_document(
        self,
        *,
        page: dict[str, Any],
        page_id: str,
        attachment: dict[str, Any],
        parent_doc: DocumentItem | None,
    ) -> AnyItem | None:
        attachment_id = str(attachment.get("id", ""))
        attachment_title = attachment.get("title", attachment_id)
        stable_page_id = f"confluence::{page_id}"
        stable_att_id = f"{stable_page_id}::att::{attachment_id}"
        self._processed_chunks.pop(stable_att_id, None)
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
            processor=self._file_processor,
        )
        if content is None:
            return None

        metadata: dict[str, str | list[str]] = {
            "space": page.get("space", {}).get("name", ""),
            "space_key": page.get("space", {}).get("key", ""),
            "attachment_id": attachment_id,
            "parent_content_id": stable_page_id,
            "doc_type": "confluence_attachment",
        }
        version_when = attachment.get("version", {}).get("when")
        if parent_doc:
            if "labels" in parent_doc.metadata:
                metadata["labels"] = parent_doc.metadata["labels"]
            metadata["parent_page"] = parent_doc.title
        metadata.update(
            {
                key: str(value)
                for key, value in {
                    "raw_storage_bucket": content.raw_storage_bucket,
                    "raw_storage_provider": content.raw_storage_provider,
                    "raw_storage_key": content.raw_storage_key,
                    "raw_storage_region": content.raw_storage_region,
                    "file_name": content.file_name,
                    "mime_type": content.mime_type,
                    "size_bytes": content.size_bytes,
                }.items()
                if value is not None
            }
        )

        original = _attachment_storage_object(content)
        if not content.text:
            if not content.mime_type or not content.mime_type.startswith("image/"):
                return None
            item = DocumentItem(
                id=stable_att_id,
                title=attachment_title,
                source=SourceIdentity(
                    connector_id=self._connector_id(),
                    provider=SourceProvider.CONFLUENCE,
                    external_id=stable_att_id,
                    external_version=str(attachment.get("version", {}).get("number") or "") or None,
                    etag=str(attachment.get("version", {}).get("when") or "") or None,
                    url=attachment_url,
                ),
                hierarchy=Hierarchy(parent_id=stable_page_id, root_id=stable_page_id, depth=1),
                access=parent_doc.access if parent_doc else AccessPolicy(),
                metadata=metadata,
                updated_at=(datetime_from_string(version_when) if version_when else None),
                document_kind=DocumentKind.IMAGE,
                content=(
                    content.content
                    or [
                        ImagePart(
                            element_id=f"{stable_att_id}::image",
                            url=attachment_url,
                            storage=content.raw_storage_key,
                            alt_text=attachment_title,
                        )
                    ]
                ),
                original=original,
            )
        else:
            item = DocumentItem(
                id=stable_att_id,
                title=attachment_title,
                source=SourceIdentity(
                    connector_id=self._connector_id(),
                    provider=SourceProvider.CONFLUENCE,
                    external_id=stable_att_id,
                    external_version=str(attachment.get("version", {}).get("number") or "") or None,
                    etag=str(version_when or "") or None,
                    url=attachment_url,
                ),
                hierarchy=Hierarchy(parent_id=stable_page_id, root_id=stable_page_id, depth=1),
                access=parent_doc.access if parent_doc else AccessPolicy(),
                metadata=metadata,
                updated_at=(datetime_from_string(version_when) if version_when else None),
                document_kind=_attachment_document_kind(content.mime_type),
                content=(
                    content.content
                    or [TextPart(text=content.text, link=attachment_url)]
                ),
                original=original,
            )

        if content.chunks:
            self._processed_chunks[stable_att_id] = tuple(
                chunk
                if (
                    chunk.item_id == stable_att_id
                    and chunk.id == f"{stable_att_id}:{chunk.chunk_index}"
                )
                else chunk.model_copy(
                    update={
                        "id": f"{stable_att_id}:{chunk.chunk_index}",
                        "item_id": stable_att_id,
                    }
                )
                for chunk in content.chunks
            )
        return item

    def _fetch_page_attachments(
        self,
        page: dict[str, Any],
        parent_doc: DocumentItem | None = None,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
    ) -> tuple[list[AnyItem], list[ConnectorFailure]]:
        del start, end
        page_id = _get_page_id(page)
        stable_page_id = f"confluence::{page_id}"
        results: list[AnyItem] = []
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
                            failed_item=ItemFailure(item_id=attachment_id),
                            failure_message=f"Failed to process attachment {attachment_title}",
                            exception=exc,
                        )
                    )
        except Exception as exc:
            log.exception("Failed to fetch or process attachments for page %s", page_id)
            failures.append(
                ConnectorFailure(
                    failed_item=ItemFailure(item_id=page_id),
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

    def fetch_pages_by_ids(self, stable_ids: set[str]) -> list[DocumentItem]:
        # Fetch full page content for a specific subset of pages.
        raw_ids = [
            sid.removeprefix("confluence::")
            for sid in stable_ids
            if sid.startswith("confluence::")
        ]
        if not raw_ids:
            return []
        documents: list[DocumentItem] = []
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
                if isinstance(result, DocumentItem):
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

        current_batch: list[AnyItem] = []

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
        self._processed_chunks.clear()
        return (yield from self._fetch_document_batches(checkpoint, start, end))

    def build_dummy_checkpoint(self) -> ConfluenceCheckpoint:
        # Return an empty checkpoint for first-time indexing runs.
        return ConfluenceCheckpoint()

    def validate_checkpoint_json(self, checkpoint_json: str) -> ConfluenceCheckpoint:
        # Deserialise and validate a persisted Confluence checkpoint.
        return ConfluenceCheckpoint.model_validate_json(checkpoint_json)

    def retrieve_all_slim_items(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimItemOutput:
        yield from self._retrieve_all_slim_items(
            start=start, end=end, callback=callback, include_permissions=False
        )

    def retrieve_all_slim_items_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimItemOutput:
        yield from self._retrieve_all_slim_items(
            start=start, end=end, callback=callback, include_permissions=True
        )

    def _retrieve_all_slim_items(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
        include_permissions: bool = True,
    ) -> GenerateSlimItemOutput:
        cql = self._construct_page_cql_query(start, end)
        batch: list[SlimItem] = []
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
                batch.append(SlimItem(id=stable_id, permission_data=perm_sync_data))
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
