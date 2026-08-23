"""PostgreSQL ORM models for BoThesis durable business state.

Raw objects belong to S3-compatible storage and retrieval chunks belong to
Qdrant. This module intentionally contains neither binary nor chunk content.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
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
    """Declarative base shared by every BoThesis database model."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class UUIDPrimaryKeyMixin:
    """Application-generated UUID primary key."""

    id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )


class CreatedAtMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
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
        back_populates="user",
    )
    conversations: Mapped[list[Conversation]] = relationship(back_populates="user")
    memories: Mapped[list[Memory]] = relationship(back_populates="user")
    created_connectors: Mapped[list[Connector]] = relationship(
        back_populates="created_by_user",
        foreign_keys="Connector.created_by_user_id",
    )
    owned_items: Mapped[list[Item]] = relationship(
        back_populates="owner_user",
        foreign_keys="Item.owner_user_id",
    )
    created_items: Mapped[list[Item]] = relationship(
        back_populates="created_by_user",
        foreign_keys="Item.created_by_user_id",
    )
    principal_tokens: Mapped[list[UserPrincipalToken]] = relationship(
        back_populates="user"
    )
    group_memberships: Mapped[list[GroupMembership]] = relationship(
        back_populates="user"
    )
    access_requests: Mapped[list[AccessRequest]] = relationship(
        back_populates="requester_user",
        foreign_keys="AccessRequest.requester_user_id",
    )
    reviewed_access_requests: Mapped[list[AccessRequest]] = relationship(
        back_populates="reviewed_by_user",
        foreign_keys="AccessRequest.reviewed_by_user_id",
    )
    created_acl_policies: Mapped[list[AclPolicy]] = relationship(
        back_populates="created_by_user",
    )
    audit_events: Mapped[list[AuditLog]] = relationship(
        back_populates="actor_user",
    )


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
    connectors: Mapped[list[Connector]] = relationship(back_populates="tenant")
    items: Mapped[list[Item]] = relationship(back_populates="tenant")
    groups: Mapped[list[Group]] = relationship(back_populates="tenant")
    access_requests: Mapped[list[AccessRequest]] = relationship(
        back_populates="tenant"
    )
    acl_policies: Mapped[list[AclPolicy]] = relationship(back_populates="tenant")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="tenant")


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("tenant_id", "code"),)

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
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
    __table_args__ = (
        Index(None, "tenant_id", "status"),
        Index(None, "role_id"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        primary_key=True,
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        primary_key=True,
    )
    role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("roles.id"),
        nullable=False,
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
        UniqueConstraint("tenant_id", "principal_token"),
        Index(None, "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    principal_token: Mapped[str] = mapped_column(String(512), nullable=False)
    permission_codes: Mapped[list[str]] = _text_array_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="groups")
    memberships: Mapped[list[GroupMembership]] = relationship(
        back_populates="group"
    )


class GroupMembership(TimestampMixin, Base):
    __tablename__ = "group_memberships"
    __table_args__ = (
        Index(None, "user_id", "status"),
        Index(None, "group_id", "status"),
    )

    group_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("groups.id"),
        primary_key=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        primary_key=True,
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    group: Mapped[Group] = relationship(back_populates="memberships")
    user: Mapped[User] = relationship(back_populates="group_memberships")


class AccessRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "access_requests"
    __table_args__ = (
        Index(None, "tenant_id", "status", "created_at"),
        Index(None, "requester_user_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
    )
    requester_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(512), nullable=False)
    access_type: Mapped[str] = mapped_column(String(32), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    reviewed_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
    )
    review_note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="access_requests")
    requester_user: Mapped[User] = relationship(
        back_populates="access_requests",
        foreign_keys=[requester_user_id],
    )
    reviewed_by_user: Mapped[User | None] = relationship(
        back_populates="reviewed_access_requests",
        foreign_keys=[reviewed_by_user_id],
    )


class AclPolicy(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "acl_policies"
    __table_args__ = (
        UniqueConstraint("tenant_id", "name"),
        Index(None, "tenant_id", "resource_type", "resource_id"),
        Index(None, "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(512), nullable=False)
    allowed_principal_tokens: Mapped[list[str]] = _text_array_column()
    denied_principal_tokens: Mapped[list[str]] = _text_array_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="acl_policies")
    created_by_user: Mapped[User | None] = relationship(
        back_populates="created_acl_policies"
    )


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "audit_logs"
    __table_args__ = (
        Index(None, "tenant_id", "created_at"),
        Index(None, "tenant_id", "action", "created_at"),
        Index(None, "actor_user_id", "created_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
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


class Conversation(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (
        Index(None, "user_id", "updated_at"),
        Index(None, "user_id", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    title: Mapped[str | None] = mapped_column(String(512))
    summary: Mapped[str | None] = mapped_column(Text)
    summary_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    state: Mapped[JsonObject] = _json_object_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="conversations")
    messages: Mapped[list[Message]] = relationship(back_populates="conversation")
    memories: Mapped[list[Memory]] = relationship(back_populates="conversation")


class Message(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "messages"
    __table_args__ = (UniqueConstraint("conversation_id", "sequence_number"),)

    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id"),
        nullable=False,
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
    sourced_memories: Mapped[list[Memory]] = relationship(
        back_populates="source_message"
    )
    item_links: Mapped[list[MessageItem]] = relationship(
        back_populates="message"
    )


class Memory(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "memories"
    __table_args__ = (
        Index(None, "user_id", "status"),
        Index(None, "user_id", "memory_key"),
        Index(None, "conversation_id", "status"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        nullable=False,
    )
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("conversations.id"),
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
        PG_UUID(as_uuid=True),
        ForeignKey("messages.id"),
    )
    importance: Mapped[float | None] = mapped_column(Float)
    confidence: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="memories")
    conversation: Mapped[Conversation | None] = relationship(back_populates="memories")
    source_message: Mapped[Message | None] = relationship(
        back_populates="sourced_memories"
    )


class Connector(TimestampMixin, Base):
    __tablename__ = "connectors"
    __table_args__ = (
        Index(None, "tenant_id", "provider", "status"),
        UniqueConstraint("tenant_id", "display_name"),
        CheckConstraint(
            "(owner_type = 'tenant' AND owner_user_id IS NULL) OR "
            "(owner_type = 'user' AND owner_user_id IS NOT NULL)",
            name="connector_owner_matches_type",
        ),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("tenants.id"),
        nullable=False,
    )
    owner_type: Mapped[str] = mapped_column(
        String(16), nullable=False, default="tenant", server_default="tenant"
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    provider: Mapped[str] = mapped_column(String(32), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    settings: Mapped[JsonObject] = _json_object_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
    )

    tenant: Mapped[Tenant] = relationship(back_populates="connectors")
    created_by_user: Mapped[User | None] = relationship(
        back_populates="created_connectors",
        foreign_keys=[created_by_user_id],
    )
    scopes: Mapped[list[ConnectorScope]] = relationship(back_populates="connector")
    credential: Mapped[ConnectorCredential | None] = relationship(
        back_populates="connector", uselist=False
    )
    items: Mapped[list[Item]] = relationship(back_populates="connector")
    principal_tokens: Mapped[list[UserPrincipalToken]] = relationship(
        back_populates="connector"
    )


class ConnectorCredential(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "connector_credentials"

    connector_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("connectors.id"), nullable=False, unique=True
    )
    credential_type: Mapped[str] = mapped_column(String(64), nullable=False)
    encrypted_payload: Mapped[str] = mapped_column(Text, nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    key_version: Mapped[str | None] = mapped_column(String(64))

    connector: Mapped[Connector] = relationship(back_populates="credential")


class ConnectorScope(TimestampMixin, Base):
    __tablename__ = "connector_scopes"
    __table_args__ = (
        UniqueConstraint("connector_id", "scope_value"),
        Index(None, "connector_id", "status"),
    )

    id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    connector_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("connectors.id"),
        nullable=False,
    )
    scope_value: Mapped[str] = mapped_column(Text, nullable=False)
    display_name: Mapped[str | None] = mapped_column(String(255))
    scope_type: Mapped[str | None] = mapped_column(String(32))
    settings: Mapped[JsonObject] = _json_object_column()
    sync_checkpoint: Mapped[JsonObject] = _json_object_column()
    sync_schedule: Mapped[JsonObject] = _json_object_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_indexed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    connector: Mapped[Connector] = relationship(back_populates="scopes")
    sync_runs: Mapped[list[SyncRun]] = relationship(back_populates="connector_scope")
    items: Mapped[list[Item]] = relationship(back_populates="connector_scope")


class SyncRun(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    __tablename__ = "sync_runs"
    __table_args__ = (
        Index(None, "connector_scope_id", "created_at"),
        Index(None, "status", "created_at"),
    )

    connector_scope_id: Mapped[int] = mapped_column(
        BigInteger,
        ForeignKey("connector_scopes.id"),
        nullable=False,
    )
    trigger_type: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    discovered_item_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    processed_item_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    written_chunk_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    deleted_item_count: Mapped[int] = mapped_column(
        BigInteger, nullable=False, default=0, server_default="0"
    )
    error_code: Mapped[str | None] = mapped_column(String(128))
    error_message: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    connector_scope: Mapped[ConnectorScope] = relationship(back_populates="sync_runs")


class Item(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "items"
    __table_args__ = (
        UniqueConstraint("connector_id", "external_id"),
        Index(None, "tenant_id", "status"),
        Index(None, "owner_user_id", "status"),
        Index(None, "connector_scope_id", "status"),
        Index(None, "parent_item_id"),
        CheckConstraint(
            "item_type IN ('collection', 'document', 'file')",
            name="item_type_is_valid",
        ),
        CheckConstraint(
            "(item_type = 'document' AND document_kind IS NOT NULL AND collection_kind IS NULL) OR "
            "(item_type = 'collection' AND collection_kind IS NOT NULL AND document_kind IS NULL) OR "
            "(item_type = 'file' AND document_kind IS NULL AND collection_kind IS NULL)",
            name="item_kind_matches_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'ready', 'failed', 'unsupported', 'deleted')",
            name="item_status_is_valid",
        ),
        CheckConstraint(
            "content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$'",
            name="item_content_sha256_is_valid",
        ),
    )

    item_type: Mapped[str] = mapped_column(String(16), nullable=False)
    document_kind: Mapped[str | None] = mapped_column(String(32))
    collection_kind: Mapped[str | None] = mapped_column(String(32))
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    connector_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("connectors.id")
    )
    connector_scope_id: Mapped[int | None] = mapped_column(
        BigInteger, ForeignKey("connector_scopes.id")
    )
    external_id: Mapped[str | None] = mapped_column(Text)
    external_version: Mapped[str | None] = mapped_column(Text)
    etag: Mapped[str | None] = mapped_column(Text)
    external_updated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    parent_item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id")
    )
    title: Mapped[str] = mapped_column(Text, nullable=False)
    source_url: Mapped[str | None] = mapped_column(Text)
    mime_type: Mapped[str | None] = mapped_column(String(255))
    size_bytes: Mapped[int | None] = mapped_column(BigInteger)
    storage_key: Mapped[str | None] = mapped_column(Text)
    content_sha256: Mapped[str | None] = mapped_column(String(64))
    allowed_principal_tokens: Mapped[list[str]] = _text_array_column()
    denied_principal_tokens: Mapped[list[str]] = _text_array_column()
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict,
        server_default=text("'{}'::jsonb"),
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    owner_user: Mapped[User | None] = relationship(
        back_populates="owned_items", foreign_keys=[owner_user_id]
    )
    created_by_user: Mapped[User | None] = relationship(
        back_populates="created_items", foreign_keys=[created_by_user_id]
    )
    tenant: Mapped[Tenant] = relationship(back_populates="items")
    connector: Mapped[Connector | None] = relationship(back_populates="items")
    connector_scope: Mapped[ConnectorScope | None] = relationship(back_populates="items")
    parent_item: Mapped[Item | None] = relationship(
        back_populates="child_items", foreign_keys=[parent_item_id], remote_side="Item.id"
    )
    child_items: Mapped[list[Item]] = relationship(
        back_populates="parent_item", foreign_keys=[parent_item_id]
    )
    upload: Mapped[ItemUpload | None] = relationship(back_populates="item", uselist=False)
    message_links: Mapped[list[MessageItem]] = relationship(back_populates="item")


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
    __table_args__ = (
        Index(None, "item_id"),
        Index(None, "message_id", "deleted_at"),
    )

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


class UserPrincipalToken(CreatedAtMixin, Base):
    __tablename__ = "user_principal_tokens"
    __table_args__ = (
        Index(None, "tenant_id", "user_id"),
        Index(None, "connector_id"),
        Index(None, "user_id", "deleted_at"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("users.id"),
        primary_key=True,
    )
    principal_token: Mapped[str] = mapped_column(
        String(512),
        primary_key=True,
    )
    connector_id: Mapped[int | None] = mapped_column(
        BigInteger,
        ForeignKey("connectors.id"),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="principal_tokens")
    connector: Mapped[Connector | None] = relationship(
        back_populates="principal_tokens"
    )
__all__ = [
    "AccessRequest",
    "AclPolicy",
    "AuditLog",
    "Base",
    "Connector",
    "ConnectorCredential",
    "ConnectorScope",
    "Conversation",
    "Group",
    "GroupMembership",
    "Item",
    "ItemUpload",
    "Memory",
    "Message",
    "MessageItem",
    "Role",
    "SyncRun",
    "Tenant",
    "TenantMembership",
    "User",
    "UserPrincipalToken",
]
