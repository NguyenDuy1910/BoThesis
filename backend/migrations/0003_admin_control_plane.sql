BEGIN;

CREATE TABLE IF NOT EXISTS groups (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    code varchar(64) NOT NULL,
    display_name varchar(255) NOT NULL,
    description text,
    principal_token varchar(512) NOT NULL,
    permission_codes text[] NOT NULL DEFAULT '{}',
    status varchar(16) NOT NULL DEFAULT 'active',
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_groups_tenant_id_code UNIQUE (tenant_id, code),
    CONSTRAINT uq_groups_tenant_id_principal_token UNIQUE (tenant_id, principal_token)
);

CREATE INDEX IF NOT EXISTS ix_groups_tenant_id_status
    ON groups (tenant_id, status);

CREATE TABLE IF NOT EXISTS group_memberships (
    group_id uuid NOT NULL REFERENCES groups(id),
    user_id uuid NOT NULL REFERENCES users(id),
    status varchar(16) NOT NULL DEFAULT 'active',
    joined_at timestamptz,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (group_id, user_id)
);

CREATE INDEX IF NOT EXISTS ix_group_memberships_user_id_status
    ON group_memberships (user_id, status);

CREATE INDEX IF NOT EXISTS ix_group_memberships_group_id_status
    ON group_memberships (group_id, status);

CREATE TABLE IF NOT EXISTS access_requests (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    requester_user_id uuid NOT NULL REFERENCES users(id),
    resource_type varchar(32) NOT NULL,
    resource_id varchar(512) NOT NULL,
    access_type varchar(32) NOT NULL,
    reason text,
    status varchar(16) NOT NULL DEFAULT 'pending',
    reviewed_by_user_id uuid REFERENCES users(id),
    review_note text,
    reviewed_at timestamptz,
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_access_requests_tenant_id_status_created_at
    ON access_requests (tenant_id, status, created_at);

CREATE INDEX IF NOT EXISTS ix_access_requests_requester_user_id_status
    ON access_requests (requester_user_id, status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_access_requests_pending_resource
    ON access_requests (tenant_id, requester_user_id, resource_type, resource_id, access_type)
    WHERE status = 'pending' AND deleted_at IS NULL;

CREATE TABLE IF NOT EXISTS acl_policies (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    name varchar(255) NOT NULL,
    resource_type varchar(32) NOT NULL,
    resource_id varchar(512) NOT NULL,
    allowed_principal_tokens text[] NOT NULL DEFAULT '{}',
    denied_principal_tokens text[] NOT NULL DEFAULT '{}',
    status varchar(16) NOT NULL DEFAULT 'active',
    created_by_user_id uuid REFERENCES users(id),
    deleted_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_acl_policies_tenant_id_name UNIQUE (tenant_id, name)
);

CREATE INDEX IF NOT EXISTS ix_acl_policies_tenant_id_resource_type_resource_id
    ON acl_policies (tenant_id, resource_type, resource_id);

CREATE INDEX IF NOT EXISTS ix_acl_policies_tenant_id_status
    ON acl_policies (tenant_id, status);

CREATE TABLE IF NOT EXISTS audit_logs (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id),
    actor_user_id uuid REFERENCES users(id),
    action varchar(96) NOT NULL,
    resource_type varchar(32) NOT NULL,
    resource_id varchar(512),
    outcome varchar(16) NOT NULL DEFAULT 'success',
    details jsonb NOT NULL DEFAULT '{}',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_id_created_at
    ON audit_logs (tenant_id, created_at);

CREATE INDEX IF NOT EXISTS ix_audit_logs_tenant_id_action_created_at
    ON audit_logs (tenant_id, action, created_at);

CREATE INDEX IF NOT EXISTS ix_audit_logs_actor_user_id_created_at
    ON audit_logs (actor_user_id, created_at);

COMMIT;
