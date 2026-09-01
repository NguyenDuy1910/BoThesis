"""PostgreSQL models for durable BoThesis business and domain state.

Canonical knowledge and authorization live here. Original bytes remain in
S3/R2, while chunks and retrieval representations remain in Qdrant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    DDL,
    event,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PG_UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

JsonObject = dict[str, Any]

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), primary_key=True, default=uuid4
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class TimestampMixin(CreatedAtMixin):
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def _json_object_column() -> Any:
    return mapped_column(
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )


def _text_array_column() -> Any:
    return mapped_column(
        ARRAY(Text),
        nullable=False,
        default=list,
        server_default=text("'{}'::text[]"),
    )


class User(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "users"

    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    preferences: Mapped[JsonObject] = _json_object_column()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant_memberships: Mapped[list[TenantMembership]] = relationship(
        back_populates="user"
    )
    conversations: Mapped[list[Conversation]] = relationship(back_populates="user")
    memories: Mapped[list[Memory]] = relationship(back_populates="user")
    group_memberships: Mapped[list[GroupMembership]] = relationship(
        back_populates="user"
    )
    created_integration_connections: Mapped[list[IntegrationConnection]] = relationship(
        back_populates="created_by_user",
        foreign_keys="IntegrationConnection.created_by_user_id",
    )
    created_items: Mapped[list[Item]] = relationship(
        back_populates="created_by_user", foreign_keys="Item.created_by_user_id"
    )
    created_collection_access: Mapped[list[CollectionAccess]] = relationship(
        back_populates="created_by_user"
    )
    access_requests: Mapped[list[AccessRequest]] = relationship(
        back_populates="requester_user",
        foreign_keys="AccessRequest.requester_user_id",
    )
    reviewed_access_requests: Mapped[list[AccessRequest]] = relationship(
        back_populates="reviewed_by_user",
        foreign_keys="AccessRequest.reviewed_by_user_id",
    )
    audit_events: Mapped[list[AuditLog]] = relationship(back_populates="actor_user")


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    settings: Mapped[JsonObject] = _json_object_column()

    roles: Mapped[list[Role]] = relationship(back_populates="tenant")
    memberships: Mapped[list[TenantMembership]] = relationship(back_populates="tenant")
    groups: Mapped[list[Group]] = relationship(back_populates="tenant")
    conversations: Mapped[list[Conversation]] = relationship(back_populates="tenant")
    memories: Mapped[list[Memory]] = relationship(back_populates="tenant")
    integration_connections: Mapped[list[IntegrationConnection]] = relationship(
        back_populates="tenant"
    )
    items: Mapped[list[Item]] = relationship(back_populates="tenant")
    access_requests: Mapped[list[AccessRequest]] = relationship(back_populates="tenant")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="tenant")


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    permission_codes: Mapped[list[str]] = _text_array_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )

    tenant: Mapped[Tenant] = relationship(back_populates="roles")
    memberships: Mapped[list[TenantMembership]] = relationship(back_populates="role")


class TenantMembership(TimestampMixin, Base):
    __tablename__ = "tenant_memberships"
    __table_args__ = (Index(None, "tenant_id", "status"), Index(None, "role_id"))

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="tenant_memberships")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")
    role: Mapped[Role] = relationship(back_populates="memberships")


class Group(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("tenant_id", "code"),
        Index(None, "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="groups")
    memberships: Mapped[list[GroupMembership]] = relationship(back_populates="group")


class GroupMembership(TimestampMixin, Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        Index(None, "user_id", "status"),
        Index(None, "group_id", "status"),
    )

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("groups.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    group: Mapped[Group] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="group_memberships")


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(None, "tenant_id", "user_id", "updated_at"),
        Index(None, "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    title: Mapped[str | None] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text)
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[JsonObject] = _json_object_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="conversations")
    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(back_populates="conversation")
    memories: Mapped[list[Memory]] = relationship(back_populates="conversation")


class Message(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "sequence_number"),)

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    sequence_number: Mapped[int] = mapped_column(BigInteger, nullable=False)

    conversation: Mapped[Conversation] = relationship(back_populates="messages")
    sourced_memories: Mapped[list[Memory]] = relationship(back_populates="source_message")
    item_links: Mapped[list[MessageItem]] = relationship(back_populates="message")


class Memory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index(None, "tenant_id", "user_id", "status"),
        Index(None, "tenant_id", "user_id", "memory_key"),
        Index(None, "conversation_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id")
    )
    memory_type: Mapped[str] = mapped_column(String(32), nullable=False)
    memory_key: Mapped[str | None] = mapped_column(String(255))
    content: Mapped[str] = mapped_column(Text, nullable=False)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    source_message_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("messages.id")
    )
    importance: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="memories")
    user: Mapped[User] = relationship(back_populates="memories")
    conversation: Mapped[Conversation | None] = relationship(back_populates="memories")
    source_message: Mapped[Message | None] = relationship(
        back_populates="sourced_memories"
    )


class IntegrationConnection(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integration_connections"
    __table_args__ = (
        Index(None, "tenant_id", "connector_key", "status"),
        Index(None, "owner_user_id", "status"),
        UniqueConstraint("tenant_id", "display_name"),
        CheckConstraint(
            "(owner_type = 'tenant' AND owner_user_id IS NULL) OR "
            "(owner_type = 'user' AND owner_user_id IS NOT NULL)",
            name="owner_matches_type",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    connector_key: Mapped[str] = mapped_column(String(64), nullable=False)
    owner_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="tenant", server_default="tenant"
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    config: Mapped[JsonObject] = _json_object_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="integration_connections")
    created_by_user: Mapped[User | None] = relationship(
        back_populates="created_integration_connections",
        foreign_keys=[created_by_user_id],
    )
    credential: Mapped[IntegrationCredential | None] = relationship(
        back_populates="integration_connection", uselist=False
    )
    ingestion_sources: Mapped[list[IngestionSource]] = relationship(
        back_populates="integration_connection"
    )


class IntegrationCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "integration_credentials"

    integration_connection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("integration_connections.id"),
        nullable=False,
        unique=True,
    )
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    key_version: Mapped[str | None] = mapped_column(String(64))

    integration_connection: Mapped[IntegrationConnection] = relationship(
        back_populates="credential"
    )


class Item(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "items"
    __table_args__ = (
        Index(None, "tenant_id"),
        Index(None, "tenant_id", "status"),
        Index(None, "parent_item_id"),
        CheckConstraint(
            "item_type IN ('collection', 'document')", name="item_type_is_valid"
        ),
        CheckConstraint(
            "(item_type = 'collection' AND document_type IS NULL) OR "
            "(item_type = 'document' AND document_type IS NOT NULL)",
            name="item_document_type_matches_type",
        ),
        CheckConstraint(
            "item_type = 'collection' OR parent_item_id IS NOT NULL",
            name="document_requires_parent",
        ),
        CheckConstraint(
            "(parent_item_id IS NULL AND parent_relation IS NULL) OR "
            "(parent_item_id IS NOT NULL AND parent_relation IS NOT NULL)",
            name="item_parent_relation_matches_parent",
        ),
        CheckConstraint(
            "parent_item_id IS NULL OR parent_item_id <> id",
            name="item_cannot_parent_itself",
        ),
        CheckConstraint(
            "parent_relation IS NULL OR parent_relation IN "
            "('contains', 'child', 'attachment', 'embedded')",
            name="item_parent_relation_is_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed', "
            "'unsupported', 'deleted')",
            name="item_status_is_valid",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="item_size_is_valid"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    parent_item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id")
    )
    parent_relation: Mapped[str | None] = mapped_column(String(32))
    document_type: Mapped[str | None] = mapped_column(String(64))
    title: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    inherit_access: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="items")
    created_by_user: Mapped[User | None] = relationship(
        back_populates="created_items", foreign_keys=[created_by_user_id]
    )
    parent_item: Mapped[Item | None] = relationship(
        back_populates="child_items", foreign_keys=[parent_item_id], remote_side="Item.id"
    )
    child_items: Mapped[list[Item]] = relationship(
        back_populates="parent_item", foreign_keys=[parent_item_id]
    )
    access_grants: Mapped[list[CollectionAccess]] = relationship(back_populates="item")
    targeted_by_ingestion_sources: Mapped[list[IngestionSource]] = relationship(
        back_populates="target_item"
    )
    external_resources: Mapped[list[ExternalResource]] = relationship(
        back_populates="item"
    )
    upload: Mapped[ItemUpload | None] = relationship(back_populates="item", uselist=False)
    message_links: Mapped[list[MessageItem]] = relationship(back_populates="item")
    citations: Mapped[list[Citation]] = relationship(back_populates="item")


class Citation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Canonical chunk citation geometry for one durable Item."""

    __tablename__ = "citations"
    __table_args__ = (
        UniqueConstraint("item_id", "chunk_id"),
        Index(None, "item_id", "deleted_at"),
        CheckConstraint(
            "page_start IS NULL OR page_start >= 1",
            name="page_start_is_valid",
        ),
        CheckConstraint(
            "page_end IS NULL OR page_end >= 1",
            name="page_end_is_valid",
        ),
        CheckConstraint(
            "page_start IS NULL OR page_end IS NULL OR page_end >= page_start",
            name="page_range_is_valid",
        ),
        CheckConstraint("jsonb_typeof(spans) = 'array'", name="spans_is_array"),
    )

    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    chunk_id: Mapped[str] = mapped_column(Text, nullable=False)
    section_path: Mapped[list[str]] = _text_array_column()
    anchor: Mapped[str | None] = mapped_column(Text)
    page_start: Mapped[int | None] = mapped_column(Integer)
    page_end: Mapped[int | None] = mapped_column(Integer)
    spans: Mapped[list[JsonObject]] = mapped_column(
        JSONB,
        nullable=False,
        default=list,
        server_default=text("'[]'::jsonb"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    item: Mapped[Item] = relationship(back_populates="citations")


class CollectionAccess(TimestampMixin, Base):
    __tablename__ = "collection_access"
    __table_args__ = (
        Index(None, "principal_type", "principal_id"),
        Index(None, "item_id", "deleted_at"),
        CheckConstraint(
            "principal_type IN ('user', 'group')", name="principal_type_is_valid"
        ),
        CheckConstraint("role IN ('owner', 'editor', 'viewer')", name="role_is_valid"),
    )

    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), primary_key=True
    )
    principal_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    principal_id: Mapped[UUID] = mapped_column(PG_UUID(as_uuid=True), primary_key=True)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    item: Mapped[Item] = relationship(back_populates="access_grants")
    created_by_user: Mapped[User | None] = relationship(
        back_populates="created_collection_access"
    )


class IngestionSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "ingestion_sources"
    __table_args__ = (
        Index(None, "integration_connection_id", "status"),
        Index(None, "target_item_id", "status"),
    )

    integration_connection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("integration_connections.id"), nullable=False
    )
    target_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(255))
    config: Mapped[JsonObject] = _json_object_column()
    checkpoint: Mapped[JsonObject] = _json_object_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    last_ingested_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    integration_connection: Mapped[IntegrationConnection] = relationship(
        back_populates="ingestion_sources"
    )
    target_item: Mapped[Item] = relationship(
        back_populates="targeted_by_ingestion_sources"
    )
    external_resources: Mapped[list[ExternalResource]] = relationship(
        back_populates="ingestion_source"
    )


class ExternalResource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "external_resources"
    __table_args__ = (
        UniqueConstraint("ingestion_source_id", "external_id"),
        Index(None, "item_id"),
        Index(None, "ingestion_source_id", "last_seen_at"),
    )

    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    ingestion_source_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("ingestion_sources.id"), nullable=False
    )
    external_id: Mapped[str] = mapped_column(Text, nullable=False)
    external_version: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    external_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    source_url: Mapped[str | None] = mapped_column(Text)
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    item: Mapped[Item] = relationship(back_populates="external_resources")
    ingestion_source: Mapped[IngestionSource] = relationship(
        back_populates="external_resources"
    )


class ItemUpload(TimestampMixin, Base):
    __tablename__ = "item_uploads"
    __table_args__ = (
        UniqueConstraint("tenant_id", "owner_user_id", "idempotency_key"),
        CheckConstraint(
            "status IN ('pending', 'available', 'failed')",
            name="item_upload_status_is_valid",
        ),
    )

    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    owner_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    idempotency_key: Mapped[str] = mapped_column(String(128), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    uploaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    item: Mapped[Item] = relationship(back_populates="upload")


class MessageItem(CreatedAtMixin, Base):
    __tablename__ = "message_items"
    __table_args__ = (Index(None, "item_id"), Index(None, "message_id", "deleted_at"))

    message_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("messages.id"), primary_key=True
    )
    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), primary_key=True
    )
    relation_type: Mapped[str] = mapped_column(String(16), primary_key=True)
    position: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    message: Mapped[Message] = relationship(back_populates="item_links")
    item: Mapped[Item] = relationship(back_populates="message_links")


class AccessRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "access_requests"
    __table_args__ = (
        Index(None, "tenant_id", "status", "created_at"),
        Index(None, "requester_user_id", "status"),
        CheckConstraint(
            "requested_role IN ('owner', 'editor', 'viewer')",
            name="requested_role_is_valid",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    requester_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    collection_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    requested_role: Mapped[str] = mapped_column(String(16), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="access_requests")
    requester_user: Mapped[User] = relationship(
        back_populates="access_requests", foreign_keys=[requester_user_id]
    )
    reviewed_by_user: Mapped[User | None] = relationship(
        back_populates="reviewed_access_requests", foreign_keys=[reviewed_by_user_id]
    )


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index(None, "tenant_id", "created_at"),
        Index(None, "tenant_id", "action", "created_at"),
        Index(None, "actor_user_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(512))
    outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success", server_default="success"
    )
    details: Mapped[JsonObject] = _json_object_column()

    tenant: Mapped[Tenant] = relationship(back_populates="audit_logs")
    actor_user: Mapped[User | None] = relationship(back_populates="audit_events")


# Cross-row hierarchy and tenant invariants cannot be represented by ordinary
# CHECK constraints. Installing them with metadata keeps create_all and the
# migration target equivalent on PostgreSQL.
_ITEM_PARENT_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_item_parent() RETURNS trigger AS $$
    DECLARE
      parent_tenant uuid;
      parent_type varchar(16);
    BEGIN
      IF NEW.parent_item_id IS NULL THEN
        IF NEW.item_type <> 'collection' THEN
          RAISE EXCEPTION 'only Collections may be root Items';
        END IF;
        RETURN NEW;
      END IF;
      SELECT tenant_id, item_type INTO parent_tenant, parent_type
      FROM items WHERE id = NEW.parent_item_id AND deleted_at IS NULL;
      IF NOT FOUND OR parent_tenant <> NEW.tenant_id THEN
        RAISE EXCEPTION 'Item parent must exist in the same tenant';
      END IF;
      IF NEW.item_type = 'collection' AND parent_type <> 'collection' THEN
        RAISE EXCEPTION 'a Collection cannot be parented by a Document';
      END IF;
      IF EXISTS (
        WITH RECURSIVE ancestry(id, parent_item_id) AS (
          SELECT id, parent_item_id FROM items WHERE id = NEW.parent_item_id
          UNION ALL
          SELECT i.id, i.parent_item_id
          FROM items i JOIN ancestry a ON i.id = a.parent_item_id
        )
        SELECT 1 FROM ancestry WHERE id = NEW.id
      ) THEN
        RAISE EXCEPTION 'Item hierarchy cycle detected';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_ITEM_PARENT_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_items_validate_parent
    BEFORE INSERT OR UPDATE OF tenant_id, item_type, parent_item_id ON items
    FOR EACH ROW EXECUTE FUNCTION bothesis_validate_item_parent()"""
).execute_if(dialect="postgresql")

_COLLECTION_ACCESS_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_collection_access() RETURNS trigger AS $$
    DECLARE collection_tenant uuid;
    BEGIN
      SELECT tenant_id INTO collection_tenant FROM items
      WHERE id = NEW.item_id AND item_type = 'collection' AND deleted_at IS NULL;
      IF NOT FOUND THEN RAISE EXCEPTION 'Collection access target must be a Collection'; END IF;
      IF NEW.principal_type = 'group' AND NOT EXISTS (
        SELECT 1 FROM groups WHERE id = NEW.principal_id
        AND tenant_id = collection_tenant AND deleted_at IS NULL
      ) THEN RAISE EXCEPTION 'Collection group principal must belong to target tenant';
      ELSIF NEW.principal_type = 'user' AND NOT EXISTS (
        SELECT 1 FROM tenant_memberships WHERE user_id = NEW.principal_id
        AND tenant_id = collection_tenant AND deleted_at IS NULL
      ) THEN RAISE EXCEPTION 'Collection user principal must belong to target tenant';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_COLLECTION_ACCESS_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_collection_access_validate
    BEFORE INSERT OR UPDATE OF item_id, principal_type, principal_id ON collection_access
    FOR EACH ROW EXECUTE FUNCTION bothesis_validate_collection_access()"""
).execute_if(dialect="postgresql")

_INGESTION_SOURCE_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_ingestion_source() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM integration_connections c JOIN items i ON i.id = NEW.target_item_id
        WHERE c.id = NEW.integration_connection_id AND c.tenant_id = i.tenant_id
        AND c.deleted_at IS NULL AND i.item_type = 'collection' AND i.deleted_at IS NULL
      ) THEN RAISE EXCEPTION 'Ingestion Source target must be a Collection in the Integration Connection tenant';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_INGESTION_SOURCE_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_ingestion_sources_validate
    BEFORE INSERT OR UPDATE OF integration_connection_id, target_item_id ON ingestion_sources
    FOR EACH ROW EXECUTE FUNCTION bothesis_validate_ingestion_source()"""
).execute_if(dialect="postgresql")

_EXTERNAL_RESOURCE_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_external_resource() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM items i
        JOIN ingestion_sources s ON s.id = NEW.ingestion_source_id
        JOIN integration_connections c ON c.id = s.integration_connection_id
        WHERE i.id = NEW.item_id AND i.tenant_id = c.tenant_id
      ) THEN RAISE EXCEPTION 'External Resource and Ingestion Source must belong to the same tenant';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_EXTERNAL_RESOURCE_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_external_resources_validate
    BEFORE INSERT OR UPDATE OF item_id, ingestion_source_id ON external_resources
    FOR EACH ROW EXECUTE FUNCTION bothesis_validate_external_resource()"""
).execute_if(dialect="postgresql")

event.listen(Item.__table__, "after_create", _ITEM_PARENT_TRIGGER)
event.listen(Item.__table__, "after_create", _ITEM_PARENT_TRIGGER_CREATE)
event.listen(CollectionAccess.__table__, "after_create", _COLLECTION_ACCESS_TRIGGER)
event.listen(
    CollectionAccess.__table__, "after_create", _COLLECTION_ACCESS_TRIGGER_CREATE
)
event.listen(IngestionSource.__table__, "after_create", _INGESTION_SOURCE_TRIGGER)
event.listen(
    IngestionSource.__table__, "after_create", _INGESTION_SOURCE_TRIGGER_CREATE
)
event.listen(ExternalResource.__table__, "after_create", _EXTERNAL_RESOURCE_TRIGGER)
event.listen(
    ExternalResource.__table__, "after_create", _EXTERNAL_RESOURCE_TRIGGER_CREATE
)


__all__ = [
    "AccessRequest",
    "AuditLog",
    "Base",
    "Citation",
    "CollectionAccess",
    "Conversation",
    "Group",
    "GroupMembership",
    "Item",
    "ExternalResource",
    "ItemUpload",
    "Memory",
    "Message",
    "MessageItem",
    "IngestionSource",
    "IntegrationConnection",
    "IntegrationCredential",
    "Role",
    "Tenant",
    "TenantMembership",
    "User",
]
