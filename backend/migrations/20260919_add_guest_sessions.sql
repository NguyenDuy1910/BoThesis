BEGIN;

ALTER TABLE tenants
    ADD COLUMN visibility varchar(16) NOT NULL DEFAULT 'private',
    ADD COLUMN public_access_role_id uuid;

ALTER TABLE tenants
    ADD CONSTRAINT ck_tenants_tenant_visibility_is_valid
        CHECK (visibility IN ('private', 'public'));

CREATE TABLE auth_identities (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id uuid NOT NULL REFERENCES users (id),
    protocol varchar(24) NOT NULL,
    provider_key varchar(64) NOT NULL,
    issuer text NOT NULL,
    subject text NOT NULL,
    email varchar(255),
    email_verified boolean,
    status varchar(16) NOT NULL DEFAULT 'active',
    profile jsonb NOT NULL DEFAULT '{}'::jsonb,
    last_authenticated_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT uq_auth_identities_issuer_subject UNIQUE (issuer, subject),
    CONSTRAINT ck_auth_identities_auth_identity_protocol_is_valid
        CHECK (protocol IN ('oidc', 'saml')),
    CONSTRAINT ck_auth_identities_auth_identity_status_is_valid
        CHECK (status IN ('active', 'disabled'))
);

CREATE INDEX ix_auth_identities_user_id_status
    ON auth_identities (user_id, status);
CREATE INDEX ix_auth_identities_provider_key_status
    ON auth_identities (provider_key, status);

CREATE TABLE access_sessions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id uuid NOT NULL REFERENCES tenants (id),
    user_id uuid REFERENCES users (id),
    auth_identity_id uuid REFERENCES auth_identities (id),
    kind varchar(24) NOT NULL,
    authentication_method varchar(32) NOT NULL,
    assurance_level varchar(16) NOT NULL DEFAULT 'aal0',
    status varchar(16) NOT NULL DEFAULT 'active',
    token_version integer NOT NULL DEFAULT 1,
    parent_session_id uuid REFERENCES access_sessions (id),
    transition_reason varchar(32),
    expires_at timestamptz NOT NULL,
    idle_expires_at timestamptz,
    last_seen_at timestamptz,
    ended_at timestamptz,
    end_reason varchar(64),
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT ck_access_sessions_access_session_kind_is_valid
        CHECK (kind IN ('guest', 'user')),
    CONSTRAINT ck_access_sessions_access_session_auth_method_is_valid
        CHECK (authentication_method IN ('anonymous', 'oidc', 'saml', 'internal')),
    CONSTRAINT ck_access_sessions_access_session_assurance_level_is_valid
        CHECK (assurance_level IN ('aal0', 'aal1', 'aal2')),
    CONSTRAINT ck_access_sessions_access_session_status_is_valid
        CHECK (status IN ('active', 'superseded', 'revoked', 'expired')),
    CONSTRAINT ck_access_sessions_access_session_token_version_is_valid
        CHECK (token_version >= 1),
    CONSTRAINT ck_access_sessions_access_session_subject_is_complete
        CHECK (
            (kind = 'guest' AND user_id IS NULL AND auth_identity_id IS NULL
                AND authentication_method = 'anonymous' AND assurance_level = 'aal0')
            OR
            (kind = 'user' AND user_id IS NOT NULL
                AND authentication_method <> 'anonymous')
        ),
    CONSTRAINT ck_access_sessions_access_session_transition_is_complete
        CHECK ((parent_session_id IS NULL) = (transition_reason IS NULL)),
    CONSTRAINT ck_access_sessions_access_session_end_is_complete
        CHECK (
            (status = 'active' AND ended_at IS NULL)
            OR (status <> 'active' AND ended_at IS NOT NULL)
        )
);

CREATE INDEX ix_access_sessions_user_id_status
    ON access_sessions (user_id, status);
CREATE INDEX ix_access_sessions_auth_identity_id_status
    ON access_sessions (auth_identity_id, status);
CREATE INDEX ix_access_sessions_tenant_id_kind_status
    ON access_sessions (tenant_id, kind, status);
CREATE INDEX ix_access_sessions_parent_session_id
    ON access_sessions (parent_session_id);
CREATE INDEX ix_access_sessions_status_expires_at
    ON access_sessions (status, expires_at);
CREATE INDEX ix_access_sessions_status_idle_expires_at
    ON access_sessions (status, idle_expires_at);

INSERT INTO roles (
    id, tenant_id, code, display_name, scope_type, is_system, status,
    created_at, updated_at
)
VALUES (
    gen_random_uuid(), NULL, 'guest', 'Guest', 'tenant', true, 'active',
    now(), now()
)
ON CONFLICT (tenant_id, code) DO UPDATE
SET display_name = EXCLUDED.display_name,
    scope_type = EXCLUDED.scope_type,
    is_system = true,
    status = 'active',
    updated_at = now();

INSERT INTO role_permissions (role_id, permission_code, deleted_at)
SELECT role.id, permission.code, NULL
FROM roles role
JOIN permissions permission ON permission.code IN (
    'collection.read',
    'knowledge.read',
    'tenant.read'
)
WHERE role.tenant_id IS NULL
  AND role.code = 'guest'
  AND role.is_system
ON CONFLICT (role_id, permission_code) DO UPDATE
SET deleted_at = NULL,
    updated_at = now();

UPDATE tenants
SET visibility = 'public',
    public_access_role_id = (
        SELECT id FROM roles
        WHERE tenant_id IS NULL AND code = 'guest' AND status = 'active'
        LIMIT 1
    )
WHERE code = 'local';

ALTER TABLE tenants
    ADD CONSTRAINT fk_tenants_public_access_role_id_roles
        FOREIGN KEY (public_access_role_id) REFERENCES roles (id),
    ADD CONSTRAINT ck_tenants_public_access_is_complete
        CHECK (
            (visibility = 'private' AND public_access_role_id IS NULL)
            OR (visibility = 'public' AND public_access_role_id IS NOT NULL)
        );

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

CREATE TRIGGER trg_tenants_validate_public_access
BEFORE INSERT OR UPDATE OF visibility, public_access_role_id ON tenants
FOR EACH ROW EXECUTE FUNCTION bothesis_validate_tenant_public_access();

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
  IF NEW.parent_session_id IS NULL THEN RETURN NEW; END IF;
  IF NEW.parent_session_id = NEW.id THEN
    RAISE EXCEPTION 'Access Session cannot parent itself';
  END IF;
  SELECT tenant_id, user_id, kind INTO parent_tenant, parent_user, parent_kind
  FROM access_sessions WHERE id = NEW.parent_session_id;
  IF NOT FOUND THEN RAISE EXCEPTION 'Access Session parent must exist'; END IF;
  IF NEW.transition_reason = 'identity_upgrade' THEN
    IF parent_kind <> 'guest' OR NEW.kind <> 'user' OR parent_tenant <> NEW.tenant_id THEN
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

CREATE TRIGGER trg_access_sessions_validate
BEFORE INSERT OR UPDATE OF tenant_id, user_id, auth_identity_id, kind, parent_session_id, transition_reason
ON access_sessions FOR EACH ROW EXECUTE FUNCTION bothesis_validate_access_session();

ALTER TABLE conversations
    ADD COLUMN owner_user_id uuid REFERENCES users (id),
    ADD COLUMN created_by_session_id uuid REFERENCES access_sessions (id);

CREATE TEMP TABLE legacy_conversation_sessions (
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    session_id uuid NOT NULL,
    PRIMARY KEY (tenant_id, user_id)
) ON COMMIT DROP;

INSERT INTO legacy_conversation_sessions (tenant_id, user_id, session_id)
SELECT DISTINCT tenant_id, user_id, gen_random_uuid()
FROM conversations;

INSERT INTO access_sessions (
    id, tenant_id, user_id, kind, authentication_method, assurance_level,
    status, expires_at, ended_at, end_reason, created_at, updated_at
)
SELECT
    session_id, tenant_id, user_id, 'user', 'oidc', 'aal1',
    'expired', now(), now(), 'legacy_conversation_lineage', now(), now()
FROM legacy_conversation_sessions;

UPDATE conversations conversation
SET owner_user_id = conversation.user_id,
    created_by_session_id = legacy.session_id
FROM legacy_conversation_sessions legacy
WHERE legacy.tenant_id = conversation.tenant_id
  AND legacy.user_id = conversation.user_id;

ALTER TABLE conversations
    ALTER COLUMN created_by_session_id SET NOT NULL,
    DROP COLUMN user_id;

CREATE INDEX ix_conversations_tenant_id_owner_user_id_updated_at
    ON conversations (tenant_id, owner_user_id, updated_at);
CREATE INDEX ix_conversations_tenant_id_created_by_session_id_updated_at
    ON conversations (tenant_id, created_by_session_id, updated_at);

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

CREATE TRIGGER trg_conversations_validate_creator_session
BEFORE INSERT OR UPDATE OF tenant_id, owner_user_id, created_by_session_id
ON conversations FOR EACH ROW EXECUTE FUNCTION bothesis_validate_conversation_session();

ALTER TABLE audit_logs
    ADD COLUMN actor_session_id uuid REFERENCES access_sessions (id);

CREATE INDEX ix_audit_logs_actor_session_id_created_at
    ON audit_logs (actor_session_id, created_at);

ALTER TABLE users
    DROP CONSTRAINT IF EXISTS ck_users_user_guest_identity_is_complete,
    DROP CONSTRAINT IF EXISTS ck_users_user_identity_kind_is_valid,
    DROP CONSTRAINT IF EXISTS uq_users_guest_session_id,
    DROP COLUMN IF EXISTS identity_kind,
    DROP COLUMN IF EXISTS guest_session_id,
    DROP COLUMN IF EXISTS guest_expires_at;

COMMIT;
