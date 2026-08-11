from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from typing import cast
from urllib.parse import quote

from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field
from pydantic import field_validator

INDEX_SEPARATOR = "==="
RETURN_SEPARATOR = "\n\r\n"


def make_url_compatible(value: str) -> str:
    """Return the stable URL-safe identifier format used by older indexes."""

    return quote(value.replace(" ", "_"), safe="")


def _set_values(value: Any) -> list[Any] | set[Any] | tuple[Any, ...]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, (list, set, tuple)):
        return value
    raise TypeError("ACL values must be a string or collection")

class DocumentSource(str, Enum):
    SLACK = "slack"
    CONFLUENCE = "confluence"
    FILE = "file"
    GOOGLE_DRIVE = "google_drive"
    JIRA = "jira"
    NOTION = "notion"


class Section(BaseModel):
    model_config = ConfigDict(extra="forbid")

    link: str | None = None
    text: str | None = None
    image_file_id: str | None = None


class TextSection(Section):
    text: str


class ImageSection(Section):
    image_file_id: str


class BasicExpertInfo(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    email: str | None = None
    username: str | None = None


class ExternalAccess(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_emails: set[str] = Field(default_factory=set)
    user_group_ids: set[str] = Field(default_factory=set)
    source_reader_ids: set[str] = Field(default_factory=set)
    is_public: bool = False

    @field_validator("user_emails", mode="before")
    @classmethod
    def _normalise_emails(cls, value: Any) -> set[str]:
        return {
            str(item).strip().lower()
            for item in _set_values(value)
            if str(item).strip()
        }

    @field_validator("user_group_ids", mode="before")
    @classmethod
    def _normalise_group_ids(cls, value: Any) -> set[str]:
        return {str(item).strip() for item in _set_values(value) if str(item).strip()}

    @field_validator("source_reader_ids", mode="before")
    @classmethod
    def _normalise_source_reader_ids(cls, value: Any) -> set[str]:
        return {
            str(item).strip().lower()
            for item in _set_values(value)
            if str(item).strip()
        }


def convert_metadata_dict_to_list_of_strings(
    metadata: dict[str, str | list[str]],
) -> list[str]:
    # Flatten a metadata dict into a list of key-value separator strings.
    attributes: list[str] = []
    for k, v in metadata.items():
        if isinstance(v, list):
            attributes.extend([k + INDEX_SEPARATOR + vi for vi in v])
        else:
            attributes.append(k + INDEX_SEPARATOR + v)
    return attributes


def convert_metadata_list_of_strings_to_dict(
    metadata_list: list[str],
) -> dict[str, str | list[str]]:
    # Reconstruct a metadata dict from separator-encoded strings.
    metadata: dict[str, str | list[str]] = {}
    for item in metadata_list:
        if INDEX_SEPARATOR not in item:
            raise ValueError(f"Invalid encoded metadata item: {item!r}")
        key, value = item.split(INDEX_SEPARATOR, 1)
        if key in metadata:
            # We have already seen this key therefore it must point to a list.
            if isinstance(metadata[key], list):
                cast(list[str], metadata[key]).append(value)
            else:
                metadata[key] = [cast(str, metadata[key]), value]
        else:
            metadata[key] = value
    return metadata

class DocumentBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    sections: list[TextSection | ImageSection]
    source: DocumentSource | None = None
    semantic_identifier: str
    metadata: dict[str, str | list[str]]

    @field_validator("metadata", mode="before")
    @classmethod
    def _coerce_metadata_values(cls, v: Any) -> dict[str, str | list[str]]:
        if v is None:
            return {}
        if not isinstance(v, dict):
            raise TypeError("metadata must be a mapping")
        return {
            str(key): [str(item) for item in val] if isinstance(val, list) else str(val)
            for key, val in v.items()
        }

    doc_updated_at: datetime | None = None
    doc_created_at: datetime | None = None
    primary_owners: list[BasicExpertInfo] | None = None
    secondary_owners: list[BasicExpertInfo] | None = None
    title: str | None = None
    source_link: str | None = None
    external_access: ExternalAccess | None = None
    parent_hierarchy_raw_node_id: str | None = None
    external_id: str | None = None
    external_version: str | None = None
    etag: str | None = None
    raw_storage_bucket: str | None = None
    raw_storage_key: str | None = None
    raw_storage_region: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None

    def get_title_for_document_index(self) -> str | None:
        # Return a sanitised title suitable for the document index.
        if self.title == "":
            return None
        replace_chars = set(RETURN_SEPARATOR)
        title = self.semantic_identifier if self.title is None else self.title
        for char in replace_chars:
            title = title.replace(char, " ")
        return title.strip()

    def get_metadata_str_attributes(self) -> list[str] | None:
        # Return metadata as a flat list of separator-encoded strings.
        if not self.metadata:
            return None
        return convert_metadata_dict_to_list_of_strings(self.metadata)

    def get_text_content(self) -> str:
        # Concatenate all section texts into a single string.
        return "\n\n".join(
            section.text.strip()
            for section in self.sections
            if section.text and section.text.strip()
        )

class Document(DocumentBase):
    id: str
    source: DocumentSource

    @classmethod
    def from_base(cls, base: DocumentBase) -> Document:
        # Construct a Document from a DocumentBase, generating an ID if absent.
        if base.source is None:
            raise ValueError("DocumentBase.source is required")
        return cls(
            id=(
                make_url_compatible(base.id)
                if base.id
                else "ingestion_api_" + make_url_compatible(base.semantic_identifier)
            ),
            sections=base.sections,
            source=base.source,
            semantic_identifier=base.semantic_identifier,
            metadata=base.metadata,
            doc_updated_at=base.doc_updated_at,
            doc_created_at=base.doc_created_at,
            primary_owners=base.primary_owners,
            secondary_owners=base.secondary_owners,
            title=base.title,
            source_link=base.source_link,
            external_access=base.external_access,
            parent_hierarchy_raw_node_id=base.parent_hierarchy_raw_node_id,
            external_id=base.external_id,
            external_version=base.external_version,
            etag=base.etag,
            raw_storage_bucket=base.raw_storage_bucket,
            raw_storage_key=base.raw_storage_key,
            raw_storage_region=base.raw_storage_region,
            mime_type=base.mime_type,
            file_name=base.file_name,
            size_bytes=base.size_bytes,
        )


class ConnectorCheckpoint(BaseModel):
    """Base checkpoint that every connector-specific checkpoint extends.

    Serialised as JSON and persisted to Postgres between indexing runs so
    that subsequent runs can resume where the previous run left off.
    """

    model_config = ConfigDict(extra="forbid")


class SourceCheckpoint(ConnectorCheckpoint):
    """Generic cursor for APIs that use modified timestamps."""

    updated_at: str | None = None
    cursor: str | None = None


class ConnectorScope(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope_type: str = Field(min_length=1)
    scope_value: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)


class SourceChangeType(str, Enum):
    UPSERT = "upsert"
    DELETE = "delete"


class SourceChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    change_type: SourceChangeType = SourceChangeType.UPSERT
    external_version: str | None = None
    etag: str | None = None
    last_modified_at: datetime | None = None


class SourceACL(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_emails: set[str] = Field(default_factory=set)
    user_group_ids: set[str] = Field(default_factory=set)
    source_reader_ids: set[str] = Field(default_factory=set)
    is_public: bool = False

    @field_validator("user_emails", mode="before")
    @classmethod
    def _normalise_emails(cls, value: Any) -> set[str]:
        return {
            str(item).strip().lower()
            for item in _set_values(value)
            if str(item).strip()
        }

    @field_validator("user_group_ids", mode="before")
    @classmethod
    def _normalise_group_ids(cls, value: Any) -> set[str]:
        return {str(item).strip() for item in _set_values(value) if str(item).strip()}

    @field_validator("source_reader_ids", mode="before")
    @classmethod
    def _normalise_source_reader_ids(cls, value: Any) -> set[str]:
        return {
            str(item).strip().lower()
            for item in _set_values(value)
            if str(item).strip()
        }

    def to_reader_ids(self) -> list[str]:
        """Return the canonical reader IDs stored in the Qdrant ACL field."""

        readers = {
            *(f"email:{email}" for email in self.user_emails),
            *(f"external_group:{group_id.lower()}" for group_id in self.user_group_ids),
            *self.source_reader_ids,
        }
        if self.is_public:
            readers.add("public")
        return sorted(readers)

    @classmethod
    def from_external_access(cls, access: ExternalAccess | None) -> SourceACL:
        if access is None:
            return cls()
        return cls(
            user_emails=access.user_emails,
            user_group_ids=access.user_group_ids,
            source_reader_ids=access.source_reader_ids,
            is_public=access.is_public,
        )

    def to_external_access(self) -> ExternalAccess:
        return ExternalAccess(
            user_emails=self.user_emails,
            user_group_ids=self.user_group_ids,
            source_reader_ids=self.source_reader_ids,
            is_public=self.is_public,
        )


class SourceDocument(BaseModel):
    """Normalized source document returned by all connector adapters."""

    model_config = ConfigDict(extra="forbid")

    external_id: str = Field(min_length=1)
    source: DocumentSource
    semantic_identifier: str
    sections: list[TextSection | ImageSection]
    metadata: dict[str, str | list[str]] = Field(default_factory=dict)
    title: str | None = None
    source_link: str | None = None
    external_version: str | None = None
    etag: str | None = None
    doc_updated_at: datetime | None = None
    doc_created_at: datetime | None = None
    primary_owners: list[BasicExpertInfo] | None = None
    secondary_owners: list[BasicExpertInfo] | None = None
    parent_hierarchy_raw_node_id: str | None = None
    acl: SourceACL = Field(default_factory=SourceACL)
    raw_storage_bucket: str | None = None
    raw_storage_key: str | None = None
    raw_storage_region: str | None = None
    mime_type: str | None = None
    file_name: str | None = None
    size_bytes: int | None = None

    def get_text_content(self) -> str:
        return "\n\n".join(
            section.text.strip()
            for section in self.sections
            if section.text and section.text.strip()
        )

    @classmethod
    def from_document(cls, document: Document) -> SourceDocument:
        return cls(
            external_id=document.external_id or document.id,
            source=document.source,
            semantic_identifier=document.semantic_identifier,
            sections=document.sections,
            metadata=document.metadata,
            title=document.title,
            source_link=document.source_link,
            external_version=document.external_version,
            etag=document.etag,
            doc_updated_at=document.doc_updated_at,
            doc_created_at=document.doc_created_at,
            primary_owners=document.primary_owners,
            secondary_owners=document.secondary_owners,
            parent_hierarchy_raw_node_id=document.parent_hierarchy_raw_node_id,
            acl=SourceACL.from_external_access(document.external_access),
            raw_storage_bucket=document.raw_storage_bucket,
            raw_storage_key=document.raw_storage_key,
            raw_storage_region=document.raw_storage_region,
            mime_type=document.mime_type,
            file_name=document.file_name,
            size_bytes=document.size_bytes,
        )

    def to_document(self) -> Document:
        return Document(
            id=self.external_id,
            source=self.source,
            sections=self.sections,
            semantic_identifier=self.semantic_identifier,
            metadata=self.metadata,
            title=self.title,
            source_link=self.source_link,
            external_access=self.acl.to_external_access(),
            parent_hierarchy_raw_node_id=self.parent_hierarchy_raw_node_id,
            external_id=self.external_id,
            external_version=self.external_version,
            etag=self.etag,
            doc_updated_at=self.doc_updated_at,
            doc_created_at=self.doc_created_at,
            primary_owners=self.primary_owners,
            secondary_owners=self.secondary_owners,
            raw_storage_bucket=self.raw_storage_bucket,
            raw_storage_key=self.raw_storage_key,
            raw_storage_region=self.raw_storage_region,
            mime_type=self.mime_type,
            file_name=self.file_name,
            size_bytes=self.size_bytes,
        )


class HierarchyNodeType(str, Enum):
    SPACE = "space"
    FOLDER = "folder"
    PAGE = "page"


class HierarchyNode(BaseModel):
    model_config = ConfigDict(extra="forbid")

    raw_node_id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    node_type: HierarchyNodeType
    parent_raw_node_id: str | None = None


class SlimDocument(BaseModel):
    id: str
    perm_sync_data: dict[str, Any] | None = None
    external_access: ExternalAccess | None = None


class DocumentFailure(BaseModel):
    document_id: str
    document_link: str | None = None


class ConnectorFailure(BaseModel):
    failed_document: DocumentFailure | None = None
    failure_message: str
    exception: Exception | None = None

    model_config = {"arbitrary_types_allowed": True}
