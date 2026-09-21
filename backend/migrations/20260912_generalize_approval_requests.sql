-- Consolidate the two request lifecycles without deleting their history.
BEGIN;

CREATE TABLE approval_requests (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    requester_user_id uuid NOT NULL,
    request_type varchar(32) NOT NULL,
    target_id varchar(512) NOT NULL,
    details jsonb NOT NULL DEFAULT '{}'::jsonb,
    reason text,
    status varchar(16) NOT NULL DEFAULT 'pending',
    decided_by_user_id uuid,
    decision_note text,
    decided_at timestamp with time zone,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT pk_approval_requests PRIMARY KEY (id),
    CONSTRAINT fk_approval_requests_tenant_id_tenants
        FOREIGN KEY (tenant_id) REFERENCES tenants (id),
    CONSTRAINT fk_approval_requests_requester_user_id_users
        FOREIGN KEY (requester_user_id) REFERENCES users (id),
    CONSTRAINT fk_approval_requests_decided_by_user_id_users
        FOREIGN KEY (decided_by_user_id) REFERENCES users (id),
    CONSTRAINT ck_approval_requests_approval_request_type_is_valid
        CHECK (request_type IN ('resource_access', 'plugin_installation')),
    CONSTRAINT ck_approval_requests_approval_request_status_is_valid
        CHECK (status IN ('pending', 'approved', 'denied', 'cancelled')),
    CONSTRAINT ck_approval_requests_approval_request_details_is_object
        CHECK (jsonb_typeof(details) = 'object')
);

INSERT INTO approval_requests (
    id, tenant_id, requester_user_id, request_type, target_id, details,
    reason, status, decided_by_user_id, decision_note, decided_at,
    deleted_at, created_at, updated_at
)
SELECT
    id,
    tenant_id,
    requester_user_id,
    'resource_access',
    collection_item_id::text,
    jsonb_build_object('role', requested_role),
    reason,
    CASE WHEN status IN ('pending', 'approved', 'denied', 'cancelled') THEN status ELSE 'pending' END,
    reviewed_by_user_id,
    review_note,
    reviewed_at,
    deleted_at,
    created_at,
    updated_at
FROM access_requests;

INSERT INTO approval_requests (
    id, tenant_id, requester_user_id, request_type, target_id, details,
    reason, status, decided_by_user_id, decision_note, decided_at,
    deleted_at, created_at, updated_at
)
SELECT
    id,
    tenant_id,
    requester_user_id,
    'plugin_installation',
    connector_key,
    '{}'::jsonb,
    reason,
    status,
    reviewed_by_user_id,
    review_note,
    reviewed_at,
    deleted_at,
    created_at,
    updated_at
FROM app_requests;

-- Keep every legacy record. Where the former schema allowed duplicate pending
-- requests, retain the newest as pending and close older duplicates.
WITH duplicates AS (
    SELECT id,
           row_number() OVER (
               PARTITION BY tenant_id, requester_user_id, request_type, target_id
               ORDER BY created_at DESC, id DESC
           ) AS ordinal
    FROM approval_requests
    WHERE status = 'pending' AND deleted_at IS NULL
)
UPDATE approval_requests request
SET status = 'cancelled',
    decision_note = COALESCE(request.decision_note, 'Cancelled during approval-request consolidation.'),
    decided_at = COALESCE(request.decided_at, request.updated_at)
FROM duplicates
WHERE request.id = duplicates.id AND duplicates.ordinal > 1;

CREATE INDEX ix_approval_requests_tenant_id_status_created_at
    ON approval_requests (tenant_id, status, created_at);
CREATE INDEX ix_approval_requests_requester_user_id_status
    ON approval_requests (requester_user_id, status);
CREATE INDEX ix_approval_requests_request_type_target_id
    ON approval_requests (request_type, target_id);
CREATE UNIQUE INDEX uq_approval_requests_pending_logical_target
    ON approval_requests (tenant_id, requester_user_id, request_type, target_id)
    WHERE status = 'pending' AND deleted_at IS NULL;

CREATE FUNCTION bothesis_validate_approval_request() RETURNS trigger AS $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM tenant_memberships membership
        WHERE membership.tenant_id = NEW.tenant_id
          AND membership.user_id = NEW.requester_user_id
          AND membership.deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Approval Request requester must belong to its tenant';
    END IF;
    IF NEW.decided_by_user_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM tenant_memberships membership
        WHERE membership.tenant_id = NEW.tenant_id
          AND membership.user_id = NEW.decided_by_user_id
          AND membership.deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Approval Request decider must belong to its tenant';
    END IF;
    IF NEW.request_type = 'resource_access' AND NOT EXISTS (
        SELECT 1 FROM items item
        WHERE item.id = NEW.target_id::uuid
          AND item.tenant_id = NEW.tenant_id
          AND item.item_type = 'collection'
          AND item.deleted_at IS NULL
    ) THEN
        RAISE EXCEPTION 'Resource access Approval Request target must be a Collection in the requester tenant';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_approval_requests_validate
BEFORE INSERT OR UPDATE OF tenant_id, requester_user_id, request_type, target_id, decided_by_user_id
ON approval_requests
FOR EACH ROW EXECUTE FUNCTION bothesis_validate_approval_request();

DROP TABLE app_requests;
DROP TABLE access_requests;

COMMIT;
