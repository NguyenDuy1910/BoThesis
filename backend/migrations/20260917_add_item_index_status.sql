-- Raw resource availability and derived semantic-index readiness are distinct
-- lifecycles. An Item remains usable through its storage-backed capabilities
-- while this state is pending, processing, or failed.
ALTER TABLE items ADD COLUMN index_status varchar(16);

UPDATE items
SET index_status = CASE
    WHEN item_type = 'collection' THEN NULL
    WHEN status = 'processing' THEN 'processing'
    WHEN status = 'unsupported' THEN 'unsupported'
    WHEN status = 'failed' THEN 'failed'
    WHEN metadata ? 'processing'
         AND (metadata -> 'processing') ? 'index_schema_version' THEN 'ready'
    ELSE 'pending'
END;

ALTER TABLE items
    ADD CONSTRAINT ck_items_item_index_status_is_valid
    CHECK (
        index_status IS NULL
        OR index_status IN ('pending', 'processing', 'ready', 'failed', 'unsupported')
    );

ALTER TABLE items
    ADD CONSTRAINT ck_items_item_index_status_matches_type
    CHECK (
        (item_type = 'collection' AND index_status IS NULL)
        OR (item_type = 'document' AND index_status IS NOT NULL)
    );
