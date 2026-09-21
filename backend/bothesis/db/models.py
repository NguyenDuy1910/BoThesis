"""PostgreSQL models for durable Enterprise Agent business and domain state.

Canonical knowledge and authorization live here. Original bytes remain in
S3/R2, while chunks and retrieval representations remain in Qdrant.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    and_,
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
    username: Mapped[str | None] = mapped_column(String(64))
    email: Mapped[str] = mapped_column(String(255), nullable=False, unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(256))
    display_name: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default=text("true")
    )
    preferences: Mapped[JsonObject] = _json_object_column()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    __table_args__ = (
        # Local-login identifiers are compared case-insensitively, matching
        # the migration and IdentityStore normalization rule.
        Index(
            "uq_users_username",
            func.lower(username),
            unique=True,
            postgresql_where=username.is_not(None),
        ),
    )

    tenant_memberships: Mapped[list[TenantMembership]] = relationship(
        back_populates="user"
    )
    auth_identities: Mapped[list[AuthIdentity]] = relationship(back_populates="user")
    access_sessions: Mapped[list[AccessSession]] = relationship(back_populates="user")
    conversations: Mapped[list[Conversation]] = relationship(back_populates="owner_user")
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
    role_assignments: Mapped[list[RoleAssignment]] = relationship(
        back_populates="user", foreign_keys="RoleAssignment.user_id"
    )
    approval_requests: Mapped[list[ApprovalRequest]] = relationship(
        back_populates="requester_user",
        foreign_keys="ApprovalRequest.requester_user_id",
    )
    decided_approval_requests: Mapped[list[ApprovalRequest]] = relationship(
        back_populates="decided_by_user",
        foreign_keys="ApprovalRequest.decided_by_user_id",
    )
    audit_events: Mapped[list[AuditLog]] = relationship(back_populates="actor_user")


class AuthIdentity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Stable external-provider subject linked to one durable human User."""

    __tablename__ = "auth_identities"
    __table_args__ = (
        UniqueConstraint("issuer", "subject"),
        Index(None, "user_id", "status"),
        Index(None, "provider_key", "status"),
        CheckConstraint("protocol IN ('oidc', 'saml')", name="auth_identity_protocol_is_valid"),
        CheckConstraint("status IN ('active', 'disabled')", name="auth_identity_status_is_valid"),
    )

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    protocol: Mapped[str] = mapped_column(String(24), nullable=False)
    provider_key: Mapped[str] = mapped_column(String(64), nullable=False)
    issuer: Mapped[str] = mapped_column(Text, nullable=False)
    subject: Mapped[str] = mapped_column(Text, nullable=False)
    email: Mapped[str | None] = mapped_column(String(255))
    email_verified: Mapped[bool | None] = mapped_column(Boolean)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    profile: Mapped[JsonObject] = _json_object_column()
    last_authenticated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="auth_identities")
    access_sessions: Mapped[list[AccessSession]] = relationship(
        back_populates="auth_identity"
    )


class AccessSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One revocable guest or user security session in one tenant context."""

    __tablename__ = "access_sessions"
    __table_args__ = (
        Index(None, "user_id", "status"),
        Index(None, "auth_identity_id", "status"),
        Index(None, "tenant_id", "kind", "status"),
        Index(None, "parent_session_id"),
        Index(None, "status", "expires_at"),
        Index(None, "status", "idle_expires_at"),
        CheckConstraint("kind IN ('guest', 'user')", name="access_session_kind_is_valid"),
        CheckConstraint(
            "authentication_method IN ('anonymous', 'oidc', 'saml', 'password', 'internal')",
            name="access_session_auth_method_is_valid",
        ),
        CheckConstraint(
            "assurance_level IN ('aal0', 'aal1', 'aal2')",
            name="access_session_assurance_level_is_valid",
        ),
        CheckConstraint(
            "status IN ('active', 'superseded', 'revoked', 'expired')",
            name="access_session_status_is_valid",
        ),
        CheckConstraint("token_version >= 1", name="access_session_token_version_is_valid"),
        CheckConstraint(
            "(kind = 'guest' AND user_id IS NULL AND auth_identity_id IS NULL "
            "AND authentication_method = 'anonymous' AND assurance_level = 'aal0') OR "
            "(kind = 'user' AND user_id IS NOT NULL "
            "AND authentication_method <> 'anonymous')",
            name="access_session_subject_is_complete",
        ),
        CheckConstraint(
            "(parent_session_id IS NULL) = (transition_reason IS NULL)",
            name="access_session_transition_is_complete",
        ),
        CheckConstraint(
            "(status = 'active' AND ended_at IS NULL) OR "
            "(status <> 'active' AND ended_at IS NOT NULL)",
            name="access_session_end_is_complete",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    auth_identity_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("auth_identities.id")
    )
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    authentication_method: Mapped[str] = mapped_column(String(32), nullable=False)
    assurance_level: Mapped[str] = mapped_column(
        String(16), nullable=False, default="aal0", server_default="aal0"
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    token_version: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default=text("1")
    )
    parent_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("access_sessions.id")
    )
    transition_reason: Mapped[str | None] = mapped_column(String(32))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    idle_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    end_reason: Mapped[str | None] = mapped_column(String(64))
    metadata_: Mapped[JsonObject] = mapped_column(
        "metadata",
        JSONB,
        nullable=False,
        default=dict,
        server_default=text("'{}'::jsonb"),
    )

    tenant: Mapped[Tenant] = relationship(back_populates="access_sessions")
    user: Mapped[User | None] = relationship(back_populates="access_sessions")
    auth_identity: Mapped[AuthIdentity | None] = relationship(
        back_populates="access_sessions"
    )
    parent_session: Mapped[AccessSession | None] = relationship(
        remote_side="AccessSession.id", foreign_keys=[parent_session_id]
    )
    conversations: Mapped[list[Conversation]] = relationship(
        back_populates="created_by_session"
    )
    audit_events: Mapped[list[AuditLog]] = relationship(back_populates="actor_session")


class Tenant(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    __tablename__ = "tenants"
    __table_args__ = (
        CheckConstraint(
            "visibility IN ('private', 'public')",
            name="tenant_visibility_is_valid",
        ),
        CheckConstraint(
            "(visibility = 'private' AND public_access_role_id IS NULL) OR "
            "(visibility = 'public' AND public_access_role_id IS NOT NULL)",
            name="tenant_public_access_is_complete",
        ),
    )

    code: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    visibility: Mapped[str] = mapped_column(
        String(16), nullable=False, default="private", server_default="private"
    )
    public_access_role_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True),
        ForeignKey("roles.id", use_alter=True, name="fk_tenants_public_access_role_id_roles"),
    )
    settings: Mapped[JsonObject] = _json_object_column()

    roles: Mapped[list[Role]] = relationship(
        back_populates="tenant", foreign_keys="Role.tenant_id"
    )
    public_access_role: Mapped[Role | None] = relationship(
        foreign_keys=[public_access_role_id], post_update=True
    )
    memberships: Mapped[list[TenantMembership]] = relationship(back_populates="tenant")
    groups: Mapped[list[Group]] = relationship(back_populates="tenant")
    conversations: Mapped[list[Conversation]] = relationship(back_populates="tenant")
    memories: Mapped[list[Memory]] = relationship(back_populates="tenant")
    integration_connections: Mapped[list[IntegrationConnection]] = relationship(
        back_populates="tenant"
    )
    items: Mapped[list[Item]] = relationship(back_populates="tenant")
    approval_requests: Mapped[list[ApprovalRequest]] = relationship(back_populates="tenant")
    audit_logs: Mapped[list[AuditLog]] = relationship(back_populates="tenant")
    role_assignments: Mapped[list[RoleAssignment]] = relationship(back_populates="tenant")
    access_sessions: Mapped[list[AccessSession]] = relationship(back_populates="tenant")


class Role(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A named permission bundle, owned by the platform or by one tenant.

    ``tenant_id`` is null for the roles the platform defines, which is what
    lets platform capability exist without inventing a second role table.
    """

    __tablename__ = "roles"
    __table_args__ = (
        # A tenant may reuse a code another tenant uses, but never a code the
        # platform defines. NULLS NOT DISTINCT makes the system row collide.
        Index(
            "uq_roles_tenant_id_code",
            "tenant_id",
            "code",
            unique=True,
            postgresql_nulls_not_distinct=True,
        ),
        Index(None, "scope_type", "status"),
        CheckConstraint(
            "scope_type IN ('platform', 'tenant', 'collection')",
            name="role_scope_type_is_valid",
        ),
        CheckConstraint(
            "(is_system AND tenant_id IS NULL) OR (NOT is_system AND tenant_id IS NOT NULL)",
            name="role_ownership_matches_system_flag",
        ),
        # A tenant defines member roles for its own workspace. Platform and
        # Collection roles are the platform's, so a tenant cannot mint one.
        CheckConstraint(
            "is_system OR scope_type = 'tenant'",
            name="tenant_defined_role_is_tenant_scoped",
        ),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id")
    )
    code: Mapped[str] = mapped_column(String(64), nullable=False)
    display_name: Mapped[str] = mapped_column(String(255), nullable=False)
    scope_type: Mapped[str] = mapped_column(String(16), nullable=False)
    is_system: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default=text("false")
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )

    tenant: Mapped[Tenant | None] = relationship(
        back_populates="roles", foreign_keys=[tenant_id]
    )
    grants: Mapped[list[RolePermission]] = relationship(
        back_populates="role", cascade="all, delete-orphan"
    )
    assignments: Mapped[list[RoleAssignment]] = relationship(back_populates="role")


class Permission(CreatedAtMixin, Base):
    """One product action the authorization resolver can be asked about."""

    __tablename__ = "permissions"

    code: Mapped[str] = mapped_column(String(64), primary_key=True)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    scope_types: Mapped[list[str]] = _text_array_column()

    role_grants: Mapped[list[RolePermission]] = relationship(
        back_populates="permission"
    )


class RolePermission(TimestampMixin, Base):
    """One permission carried by one role.

    Removing a permission from a role is a tombstone, like every other removal
    here, so the history of what a role could do survives. Every read of this
    table must therefore exclude tombstones: a forgotten filter would keep
    granting a capability someone believes they revoked.
    """

    __tablename__ = "role_permissions"

    role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("roles.id"), primary_key=True
    )
    permission_code: Mapped[str] = mapped_column(
        String(64), ForeignKey("permissions.code"), primary_key=True
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    role: Mapped[Role] = relationship(back_populates="grants")
    permission: Mapped[Permission] = relationship(back_populates="role_grants")

    @classmethod
    def granted_by(cls, role_id: Any) -> Any:
        """Join condition that only ever reaches live permission grants.

        Readers join through this rather than writing the tombstone filter
        themselves, so a revoked permission cannot come back through a query
        that forgot it.
        """

        return and_(cls.role_id == role_id, cls.deleted_at.is_(None))


class TenantMembership(TimestampMixin, Base):
    """The fact that a user belongs to a tenant. Never an authorization grant.

    What the member may do lives in :class:`RoleAssignment`, so one member can
    hold several roles and losing a role never removes them from the workspace.
    """

    __tablename__ = "tenant_memberships"
    __table_args__ = (Index(None, "tenant_id", "status"),)

    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), primary_key=True
    )
    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    joined_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User] = relationship(back_populates="tenant_memberships")
    tenant: Mapped[Tenant] = relationship(back_populates="memberships")


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
    role_assignments: Mapped[list[RoleAssignment]] = relationship(back_populates="group")


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
        Index(None, "tenant_id", "owner_user_id", "updated_at"),
        Index(None, "tenant_id", "created_by_session_id", "updated_at"),
        Index(None, "tenant_id", "status"),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    owner_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    created_by_session_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("access_sessions.id"), nullable=False
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
    owner_user: Mapped[User | None] = relationship(back_populates="conversations")
    created_by_session: Mapped[AccessSession] = relationship(
        back_populates="conversations"
    )
    messages: Mapped[list[Message]] = relationship(back_populates="conversation")
    memories: Mapped[list[Memory]] = relationship(back_populates="conversation")


class SandboxSession(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """Durable recovery metadata for a provider-backed conversation workspace.

    The provider container and files are opaque values in ``provider_state``;
    durable Enterprise Agent Item identities stay in the provider-neutral ``manifest``.
    Neither field contains workspace output bytes.
    """

    __tablename__ = "sandbox_sessions"
    __table_args__ = (
        Index(None, "tenant_id", "conversation_id", "status"),
        Index(None, "conversation_id", "provider", "status"),
        CheckConstraint(
            "status IN ('active', 'expired', 'closed')",
            name="sandbox_session_status_is_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(manifest) = 'object'", name="sandbox_manifest_is_object"
        ),
        CheckConstraint(
            "jsonb_typeof(provider_state) = 'object'",
            name="sandbox_provider_state_is_object",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    conversation_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id"), nullable=False
    )
    user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    provider: Mapped[str] = mapped_column(String(64), nullable=False)
    manifest: Mapped[JsonObject] = _json_object_column()
    provider_state: Mapped[JsonObject] = _json_object_column()
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="active", server_default="active"
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


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
    """One authorized external account, reusable by many Ingestion Sources.

    A Connection answers "whose access is this, and is it still good"; an
    Ingestion Source answers "which resource does it read". Authorizing the
    same provider account twice must not create a second Connection, so the
    provider's own account and resource identifiers are stored here and are
    unique per tenant and connector.
    """

    __tablename__ = "integration_connections"
    __table_args__ = (
        Index(None, "tenant_id", "connector_key", "status"),
        Index(None, "owner_user_id", "status"),
        UniqueConstraint("tenant_id", "display_name"),
        Index(
            "uq_integration_connections_provider_account",
            "tenant_id",
            "connector_key",
            "owner_type",
            "owner_user_id",
            "provider_account_id",
            "provider_resource_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND provider_account_id IS NOT NULL"
            ),
        ),
        CheckConstraint(
            "(owner_type = 'tenant' AND owner_user_id IS NULL) OR "
            "(owner_type = 'user' AND owner_user_id IS NOT NULL)",
            name="owner_matches_type",
        ),
        CheckConstraint(
            "status IN ('draft', 'connected', 'expired', 'reauth_required', "
            "'revoked', 'error', 'disconnected')",
            name="connection_status_is_valid",
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
    #: The provider's own identifier for the authorized account.
    provider_account_id: Mapped[str | None] = mapped_column(String(255))
    #: A human label for that account, safe to show (an email, a site host).
    provider_account_label: Mapped[str | None] = mapped_column(String(255))
    #: The provider resource the grant is bound to: an Atlassian cloud id, a
    #: Shared Drive id. Null when one grant covers the whole account.
    provider_resource_id: Mapped[str | None] = mapped_column(String(255))
    provider_resource_label: Mapped[str | None] = mapped_column(String(255))
    #: Scopes the provider actually granted, not the ones that were requested.
    scopes: Mapped[list[str]] = _text_array_column()
    config: Mapped[JsonObject] = _json_object_column()
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="draft", server_default="draft"
    )
    #: Why the connection is not healthy, in words a person may be shown.
    status_detail: Mapped[str | None] = mapped_column(Text)
    #: Mirrors the credential expiry so listing does not decrypt secrets.
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disconnected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
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
        CheckConstraint(
            "index_status IS NULL OR index_status IN "
            "('pending', 'processing', 'ready', 'failed', 'unsupported')",
            name="item_index_status_is_valid",
        ),
        CheckConstraint(
            "(item_type = 'collection' AND index_status IS NULL) OR "
            "(item_type = 'document' AND index_status IS NOT NULL)",
            name="item_index_status_matches_type",
        ),
        CheckConstraint("size_bytes IS NULL OR size_bytes >= 0", name="item_size_is_valid"),
        # Only a Collection can hold grants, so only a Collection can end
        # inheritance. A Document that stopped inheriting would be reachable
        # by nobody.
        CheckConstraint(
            "item_type = 'collection' OR inherit_access",
            name="only_collections_end_inheritance",
        ),
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
    #: Derived-search lifecycle. A ready Item may still be waiting to be
    #: parsed and indexed; the original resource remains independently usable.
    index_status: Mapped[str | None] = mapped_column(String(16))
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
    role_assignments: Mapped[list[RoleAssignment]] = relationship(back_populates="item")
    targeted_by_ingestion_sources: Mapped[list[IngestionSource]] = relationship(
        back_populates="target_item"
    )
    external_resources: Mapped[list[ExternalResource]] = relationship(
        back_populates="item"
    )
    upload: Mapped[ItemUpload | None] = relationship(back_populates="item", uselist=False)
    message_links: Mapped[list[MessageItem]] = relationship(back_populates="item")
    citations: Mapped[list[Citation]] = relationship(back_populates="item")
    artifact_revisions: Mapped[list[ArtifactRevision]] = relationship(
        back_populates="item"
    )


class ArtifactRevision(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One immutable revision of a conversation artifact Item.

    The Item stays the canonical identity (title, ACL, lineage, tombstone) and
    its ``storage_key`` always points at the current revision; every revision
    keeps its own object so an edit never overwrites the previous file.
    """

    __tablename__ = "artifact_revisions"
    __table_args__ = (
        UniqueConstraint("item_id", "revision_number"),
        Index(None, "conversation_id", "deleted_at"),
        CheckConstraint("revision_number >= 1", name="revision_number_is_valid"),
        CheckConstraint("size_bytes >= 0", name="revision_size_is_valid"),
        CheckConstraint("jsonb_typeof(exports) = 'object'", name="exports_is_object"),
    )

    item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    revision_number: Mapped[int] = mapped_column(Integer, nullable=False)
    storage_key: Mapped[str] = mapped_column(Text, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(255), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    summary: Mapped[str | None] = mapped_column(Text)
    conversation_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("conversations.id")
    )
    request_id: Mapped[str | None] = mapped_column(String(64))
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    exports: Mapped[JsonObject] = _json_object_column()
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    item: Mapped[Item] = relationship(back_populates="artifact_revisions")


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


class RoleAssignment(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """WHO holds WHICH ROLE at WHICH SCOPE. The only authorization grant.

    Principal and scope are exclusive arcs of real foreign keys rather than a
    ``principal_id``/``scope_id`` pair of loose UUIDs: every reference here is
    checked by PostgreSQL, and a deleted group or Collection cannot leave a
    grant pointing at nothing. A row with neither ``tenant_id`` nor ``item_id``
    is a platform grant.
    """

    __tablename__ = "role_assignments"
    __table_args__ = (
        # One grant of one role to one principal at one scope. NULLS NOT
        # DISTINCT is what makes the unused arc columns compare equal.
        Index(
            "uq_role_assignments_principal_scope_role",
            "user_id",
            "group_id",
            "tenant_id",
            "item_id",
            "role_id",
            unique=True,
            postgresql_nulls_not_distinct=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(None, "user_id", "tenant_id"),
        Index(None, "group_id", "tenant_id"),
        Index(None, "item_id"),
        Index(None, "role_id"),
        CheckConstraint(
            "num_nonnulls(user_id, group_id) = 1",
            name="role_assignment_has_one_principal",
        ),
        CheckConstraint(
            "num_nonnulls(tenant_id, item_id) <= 1",
            name="role_assignment_has_one_scope",
        ),
    )

    user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    group_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("groups.id")
    )
    role_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id")
    )
    item_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id")
    )
    created_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    user: Mapped[User | None] = relationship(
        back_populates="role_assignments", foreign_keys=[user_id]
    )
    group: Mapped[Group | None] = relationship(back_populates="role_assignments")
    role: Mapped[Role] = relationship(back_populates="assignments")
    tenant: Mapped[Tenant | None] = relationship(back_populates="role_assignments")
    item: Mapped[Item | None] = relationship(back_populates="role_assignments")

    @property
    def principal_type(self) -> str:
        return "user" if self.user_id is not None else "group"

    @property
    def principal_id(self) -> UUID:
        principal = self.user_id if self.user_id is not None else self.group_id
        assert principal is not None  # guaranteed by role_assignment_has_one_principal
        return principal

    @property
    def scope_type(self) -> str:
        if self.item_id is not None:
            return "collection"
        return "tenant" if self.tenant_id is not None else "platform"

    @property
    def scope_id(self) -> UUID | None:
        return self.item_id if self.item_id is not None else self.tenant_id


class IngestionSource(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One external resource synchronized into one destination Collection.

    ``status`` is the source's own enablement and health, never the state of a
    run: a run lives in its workflow execution and is read from there. A source
    that is enabled and reachable is ``ready`` whether or not a sync happens to
    be in flight.
    """

    __tablename__ = "ingestion_sources"
    __table_args__ = (
        Index(None, "integration_connection_id", "status"),
        Index(None, "target_item_id", "status"),
        Index(
            "uq_ingestion_sources_connection_resource",
            "integration_connection_id",
            "resource_type",
            "external_resource_id",
            unique=True,
            postgresql_where=text(
                "deleted_at IS NULL AND external_resource_id IS NOT NULL"
            ),
        ),
        CheckConstraint(
            "status IN ('ready', 'paused', 'failed', 'connection_required', "
            "'disabled')",
            name="ingestion_source_status_is_valid",
        ),
        CheckConstraint(
            "sync_mode IN ('manual', 'scheduled')",
            name="ingestion_source_sync_mode_is_valid",
        ),
    )

    integration_connection_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("integration_connections.id"), nullable=False
    )
    target_item_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("items.id"), nullable=False
    )
    display_name: Mapped[str | None] = mapped_column(String(255))
    #: The provider resource kind this source reads: space, shared_drive, folder.
    resource_type: Mapped[str | None] = mapped_column(String(64))
    #: The provider's identifier for that resource, lifted out of ``config`` so
    #: the same resource cannot be added to one connection twice.
    external_resource_id: Mapped[str | None] = mapped_column(Text)
    config: Mapped[JsonObject] = _json_object_column()
    checkpoint: Mapped[JsonObject] = _json_object_column()
    #: Whether this source runs on a schedule at all. Nothing syncs on its own
    #: until someone configures it.
    sync_mode: Mapped[str] = mapped_column(
        String(16), nullable=False, default="manual", server_default="manual"
    )
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="ready", server_default="ready"
    )
    status_detail: Mapped[str | None] = mapped_column(Text)
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


class ApprovalRequest(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """A tenant-scoped request requiring an explicit governed decision."""

    __tablename__ = "approval_requests"
    __table_args__ = (
        Index(None, "tenant_id", "status", "created_at"),
        Index(None, "requester_user_id", "status"),
        Index(None, "request_type", "target_id"),
        Index(
            "uq_approval_requests_pending_logical_target",
            "tenant_id",
            "requester_user_id",
            "request_type",
            "target_id",
            unique=True,
            postgresql_where=text("status = 'pending' AND deleted_at IS NULL"),
        ),
        CheckConstraint(
            "request_type IN ('resource_access', 'plugin_installation')",
            name="approval_request_type_is_valid",
        ),
        CheckConstraint(
            "status IN ('pending', 'approved', 'denied', 'cancelled')",
            name="approval_request_status_is_valid",
        ),
        CheckConstraint(
            "jsonb_typeof(details) = 'object'",
            name="approval_request_details_is_object",
        ),
        CheckConstraint(
            "(request_type = 'resource_access') = (requested_role_id IS NOT NULL)",
            name="resource_access_names_a_role",
        ),
    )

    tenant_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    requester_user_id: Mapped[UUID] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    request_type: Mapped[str] = mapped_column(String(32), nullable=False)
    target_id: Mapped[str] = mapped_column(String(512), nullable=False)
    #: The Collection role a resource_access request asks for. Approving one
    #: creates exactly this assignment, so a request can never name a role the
    #: authorization model does not have.
    requested_role_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("roles.id")
    )
    details: Mapped[JsonObject] = _json_object_column()
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(
        String(16), nullable=False, default="pending", server_default="pending"
    )
    decided_by_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    decision_note: Mapped[str | None] = mapped_column(Text)
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    tenant: Mapped[Tenant] = relationship(back_populates="approval_requests")
    requester_user: Mapped[User] = relationship(
        back_populates="approval_requests", foreign_keys=[requester_user_id]
    )
    decided_by_user: Mapped[User | None] = relationship(
        back_populates="decided_approval_requests", foreign_keys=[decided_by_user_id]
    )
    requested_role: Mapped[Role | None] = relationship()


class AuditLog(UUIDPrimaryKeyMixin, CreatedAtMixin, Base):
    """One recorded action. A null ``tenant_id`` is a platform-scoped action.

    Creating a tenant or granting platform administration belongs to no single
    workspace, so forcing every event into one would either lose the event or
    file it under an unrelated tenant.
    """

    __tablename__ = "audit_logs"
    __table_args__ = (
        Index(None, "tenant_id", "created_at"),
        Index(None, "tenant_id", "action", "created_at"),
        Index(None, "actor_user_id", "created_at"),
        Index(None, "actor_session_id", "created_at"),
        Index(None, "created_at"),
    )

    tenant_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("tenants.id")
    )
    actor_user_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("users.id")
    )
    actor_session_id: Mapped[UUID | None] = mapped_column(
        PG_UUID(as_uuid=True), ForeignKey("access_sessions.id")
    )
    action: Mapped[str] = mapped_column(String(96), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(32), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(512))
    outcome: Mapped[str] = mapped_column(
        String(16), nullable=False, default="success", server_default="success"
    )
    details: Mapped[JsonObject] = _json_object_column()

    tenant: Mapped[Tenant | None] = relationship(back_populates="audit_logs")
    actor_user: Mapped[User | None] = relationship(back_populates="audit_events")
    actor_session: Mapped[AccessSession | None] = relationship(
        back_populates="audit_events"
    )


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

_ROLE_ASSIGNMENT_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_role_assignment() RETURNS trigger AS $$
    DECLARE
      role_scope varchar(16);
      role_tenant uuid;
      role_status varchar(16);
      assignment_scope varchar(16);
      effective_tenant uuid;
    BEGIN
      SELECT scope_type, tenant_id, status INTO role_scope, role_tenant, role_status
      FROM roles WHERE id = NEW.role_id;
      IF NOT FOUND OR role_status <> 'active' THEN
        RAISE EXCEPTION 'Role Assignment must reference an active Role';
      END IF;

      IF NEW.item_id IS NOT NULL THEN
        assignment_scope := 'collection';
        SELECT tenant_id INTO effective_tenant FROM items
        WHERE id = NEW.item_id AND item_type = 'collection' AND deleted_at IS NULL;
        IF NOT FOUND THEN
          RAISE EXCEPTION 'Collection-scoped Role Assignment must target a Collection';
        END IF;
      ELSIF NEW.tenant_id IS NOT NULL THEN
        assignment_scope := 'tenant';
        effective_tenant := NEW.tenant_id;
      ELSE
        assignment_scope := 'platform';
        effective_tenant := NULL;
      END IF;

      IF role_scope <> assignment_scope THEN
        RAISE EXCEPTION 'Role scope does not match the Role Assignment scope';
      END IF;
      IF role_tenant IS NOT NULL AND role_tenant IS DISTINCT FROM effective_tenant THEN
        RAISE EXCEPTION 'a tenant-defined Role cannot be assigned outside its tenant';
      END IF;

      IF NEW.group_id IS NOT NULL THEN
        IF effective_tenant IS NULL THEN
          RAISE EXCEPTION 'a platform Role cannot be assigned to a group';
        END IF;
        IF NOT EXISTS (
          SELECT 1 FROM groups WHERE id = NEW.group_id
          AND tenant_id = effective_tenant AND deleted_at IS NULL
        ) THEN
          RAISE EXCEPTION 'Role Assignment group must belong to the scope tenant';
        END IF;
      ELSIF effective_tenant IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM tenant_memberships
        WHERE user_id = NEW.user_id AND tenant_id = effective_tenant
        AND deleted_at IS NULL
      ) THEN
        RAISE EXCEPTION 'Role Assignment user must be a member of the scope tenant';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_ROLE_ASSIGNMENT_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_role_assignments_validate
    BEFORE INSERT OR UPDATE OF user_id, group_id, role_id, tenant_id, item_id
    ON role_assignments
    FOR EACH ROW WHEN (NEW.deleted_at IS NULL)
    EXECUTE FUNCTION bothesis_validate_role_assignment()"""
).execute_if(dialect="postgresql")

_GROUP_MEMBERSHIP_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_group_membership() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM groups g
        JOIN tenant_memberships m
          ON m.tenant_id = g.tenant_id AND m.deleted_at IS NULL
        WHERE g.id = NEW.group_id AND g.deleted_at IS NULL
          AND m.user_id = NEW.user_id
      ) THEN
        RAISE EXCEPTION 'a group member must belong to the group tenant';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_GROUP_MEMBERSHIP_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_group_memberships_validate
    BEFORE INSERT OR UPDATE OF group_id, user_id ON group_memberships
    FOR EACH ROW WHEN (NEW.deleted_at IS NULL)
    EXECUTE FUNCTION bothesis_validate_group_membership()"""
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

_APPROVAL_REQUEST_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_approval_request() RETURNS trigger AS $$
    BEGIN
      IF NOT EXISTS (
        SELECT 1 FROM tenant_memberships membership
        WHERE membership.tenant_id = NEW.tenant_id
          AND membership.user_id = NEW.requester_user_id
          AND membership.deleted_at IS NULL
      ) THEN RAISE EXCEPTION 'Approval Request requester must belong to its tenant';
      END IF;
      IF NEW.decided_by_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM tenant_memberships membership
        WHERE membership.tenant_id = NEW.tenant_id
          AND membership.user_id = NEW.decided_by_user_id
          AND membership.deleted_at IS NULL
      ) THEN RAISE EXCEPTION 'Approval Request decider must belong to its tenant';
      END IF;
      IF NEW.request_type = 'resource_access' THEN
        IF NOT EXISTS (
          SELECT 1 FROM items item
          WHERE item.id = NEW.target_id::uuid
            AND item.tenant_id = NEW.tenant_id
            AND item.item_type = 'collection'
            AND item.deleted_at IS NULL
        ) THEN RAISE EXCEPTION 'Resource access Approval Request target must be a Collection in the requester tenant';
        END IF;
        IF NOT EXISTS (
          SELECT 1 FROM roles role
          WHERE role.id = NEW.requested_role_id
            AND role.scope_type = 'collection'
            AND role.status = 'active'
            AND (role.tenant_id IS NULL OR role.tenant_id = NEW.tenant_id)
        ) THEN RAISE EXCEPTION 'Resource access Approval Request must name a Collection Role available to its tenant';
        END IF;
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_APPROVAL_REQUEST_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_approval_requests_validate
    BEFORE INSERT OR UPDATE OF tenant_id, requester_user_id, request_type, target_id, requested_role_id, decided_by_user_id ON approval_requests
    FOR EACH ROW EXECUTE FUNCTION bothesis_validate_approval_request()"""
).execute_if(dialect="postgresql")

_TENANT_PUBLIC_ACCESS_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_tenant_public_access() RETURNS trigger AS $$
    BEGIN
      IF NEW.public_access_role_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM roles role
        WHERE role.id = NEW.public_access_role_id
          AND role.scope_type = 'tenant'
          AND role.status = 'active'
          AND (role.tenant_id IS NULL OR role.tenant_id = NEW.id)
      ) THEN
        RAISE EXCEPTION 'public access Role must be an active tenant-scope Role available to the tenant';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_TENANT_PUBLIC_ACCESS_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_tenants_validate_public_access
    BEFORE INSERT OR UPDATE OF visibility, public_access_role_id ON tenants
    FOR EACH ROW EXECUTE FUNCTION bothesis_validate_tenant_public_access()"""
).execute_if(dialect="postgresql")

_ACCESS_SESSION_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_access_session() RETURNS trigger AS $$
    DECLARE
      identity_user uuid;
      parent_tenant uuid;
      parent_user uuid;
      parent_kind varchar(24);
    BEGIN
      IF NEW.kind = 'guest' AND NOT EXISTS (
        SELECT 1 FROM tenants tenant
        WHERE tenant.id = NEW.tenant_id
          AND tenant.status = 'active'
          AND tenant.visibility = 'public'
          AND tenant.public_access_role_id IS NOT NULL
      ) THEN
        RAISE EXCEPTION 'Guest Access Session must target an active public tenant';
      END IF;
      IF NEW.auth_identity_id IS NOT NULL THEN
        SELECT user_id INTO identity_user FROM auth_identities
        WHERE id = NEW.auth_identity_id AND status = 'active';
        IF NOT FOUND OR identity_user IS DISTINCT FROM NEW.user_id THEN
          RAISE EXCEPTION 'Access Session identity must be active and belong to its User';
        END IF;
      END IF;
      IF NEW.parent_session_id IS NULL THEN
        RETURN NEW;
      END IF;
      IF NEW.parent_session_id = NEW.id THEN
        RAISE EXCEPTION 'Access Session cannot parent itself';
      END IF;
      SELECT tenant_id, user_id, kind
      INTO parent_tenant, parent_user, parent_kind
      FROM access_sessions WHERE id = NEW.parent_session_id;
      IF NOT FOUND THEN
        RAISE EXCEPTION 'Access Session parent must exist';
      END IF;
      IF NEW.transition_reason = 'identity_upgrade' THEN
        IF parent_kind <> 'guest' OR NEW.kind <> 'user'
           OR parent_tenant <> NEW.tenant_id THEN
          RAISE EXCEPTION 'identity upgrade must replace a guest in the same tenant';
        END IF;
      ELSIF NEW.transition_reason = 'token_rotation' THEN
        IF parent_kind <> NEW.kind OR parent_tenant <> NEW.tenant_id
           OR parent_user IS DISTINCT FROM NEW.user_id THEN
          RAISE EXCEPTION 'token rotation must preserve session subject and tenant';
        END IF;
      ELSIF NEW.transition_reason = 'tenant_switch' THEN
        IF parent_kind <> 'user' OR NEW.kind <> 'user'
           OR parent_user IS DISTINCT FROM NEW.user_id THEN
          RAISE EXCEPTION 'tenant switch must preserve the User subject';
        END IF;
      ELSE
        RAISE EXCEPTION 'Access Session transition reason is invalid';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_ACCESS_SESSION_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_access_sessions_validate
    BEFORE INSERT OR UPDATE OF tenant_id, user_id, auth_identity_id, kind, parent_session_id, transition_reason
    ON access_sessions FOR EACH ROW EXECUTE FUNCTION bothesis_validate_access_session()"""
).execute_if(dialect="postgresql")

_CONVERSATION_SESSION_TRIGGER = DDL(
    """
    CREATE OR REPLACE FUNCTION bothesis_validate_conversation_session() RETURNS trigger AS $$
    DECLARE
      session_tenant uuid;
      creator_user_id uuid;
      session_kind varchar(24);
    BEGIN
      SELECT tenant_id, user_id, kind
      INTO session_tenant, creator_user_id, session_kind
      FROM access_sessions WHERE id = NEW.created_by_session_id;
      IF NOT FOUND OR session_tenant IS DISTINCT FROM NEW.tenant_id THEN
        RAISE EXCEPTION 'Conversation creator session must belong to its tenant';
      END IF;
      IF NEW.owner_user_id IS NULL AND session_kind <> 'guest' THEN
        RAISE EXCEPTION 'Guest-owned Conversation must be created by a guest session';
      END IF;
      IF NEW.owner_user_id IS NOT NULL AND session_kind = 'user'
         AND creator_user_id IS DISTINCT FROM NEW.owner_user_id THEN
        RAISE EXCEPTION 'Conversation owner must match its creator User session';
      END IF;
      RETURN NEW;
    END;
    $$ LANGUAGE plpgsql;
    """
).execute_if(dialect="postgresql")
_CONVERSATION_SESSION_TRIGGER_CREATE = DDL(
    """CREATE TRIGGER trg_conversations_validate_creator_session
    BEFORE INSERT OR UPDATE OF tenant_id, owner_user_id, created_by_session_id
    ON conversations FOR EACH ROW EXECUTE FUNCTION bothesis_validate_conversation_session()"""
).execute_if(dialect="postgresql")

event.listen(Item.__table__, "after_create", _ITEM_PARENT_TRIGGER)
event.listen(Item.__table__, "after_create", _ITEM_PARENT_TRIGGER_CREATE)
event.listen(RoleAssignment.__table__, "after_create", _ROLE_ASSIGNMENT_TRIGGER)
event.listen(RoleAssignment.__table__, "after_create", _ROLE_ASSIGNMENT_TRIGGER_CREATE)
event.listen(GroupMembership.__table__, "after_create", _GROUP_MEMBERSHIP_TRIGGER)
event.listen(
    GroupMembership.__table__, "after_create", _GROUP_MEMBERSHIP_TRIGGER_CREATE
)
event.listen(IngestionSource.__table__, "after_create", _INGESTION_SOURCE_TRIGGER)
event.listen(
    IngestionSource.__table__, "after_create", _INGESTION_SOURCE_TRIGGER_CREATE
)
event.listen(ExternalResource.__table__, "after_create", _EXTERNAL_RESOURCE_TRIGGER)
event.listen(
    ExternalResource.__table__, "after_create", _EXTERNAL_RESOURCE_TRIGGER_CREATE
)
event.listen(ApprovalRequest.__table__, "after_create", _APPROVAL_REQUEST_TRIGGER)
event.listen(
    ApprovalRequest.__table__, "after_create", _APPROVAL_REQUEST_TRIGGER_CREATE
)
event.listen(Base.metadata, "after_create", _TENANT_PUBLIC_ACCESS_TRIGGER)
event.listen(Base.metadata, "after_create", _TENANT_PUBLIC_ACCESS_TRIGGER_CREATE)
event.listen(Base.metadata, "after_create", _ACCESS_SESSION_TRIGGER)
event.listen(Base.metadata, "after_create", _ACCESS_SESSION_TRIGGER_CREATE)
event.listen(Base.metadata, "after_create", _CONVERSATION_SESSION_TRIGGER)
event.listen(Base.metadata, "after_create", _CONVERSATION_SESSION_TRIGGER_CREATE)


__all__ = [
    "ApprovalRequest",
    "AccessSession",
    "ArtifactRevision",
    "AuditLog",
    "AuthIdentity",
    "Base",
    "Citation",
    "Conversation",
    "Group",
    "GroupMembership",
    "Item",
    "ExternalResource",
    "ItemUpload",
    "Memory",
    "Message",
    "MessageItem",
    "Permission",
    "IngestionSource",
    "IntegrationConnection",
    "IntegrationCredential",
    "Role",
    "RoleAssignment",
    "RolePermission",
    "Tenant",
    "TenantMembership",
    "User",
]
