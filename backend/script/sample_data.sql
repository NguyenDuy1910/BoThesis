-- Realistic sample data for the local development workspace.
--
-- Everything lands in the tenant `make db-seed` creates, so the local admin
-- identity sees it the moment the app loads. Re-running is safe: every row is
-- addressed by a fixed id and upserted.
--
-- The shape is chosen to exercise authorization, not just to fill lists:
--   * a member with no Collection grant, who must see nothing
--   * a grant held through a group rather than directly
--   * a nested Collection that inherits, and a sibling that does not
--   * a custom tenant role beside the platform's system roles
--
-- Usage: make db-sample
BEGIN;

-- The workspace these rows belong to, and the administrator db-seed created.
CREATE TEMP TABLE sample_context ON COMMIT DROP AS
SELECT
    (SELECT id FROM tenants WHERE code = 'local') AS tenant_id,
    (SELECT id FROM users WHERE email = 'local-admin@bothesis.dev') AS admin_id;

DO $$
BEGIN
  IF (SELECT tenant_id FROM sample_context) IS NULL
     OR (SELECT admin_id FROM sample_context) IS NULL THEN
    RAISE EXCEPTION 'Run "make db-seed" before "make db-sample".';
  END IF;
END;
$$;

-- 1. People -----------------------------------------------------------------
INSERT INTO users (id, email, display_name, status, preferences, last_login_at, created_at, updated_at)
VALUES
    ('00000000-0000-4000-a000-000000000101', 'linh.tran@bothesis.dev',  'Linh Tran',  true, '{}'::jsonb, now() - interval '2 hours', now(), now()),
    ('00000000-0000-4000-a000-000000000102', 'minh.pham@bothesis.dev',  'Minh Pham',  true, '{}'::jsonb, now() - interval '1 day',   now(), now()),
    ('00000000-0000-4000-a000-000000000103', 'an.le@bothesis.dev',      'An Le',      true, '{}'::jsonb, now() - interval '6 days',  now(), now()),
    ('00000000-0000-4000-a000-000000000104', 'mai.nguyen@bothesis.dev', 'Mai Nguyen', true, '{}'::jsonb, NULL,                       now(), now())
ON CONFLICT (email) DO UPDATE
   SET display_name = EXCLUDED.display_name, status = true, updated_at = now();

INSERT INTO tenant_memberships (user_id, tenant_id, status, joined_at, created_at, updated_at)
SELECT account.id, context.tenant_id, 'active', now() - interval '30 days', now(), now()
FROM sample_context context
CROSS JOIN users account
WHERE account.email IN (
    'linh.tran@bothesis.dev', 'minh.pham@bothesis.dev',
    'an.le@bothesis.dev', 'mai.nguyen@bothesis.dev'
)
ON CONFLICT (user_id, tenant_id) DO UPDATE
   SET status = 'active', deleted_at = NULL;

-- 2. One tenant-defined role beside the platform's own ----------------------
INSERT INTO roles (id, tenant_id, code, display_name, scope_type, is_system, status, created_at, updated_at)
SELECT '00000000-0000-4000-b000-000000000201', context.tenant_id, 'knowledge_curator',
       'Knowledge Curator', 'tenant', false, 'active', now(), now()
FROM sample_context context
ON CONFLICT (tenant_id, code) DO UPDATE
   SET display_name = EXCLUDED.display_name, status = 'active', updated_at = now();

INSERT INTO role_permissions (role_id, permission_code, created_at, updated_at)
SELECT '00000000-0000-4000-b000-000000000201', code, now(), now()
FROM (VALUES ('knowledge.read'), ('item.manage'), ('source.manage'), ('tenant.read')) AS wanted(code)
ON CONFLICT (role_id, permission_code) DO UPDATE SET deleted_at = NULL;

-- 3. Who holds which role ---------------------------------------------------
-- Linh curates knowledge, Minh and An are ordinary members, and Mai is a
-- member with no Collection grant at all: the workspace must look empty to her.
INSERT INTO role_assignments (id, user_id, role_id, tenant_id, created_by_user_id, created_at, updated_at)
SELECT assignment.id, account.id, role.id, context.tenant_id, context.admin_id, now(), now()
FROM sample_context context
CROSS JOIN (VALUES
    ('00000000-0000-4000-c000-000000000301'::uuid, 'linh.tran@bothesis.dev',  'knowledge_curator'),
    ('00000000-0000-4000-c000-000000000302'::uuid, 'minh.pham@bothesis.dev',  'tenant_member'),
    ('00000000-0000-4000-c000-000000000303'::uuid, 'an.le@bothesis.dev',      'tenant_member'),
    ('00000000-0000-4000-c000-000000000304'::uuid, 'mai.nguyen@bothesis.dev', 'tenant_member')
) AS assignment(id, email, role_code)
JOIN users account ON account.email = assignment.email
JOIN roles role
  ON role.code = assignment.role_code
 AND role.scope_type = 'tenant'
 AND (role.tenant_id IS NULL OR role.tenant_id = context.tenant_id)
ON CONFLICT (id) DO UPDATE SET deleted_at = NULL, updated_at = now();

-- 4. Groups -----------------------------------------------------------------
INSERT INTO groups (id, tenant_id, code, display_name, description, status, created_at, updated_at)
SELECT group_row.id, context.tenant_id, group_row.code, group_row.display_name,
       group_row.description, 'active', now(), now()
FROM sample_context context
CROSS JOIN (VALUES
    ('00000000-0000-4000-d000-000000000401'::uuid, 'academic_affairs', 'Academic Affairs', 'Owns academic policy and regulation'),
    ('00000000-0000-4000-d000-000000000402'::uuid, 'student_services', 'Student Services', 'Front-line student support')
) AS group_row(id, code, display_name, description)
ON CONFLICT (tenant_id, code) DO UPDATE
   SET display_name = EXCLUDED.display_name, status = 'active',
       deleted_at = NULL, updated_at = now();

INSERT INTO group_memberships (group_id, user_id, status, joined_at, created_at, updated_at)
SELECT membership.group_id, account.id, 'active', now() - interval '20 days', now(), now()
FROM (VALUES
    ('00000000-0000-4000-d000-000000000401'::uuid, 'linh.tran@bothesis.dev'),
    ('00000000-0000-4000-d000-000000000401'::uuid, 'minh.pham@bothesis.dev'),
    ('00000000-0000-4000-d000-000000000402'::uuid, 'an.le@bothesis.dev')
) AS membership(group_id, email)
JOIN users account ON account.email = membership.email
ON CONFLICT (group_id, user_id) DO UPDATE
   SET status = 'active', deleted_at = NULL;

-- 5. Collections ------------------------------------------------------------
-- Policies
--   ├── Travel and expenses        (inherits — a grant on Policies reaches it)
--   └── Board papers               (its own boundary — grants above stop here)
-- Engineering handbook             (a separate root)
INSERT INTO items (id, tenant_id, item_type, parent_item_id, parent_relation, title,
                   metadata, inherit_access, status, created_by_user_id, created_at, updated_at)
SELECT collection.id, context.tenant_id, 'collection', collection.parent_id,
       CASE WHEN collection.parent_id IS NULL THEN NULL ELSE 'contains' END,
       collection.title, jsonb_build_object('description', collection.description),
       collection.inherit_access, 'ready', context.admin_id, now(), now()
FROM sample_context context
CROSS JOIN (VALUES
    ('00000000-0000-4000-e000-000000000501'::uuid, NULL::uuid, 'Policies', 'Approved university policy', true),
    ('00000000-0000-4000-e000-000000000502'::uuid, '00000000-0000-4000-e000-000000000501'::uuid, 'Travel and expenses', 'Reimbursement rules and forms', true),
    ('00000000-0000-4000-e000-000000000503'::uuid, '00000000-0000-4000-e000-000000000501'::uuid, 'Board papers', 'Restricted: its own access boundary', false),
    ('00000000-0000-4000-e000-000000000504'::uuid, NULL::uuid, 'Engineering handbook', 'How the platform is built and run', true)
) AS collection(id, parent_id, title, description, inherit_access)
ON CONFLICT (id) DO UPDATE
   SET title = EXCLUDED.title, metadata = EXCLUDED.metadata,
       inherit_access = EXCLUDED.inherit_access, deleted_at = NULL, updated_at = now();

-- 6. Documents --------------------------------------------------------------
INSERT INTO items (id, tenant_id, item_type, parent_item_id, parent_relation, document_type,
                   title, mime_type, size_bytes, metadata, status, created_by_user_id,
                   created_at, updated_at)
SELECT document.id, context.tenant_id, 'document', document.parent_id, 'contains',
       document.document_type, document.title, document.mime_type, document.size_bytes,
       '{}'::jsonb, document.status, context.admin_id,
       now() - document.age, now() - document.age
FROM sample_context context
CROSS JOIN (VALUES
    ('00000000-0000-4000-f000-000000000601'::uuid, '00000000-0000-4000-e000-000000000502'::uuid, 'pdf',      'Travel reimbursement policy.pdf', 'application/pdf', 1149000, 'ready',       interval '2 days'),
    ('00000000-0000-4000-f000-000000000602'::uuid, '00000000-0000-4000-e000-000000000502'::uuid, 'docx',     'Manager travel guide.docx',       'application/vnd.openxmlformats-officedocument.wordprocessingml.document', 290816, 'ready', interval '3 days'),
    ('00000000-0000-4000-f000-000000000603'::uuid, '00000000-0000-4000-e000-000000000502'::uuid, 'xlsx',     'Per diem rates 2026.xlsx',        'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet', 98304, 'ready',  interval '5 days'),
    ('00000000-0000-4000-f000-000000000604'::uuid, '00000000-0000-4000-e000-000000000501'::uuid, 'pdf',      'Academic regulations 2026.pdf',   'application/pdf', 2516582, 'ready',       interval '8 days'),
    ('00000000-0000-4000-f000-000000000605'::uuid, '00000000-0000-4000-e000-000000000501'::uuid, 'pdf',      'Admissions procedure.pdf',        'application/pdf', 733184, 'processing',   interval '1 hour'),
    ('00000000-0000-4000-f000-000000000606'::uuid, '00000000-0000-4000-e000-000000000503'::uuid, 'pdf',      'Board minutes, March.pdf',        'application/pdf', 512000, 'ready',        interval '12 days'),
    ('00000000-0000-4000-f000-000000000607'::uuid, '00000000-0000-4000-e000-000000000504'::uuid, 'markdown', 'Runbook: ingestion failures.md',  'text/markdown', 14336, 'ready',          interval '1 day'),
    ('00000000-0000-4000-f000-000000000608'::uuid, '00000000-0000-4000-e000-000000000504'::uuid, 'markdown', 'Architecture overview.md',        'text/markdown', 41984, 'ready',          interval '4 days'),
    ('00000000-0000-4000-f000-000000000609'::uuid, '00000000-0000-4000-e000-000000000504'::uuid, 'pdf',      'Scanned whiteboard.pdf',          'application/pdf', 8388608, 'failed',      interval '2 hours')
) AS document(id, parent_id, document_type, title, mime_type, size_bytes, status, age)
ON CONFLICT (id) DO UPDATE
   SET title = EXCLUDED.title, status = EXCLUDED.status,
       size_bytes = EXCLUDED.size_bytes, deleted_at = NULL, updated_at = now();

-- 7. Who can reach which Collection -----------------------------------------
-- The administrator owns each root. Academic Affairs reads Policies as a
-- group. Linh edits the handbook directly. Board papers is granted to nobody
-- but the administrator, so its own boundary is visible in the UI.
INSERT INTO role_assignments (id, user_id, group_id, role_id, item_id, created_by_user_id, created_at, updated_at)
SELECT grant_row.id,
       CASE WHEN grant_row.email IS NOT NULL THEN account.id END,
       grant_row.group_id,
       role.id,
       grant_row.item_id,
       context.admin_id, now(), now()
FROM sample_context context
CROSS JOIN (VALUES
    ('00000000-0000-4000-c000-000000000311'::uuid, 'local-admin@bothesis.dev', NULL::uuid, '00000000-0000-4000-e000-000000000501'::uuid, 'collection_owner'),
    ('00000000-0000-4000-c000-000000000312'::uuid, 'local-admin@bothesis.dev', NULL::uuid, '00000000-0000-4000-e000-000000000504'::uuid, 'collection_owner'),
    ('00000000-0000-4000-c000-000000000313'::uuid, 'local-admin@bothesis.dev', NULL::uuid, '00000000-0000-4000-e000-000000000503'::uuid, 'collection_owner'),
    ('00000000-0000-4000-c000-000000000314'::uuid, NULL, '00000000-0000-4000-d000-000000000401'::uuid, '00000000-0000-4000-e000-000000000501'::uuid, 'collection_viewer'),
    ('00000000-0000-4000-c000-000000000315'::uuid, 'linh.tran@bothesis.dev', NULL::uuid, '00000000-0000-4000-e000-000000000504'::uuid, 'collection_editor')
) AS grant_row(id, email, group_id, item_id, role_code)
LEFT JOIN users account ON account.email = grant_row.email
JOIN roles role ON role.is_system AND role.code = grant_row.role_code
ON CONFLICT (id) DO UPDATE SET deleted_at = NULL, updated_at = now();

-- 8. A little history so the activity views are not empty --------------------
INSERT INTO audit_logs (id, tenant_id, actor_user_id, action, resource_type, resource_id,
                        outcome, details, created_at)
SELECT event.id, context.tenant_id, context.admin_id, event.action, event.resource_type,
       event.resource_id, event.outcome, '{}'::jsonb, now() - event.age
FROM sample_context context
CROSS JOIN (VALUES
    ('00000000-0000-4000-0a00-000000000701'::uuid, 'collection.created',              'collection', '00000000-0000-4000-e000-000000000501', 'success', interval '30 days'),
    ('00000000-0000-4000-0a00-000000000702'::uuid, 'collection.created',              'collection', '00000000-0000-4000-e000-000000000504', 'success', interval '29 days'),
    ('00000000-0000-4000-0a00-000000000703'::uuid, 'group.created',                   'group',      '00000000-0000-4000-d000-000000000401', 'success', interval '21 days'),
    ('00000000-0000-4000-0a00-000000000704'::uuid, 'collection.access.granted',       'collection', '00000000-0000-4000-e000-000000000501', 'success', interval '20 days'),
    ('00000000-0000-4000-0a00-000000000705'::uuid, 'role.created',                    'role',       '00000000-0000-4000-b000-000000000201', 'success', interval '14 days'),
    ('00000000-0000-4000-0a00-000000000706'::uuid, 'user.created',                    'user',       '00000000-0000-4000-a000-000000000101', 'success', interval '13 days'),
    ('00000000-0000-4000-0a00-000000000707'::uuid, 'item.reprocessed',                'item',       '00000000-0000-4000-f000-000000000609', 'failure', interval '2 hours'),
    ('00000000-0000-4000-0a00-000000000708'::uuid, 'approval_request.resource_access.created', 'approval_request', '00000000-0000-4000-e000-000000000503', 'success', interval '40 minutes')
) AS event(id, action, resource_type, resource_id, outcome, age)
ON CONFLICT (id) DO NOTHING;

-- 9. One pending access request, so the review queue has something in it -----
INSERT INTO approval_requests (id, tenant_id, requester_user_id, request_type, target_id,
                               requested_role_id, details, reason, status, created_at, updated_at)
SELECT '00000000-0000-4000-0b00-000000000801', context.tenant_id, account.id,
       'resource_access', '00000000-0000-4000-e000-000000000503', role.id, '{}'::jsonb,
       'I need the March board minutes to finish the funding summary.',
       'pending', now() - interval '40 minutes', now() - interval '40 minutes'
FROM sample_context context
JOIN users account ON account.email = 'minh.pham@bothesis.dev'
JOIN roles role ON role.is_system AND role.code = 'collection_viewer'
ON CONFLICT (id) DO NOTHING;

COMMIT;
