-- Converge every authorization mechanism on one scoped RBAC model.
--
-- Before: a root-admin boolean on users, one role per tenant membership, a
-- text[] of permission codes on roles, and a separate collection_access ACL.
-- After: permissions, role_permissions, and role_assignments, where a role
-- assignment is the only way any principal holds any capability anywhere.
--
-- Every existing grant is carried across before the old structures are
-- dropped: a root admin becomes a platform_admin assignment, a membership role
-- becomes a tenant-scoped assignment, and an owner/editor/viewer ACL row
-- becomes a Collection-scoped assignment.
BEGIN;

-- 1. Permission catalog -----------------------------------------------------
CREATE TABLE permissions (
    code varchar(64) NOT NULL,
    description text NOT NULL,
    scope_types text[] NOT NULL DEFAULT '{}'::text[],
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT pk_permissions PRIMARY KEY (code)
);

INSERT INTO permissions (code, description, scope_types) VALUES
    ('platform.tenant.read', 'Read the workspace inventory and platform overview', ARRAY['platform']),
    ('platform.user.read', 'Read user identities across workspaces', ARRAY['platform']),
    ('platform.audit.read', 'Read audit events across workspaces', ARRAY['platform']),
    ('platform.health.read', 'Read platform service health', ARRAY['platform']),
    ('access.manage', 'Review access requests and manage Collection access', ARRAY['tenant']),
    ('audit.read', 'Read tenant administration audit events', ARRAY['tenant']),
    ('group.manage', 'Manage groups and group membership', ARRAY['tenant']),
    ('item.manage', 'Manage canonical Item lifecycle and indexing', ARRAY['tenant']),
    ('knowledge.read', 'Read tenant knowledge through permission filters', ARRAY['tenant']),
    ('role.manage', 'Manage roles and role assignments', ARRAY['tenant']),
    ('source.manage', 'Manage data sources, scopes, and ingestion', ARRAY['tenant']),
    ('tenant.read', 'Read the tenant profile and administration overview', ARRAY['tenant']),
    ('tenant.manage', 'Manage tenant profile and settings', ARRAY['tenant']),
    ('user.manage', 'Manage users and tenant membership', ARRAY['tenant']),
    ('collection.read', 'Read a Collection and the Documents it contains', ARRAY['collection', 'tenant']),
    ('collection.update', 'Add, update, and remove content in a Collection', ARRAY['collection', 'tenant']),
    ('collection.delete', 'Delete a Collection', ARRAY['collection', 'tenant']),
    ('collection.share', 'Grant and revoke access to a Collection', ARRAY['collection', 'tenant']);

-- 2. Roles gain a scope and may belong to the platform ----------------------
ALTER TABLE roles ALTER COLUMN tenant_id DROP NOT NULL;
ALTER TABLE roles ADD COLUMN scope_type varchar(16) NOT NULL DEFAULT 'tenant';
ALTER TABLE roles ADD COLUMN is_system boolean NOT NULL DEFAULT false;
ALTER TABLE roles ALTER COLUMN scope_type DROP DEFAULT;

-- The old uniqueness was a table constraint; a NULL tenant_id needs an index
-- with NULLS NOT DISTINCT instead, so the constraint goes first.
ALTER TABLE roles DROP CONSTRAINT IF EXISTS uq_roles_tenant_id_code;
DROP INDEX IF EXISTS uq_roles_tenant_id_code;

CREATE TABLE role_permissions (
    role_id uuid NOT NULL,
    permission_code varchar(64) NOT NULL,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT pk_role_permissions PRIMARY KEY (role_id, permission_code),
    CONSTRAINT fk_role_permissions_role_id_roles
        FOREIGN KEY (role_id) REFERENCES roles (id),
    CONSTRAINT fk_role_permissions_permission_code_permissions
        FOREIGN KEY (permission_code) REFERENCES permissions (code)
);

-- Carry existing tenant role permissions across. The two wildcard codes the
-- old model recognized ('admin' and '*:*') expand to the full tenant set they
-- actually granted, so no role silently loses or gains capability.
INSERT INTO role_permissions (role_id, permission_code)
SELECT DISTINCT role.id, permission.code
FROM roles role
JOIN LATERAL unnest(role.permission_codes) AS granted(code) ON true
JOIN permissions permission
  ON permission.code = granted.code
  OR (granted.code IN ('admin', '*:*') AND 'tenant' = ANY (permission.scope_types))
ON CONFLICT DO NOTHING;

-- 3. The system roles the platform defines ----------------------------------
INSERT INTO roles (id, tenant_id, code, display_name, scope_type, is_system, status, created_at, updated_at)
VALUES
    (gen_random_uuid(), NULL, 'platform_admin', 'Platform Administrator', 'platform', true, 'active', now(), now()),
    (gen_random_uuid(), NULL, 'tenant_admin', 'Workspace Administrator', 'tenant', true, 'active', now(), now()),
    (gen_random_uuid(), NULL, 'tenant_member', 'Workspace Member', 'tenant', true, 'active', now(), now()),
    (gen_random_uuid(), NULL, 'collection_owner', 'Collection Owner', 'collection', true, 'active', now(), now()),
    (gen_random_uuid(), NULL, 'collection_editor', 'Collection Editor', 'collection', true, 'active', now(), now()),
    (gen_random_uuid(), NULL, 'collection_viewer', 'Collection Viewer', 'collection', true, 'active', now(), now());

INSERT INTO role_permissions (role_id, permission_code)
SELECT role.id, permission.code
FROM roles role
JOIN permissions permission ON (
    (role.code = 'platform_admin' AND 'platform' = ANY (permission.scope_types))
 OR (role.code = 'tenant_admin' AND permission.scope_types <> ARRAY['platform'])
 OR (role.code = 'tenant_member' AND permission.code IN ('tenant.read', 'knowledge.read'))
 OR (role.code = 'collection_owner' AND permission.code IN (
        'collection.read', 'collection.update', 'collection.delete', 'collection.share'))
 OR (role.code = 'collection_editor' AND permission.code IN (
        'collection.read', 'collection.update'))
 OR (role.code = 'collection_viewer' AND permission.code = 'collection.read')
)
WHERE role.is_system
ON CONFLICT DO NOTHING;

ALTER TABLE roles DROP COLUMN permission_codes;
ALTER TABLE roles
    ADD CONSTRAINT ck_roles_role_scope_type_is_valid
        CHECK (scope_type IN ('platform', 'tenant', 'collection')),
    ADD CONSTRAINT ck_roles_role_ownership_matches_system_flag
        CHECK ((is_system AND tenant_id IS NULL) OR (NOT is_system AND tenant_id IS NOT NULL)),
    ADD CONSTRAINT ck_roles_tenant_defined_role_is_tenant_scoped
        CHECK (is_system OR scope_type = 'tenant');
CREATE UNIQUE INDEX uq_roles_tenant_id_code
    ON roles (tenant_id, code) NULLS NOT DISTINCT;
CREATE INDEX ix_roles_scope_type_status ON roles (scope_type, status);

-- 4. Role assignments -------------------------------------------------------
CREATE TABLE role_assignments (
    id uuid NOT NULL,
    user_id uuid,
    group_id uuid,
    role_id uuid NOT NULL,
    tenant_id uuid,
    item_id uuid,
    created_by_user_id uuid,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT pk_role_assignments PRIMARY KEY (id),
    CONSTRAINT fk_role_assignments_user_id_users FOREIGN KEY (user_id) REFERENCES users (id),
    CONSTRAINT fk_role_assignments_group_id_groups FOREIGN KEY (group_id) REFERENCES groups (id),
    CONSTRAINT fk_role_assignments_role_id_roles FOREIGN KEY (role_id) REFERENCES roles (id),
    CONSTRAINT fk_role_assignments_tenant_id_tenants FOREIGN KEY (tenant_id) REFERENCES tenants (id),
    CONSTRAINT fk_role_assignments_item_id_items FOREIGN KEY (item_id) REFERENCES items (id),
    CONSTRAINT fk_role_assignments_created_by_user_id_users
        FOREIGN KEY (created_by_user_id) REFERENCES users (id),
    CONSTRAINT ck_role_assignments_role_assignment_has_one_principal
        CHECK (num_nonnulls(user_id, group_id) = 1),
    CONSTRAINT ck_role_assignments_role_assignment_has_one_scope
        CHECK (num_nonnulls(tenant_id, item_id) <= 1)
);

CREATE UNIQUE INDEX uq_role_assignments_principal_scope_role
    ON role_assignments (user_id, group_id, tenant_id, item_id, role_id)
    NULLS NOT DISTINCT
    WHERE deleted_at IS NULL;
CREATE INDEX ix_role_assignments_user_id_tenant_id ON role_assignments (user_id, tenant_id);
CREATE INDEX ix_role_assignments_group_id_tenant_id ON role_assignments (group_id, tenant_id);
CREATE INDEX ix_role_assignments_item_id ON role_assignments (item_id);
CREATE INDEX ix_role_assignments_role_id ON role_assignments (role_id);

-- Each membership's single role becomes a tenant-scoped assignment.
INSERT INTO role_assignments (id, user_id, role_id, tenant_id, created_at, updated_at, deleted_at)
SELECT gen_random_uuid(), membership.user_id, membership.role_id, membership.tenant_id,
       membership.created_at, membership.updated_at, membership.deleted_at
FROM tenant_memberships membership
JOIN roles role ON role.id = membership.role_id;

-- Root administrators become platform_admin assignments.
INSERT INTO role_assignments (id, user_id, role_id, created_at, updated_at)
SELECT gen_random_uuid(), account.id, role.id, now(), now()
FROM users account
CROSS JOIN roles role
WHERE account.is_root_admin AND role.code = 'platform_admin' AND role.is_system;

-- Collection ACL rows become Collection-scoped assignments, tombstones kept.
INSERT INTO role_assignments (
    id, user_id, group_id, role_id, item_id, created_by_user_id,
    deleted_at, created_at, updated_at
)
SELECT
    gen_random_uuid(),
    CASE WHEN grant_row.principal_type = 'user' THEN grant_row.principal_id END,
    CASE WHEN grant_row.principal_type = 'group' THEN grant_row.principal_id END,
    role.id,
    grant_row.item_id,
    grant_row.created_by_user_id,
    grant_row.deleted_at,
    grant_row.created_at,
    grant_row.updated_at
FROM collection_access grant_row
JOIN roles role
  ON role.is_system AND role.code = 'collection_' || grant_row.role;

-- 5. Membership is identity only; authorization moved out ------------------
DROP INDEX IF EXISTS ix_tenant_memberships_role_id;
ALTER TABLE tenant_memberships DROP COLUMN role_id;

-- 6. Users are identity only ------------------------------------------------
ALTER TABLE users DROP COLUMN is_root_admin;

-- 7. Access requests resolve to a real role --------------------------------
ALTER TABLE approval_requests ADD COLUMN requested_role_id uuid
    REFERENCES roles (id);
UPDATE approval_requests request
SET requested_role_id = role.id,
    details = '{}'::jsonb
FROM roles role
WHERE request.request_type = 'resource_access'
  AND role.is_system
  AND role.code = 'collection_' || (request.details ->> 'role');
-- A pending request that named no resolvable role cannot be approved into a
-- grant, so it is cancelled rather than left un-actionable.
UPDATE approval_requests
SET status = 'cancelled',
    decision_note = 'Cancelled by the scoped RBAC migration: no resolvable role.',
    decided_at = now()
WHERE request_type = 'resource_access'
  AND requested_role_id IS NULL
  AND status = 'pending';
DELETE FROM approval_requests
WHERE request_type = 'resource_access' AND requested_role_id IS NULL;
ALTER TABLE approval_requests
    ADD CONSTRAINT ck_approval_requests_resource_access_names_a_role
        CHECK ((request_type = 'resource_access') = (requested_role_id IS NOT NULL));

-- 8. Platform actions belong to no tenant ----------------------------------
ALTER TABLE audit_logs ALTER COLUMN tenant_id DROP NOT NULL;
CREATE INDEX ix_audit_logs_created_at ON audit_logs (created_at);

-- 9. Only a Collection can end inheritance ---------------------------------
UPDATE items SET inherit_access = true WHERE item_type <> 'collection';
ALTER TABLE items
    ADD CONSTRAINT ck_items_only_collections_end_inheritance
        CHECK (item_type = 'collection' OR inherit_access);

-- 10. Replace the ACL trigger with the role-assignment trigger -------------
DROP TRIGGER IF EXISTS trg_collection_access_validate ON collection_access;
DROP FUNCTION IF EXISTS bothesis_validate_collection_access();
DROP TABLE collection_access;

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

CREATE TRIGGER trg_role_assignments_validate
BEFORE INSERT OR UPDATE OF user_id, group_id, role_id, tenant_id, item_id
ON role_assignments
FOR EACH ROW WHEN (NEW.deleted_at IS NULL)
EXECUTE FUNCTION bothesis_validate_role_assignment();

-- 11. A group member must belong to the group's tenant ---------------------
UPDATE group_memberships membership
SET status = 'inactive', deleted_at = now()
WHERE membership.deleted_at IS NULL
  AND NOT EXISTS (
    SELECT 1 FROM groups g
    JOIN tenant_memberships m
      ON m.tenant_id = g.tenant_id AND m.deleted_at IS NULL
    WHERE g.id = membership.group_id AND g.deleted_at IS NULL
      AND m.user_id = membership.user_id
  );

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

CREATE TRIGGER trg_group_memberships_validate
BEFORE INSERT OR UPDATE OF group_id, user_id ON group_memberships
FOR EACH ROW WHEN (NEW.deleted_at IS NULL)
EXECUTE FUNCTION bothesis_validate_group_membership();

-- 12. The access-request trigger now also checks the requested role --------
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

DROP TRIGGER IF EXISTS trg_approval_requests_validate ON approval_requests;
CREATE TRIGGER trg_approval_requests_validate
BEFORE INSERT OR UPDATE OF tenant_id, requester_user_id, request_type, target_id, requested_role_id, decided_by_user_id ON approval_requests
FOR EACH ROW EXECUTE FUNCTION bothesis_validate_approval_request();

COMMIT;
