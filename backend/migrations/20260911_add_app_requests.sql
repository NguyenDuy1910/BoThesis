BEGIN;

CREATE TABLE app_requests (
    id uuid NOT NULL,
    tenant_id uuid NOT NULL,
    requester_user_id uuid NOT NULL,
    connector_key varchar(64) NOT NULL,
    reason text,
    status varchar(16) NOT NULL DEFAULT 'pending',
    reviewed_by_user_id uuid,
    review_note text,
    reviewed_at timestamp with time zone,
    deleted_at timestamp with time zone,
    created_at timestamp with time zone NOT NULL DEFAULT now(),
    updated_at timestamp with time zone NOT NULL DEFAULT now(),
    CONSTRAINT pk_app_requests PRIMARY KEY (id),
    CONSTRAINT fk_app_requests_tenant_id_tenants FOREIGN KEY (tenant_id) REFERENCES tenants (id),
    CONSTRAINT fk_app_requests_requester_user_id_users FOREIGN KEY (requester_user_id) REFERENCES users (id),
    CONSTRAINT fk_app_requests_reviewed_by_user_id_users FOREIGN KEY (reviewed_by_user_id) REFERENCES users (id),
    CONSTRAINT ck_app_requests_app_request_status_is_valid CHECK (status IN ('pending', 'approved', 'denied', 'cancelled'))
);

CREATE INDEX ix_app_requests_tenant_id_status_created_at ON app_requests (tenant_id, status, created_at);
CREATE INDEX ix_app_requests_requester_user_id_status ON app_requests (requester_user_id, status);

COMMIT;
