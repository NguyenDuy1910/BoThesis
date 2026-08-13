BEGIN;

ALTER TABLE tenant_memberships
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

ALTER TABLE document_chunks
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

ALTER TABLE message_documents
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

ALTER TABLE user_principal_tokens
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

ALTER TABLE document_blobs
    ADD COLUMN IF NOT EXISTS deleted_at timestamptz;

CREATE INDEX IF NOT EXISTS ix_document_chunks_document_id_deleted_at
    ON document_chunks (document_id, deleted_at);

CREATE INDEX IF NOT EXISTS ix_message_documents_message_id_deleted_at
    ON message_documents (message_id, deleted_at);

CREATE INDEX IF NOT EXISTS ix_user_principal_tokens_user_id_deleted_at
    ON user_principal_tokens (user_id, deleted_at);

COMMIT;
