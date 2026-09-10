-- Keep provider execution recovery state separate from Conversations and Items.
-- Item IDs in manifest remain portable; provider container/file IDs stay opaque.
BEGIN;

CREATE TABLE sandbox_sessions (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    conversation_id uuid NOT NULL,
    user_id uuid NOT NULL,
    provider varchar(64) NOT NULL,
    manifest jsonb DEFAULT '{}'::jsonb NOT NULL,
    provider_state jsonb DEFAULT '{}'::jsonb NOT NULL,
    status varchar(16) DEFAULT 'active' NOT NULL,
    last_used_at timestamp with time zone,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone DEFAULT now() NOT NULL,
    updated_at timestamp with time zone DEFAULT now() NOT NULL,
    CONSTRAINT pk_sandbox_sessions PRIMARY KEY (id),
    CONSTRAINT fk_sandbox_sessions_tenant_id_tenants
        FOREIGN KEY (tenant_id) REFERENCES tenants (id),
    CONSTRAINT fk_sandbox_sessions_conversation_id_conversations
        FOREIGN KEY (conversation_id) REFERENCES conversations (id),
    CONSTRAINT fk_sandbox_sessions_user_id_users
        FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT ck_sandbox_sessions_sandbox_session_status_is_valid
        CHECK (status IN ('active', 'expired', 'closed')),
    CONSTRAINT ck_sandbox_sessions_sandbox_manifest_is_object
        CHECK (jsonb_typeof(manifest) = 'object'),
    CONSTRAINT ck_sandbox_sessions_sandbox_provider_state_is_object
        CHECK (jsonb_typeof(provider_state) = 'object')
);

CREATE INDEX ix_sandbox_sessions_tenant_id_conversation_id_status
    ON sandbox_sessions (tenant_id, conversation_id, status);
CREATE INDEX ix_sandbox_sessions_conversation_id_provider_status
    ON sandbox_sessions (conversation_id, provider, status);

COMMIT;
