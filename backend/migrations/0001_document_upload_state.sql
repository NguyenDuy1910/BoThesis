BEGIN;

ALTER TABLE documents
    ADD COLUMN IF NOT EXISTS upload_status varchar(16) NOT NULL DEFAULT 'not_applicable',
    ADD COLUMN IF NOT EXISTS content_sha256 varchar(64),
    ADD COLUMN IF NOT EXISTS upload_idempotency_key varchar(128),
    ADD COLUMN IF NOT EXISTS uploaded_at timestamptz;

CREATE INDEX IF NOT EXISTS ix_documents_owner_user_id_upload_status
    ON documents (owner_user_id, upload_status);

CREATE UNIQUE INDEX IF NOT EXISTS uq_documents_owner_user_id_upload_idempotency_key
    ON documents (owner_user_id, upload_idempotency_key)
    WHERE upload_idempotency_key IS NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_documents_document_upload_status_is_valid'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT ck_documents_document_upload_status_is_valid
            CHECK (upload_status IN ('not_applicable', 'pending', 'available', 'failed'));
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_documents_document_content_sha256_is_valid'
    ) THEN
        ALTER TABLE documents
            ADD CONSTRAINT ck_documents_document_content_sha256_is_valid
            CHECK (content_sha256 IS NULL OR content_sha256 ~ '^[0-9a-f]{64}$');
    END IF;
END
$$;

COMMIT;
