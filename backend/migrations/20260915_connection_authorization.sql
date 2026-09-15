-- Give Connections a provider identity and an authorization lifecycle, and
-- give Sources the resource they read. Nothing is dropped: every existing
-- connection, source, credential, Item, and vector point is preserved, and the
-- old status vocabularies are mapped onto the new ones in place.
BEGIN;

-- 1. Connections: who was authorized, what was granted, and when it lapses.
ALTER TABLE integration_connections
    ADD COLUMN IF NOT EXISTS provider_account_id varchar(255),
    ADD COLUMN IF NOT EXISTS provider_account_label varchar(255),
    ADD COLUMN IF NOT EXISTS provider_resource_id varchar(255),
    ADD COLUMN IF NOT EXISTS provider_resource_label varchar(255),
    ADD COLUMN IF NOT EXISTS scopes text[] NOT NULL DEFAULT '{}'::text[],
    ADD COLUMN IF NOT EXISTS status_detail text,
    ADD COLUMN IF NOT EXISTS expires_at timestamptz,
    ADD COLUMN IF NOT EXISTS connected_at timestamptz,
    ADD COLUMN IF NOT EXISTS disconnected_at timestamptz,
    ADD COLUMN IF NOT EXISTS last_checked_at timestamptz;

-- 'reauth_required' does not fit the column the old vocabulary was sized for.
ALTER TABLE integration_connections ALTER COLUMN status TYPE varchar(32);

-- A connection that already worked has been connected since it was validated;
-- the closest durable evidence of that is when it was last updated.
UPDATE integration_connections
SET connected_at = COALESCE(connected_at, updated_at)
WHERE status = 'active';

UPDATE integration_connections
SET disconnected_at = COALESCE(disconnected_at, updated_at)
WHERE status = 'disabled';

-- 'active' described a grant that reached its provider; 'disabled' described
-- one that was switched off. Both now say so in the connection's own words.
UPDATE integration_connections SET status = 'connected'    WHERE status = 'active';
UPDATE integration_connections SET status = 'disconnected' WHERE status = 'disabled';

ALTER TABLE integration_connections ALTER COLUMN status SET DEFAULT 'draft';

ALTER TABLE integration_connections
    DROP CONSTRAINT IF EXISTS ck_integration_connections_connection_status_is_valid;
ALTER TABLE integration_connections
    ADD CONSTRAINT ck_integration_connections_connection_status_is_valid
    CHECK (status IN ('draft', 'connected', 'expired', 'reauth_required',
                      'revoked', 'error', 'disconnected'));

-- Authorizing the same provider account twice must reuse one record, so that
-- every source already built on it keeps working.
CREATE UNIQUE INDEX IF NOT EXISTS uq_integration_connections_provider_account
    ON integration_connections (
        tenant_id, connector_key, owner_type, owner_user_id,
        provider_account_id, provider_resource_id
    )
    WHERE deleted_at IS NULL AND provider_account_id IS NOT NULL;

-- 2. Sources: which resource, and whether anything runs on a schedule.
ALTER TABLE ingestion_sources
    ADD COLUMN IF NOT EXISTS resource_type varchar(64),
    ADD COLUMN IF NOT EXISTS external_resource_id text,
    ADD COLUMN IF NOT EXISTS sync_mode varchar(16) NOT NULL DEFAULT 'manual',
    ADD COLUMN IF NOT EXISTS status_detail text;

-- Lift the resource each existing source already reads out of its config, so
-- duplicate detection and the resource picker agree with what is running.
UPDATE ingestion_sources AS source
SET resource_type = 'space',
    external_resource_id = source.config ->> 'space'
FROM integration_connections AS connection
WHERE connection.id = source.integration_connection_id
  AND connection.connector_key = 'confluence'
  AND source.external_resource_id IS NULL
  AND COALESCE(source.config ->> 'space', '') <> ''
  AND COALESCE(source.config ->> 'page_id', '') = '';

UPDATE ingestion_sources AS source
SET resource_type = 'shared_drive',
    external_resource_id = source.config ->> 'shared_drive_id'
FROM integration_connections AS connection
WHERE connection.id = source.integration_connection_id
  AND connection.connector_key = 'google_drive'
  AND source.external_resource_id IS NULL
  AND COALESCE(source.config ->> 'shared_drive_id', '') <> '';

UPDATE ingestion_sources AS source
SET resource_type = 'folder',
    external_resource_id = source.config ->> 'folder_id'
FROM integration_connections AS connection
WHERE connection.id = source.integration_connection_id
  AND connection.connector_key = 'google_drive'
  AND source.external_resource_id IS NULL
  AND COALESCE(source.config ->> 'folder_id', '') <> '';

-- 'connection_required' does not fit the column the old vocabulary was sized for.
ALTER TABLE ingestion_sources ALTER COLUMN status TYPE varchar(32);

-- 'active' was enablement, not a run in progress; 'error' was a failed run.
UPDATE ingestion_sources SET status = 'ready'  WHERE status = 'active';
UPDATE ingestion_sources SET status = 'failed' WHERE status = 'error';

ALTER TABLE ingestion_sources ALTER COLUMN status SET DEFAULT 'ready';

ALTER TABLE ingestion_sources
    DROP CONSTRAINT IF EXISTS ck_ingestion_sources_ingestion_source_status_is_valid;
ALTER TABLE ingestion_sources
    ADD CONSTRAINT ck_ingestion_sources_ingestion_source_status_is_valid
    CHECK (status IN ('ready', 'paused', 'failed', 'connection_required', 'disabled'));

ALTER TABLE ingestion_sources
    DROP CONSTRAINT IF EXISTS ck_ingestion_sources_ingestion_source_sync_mode_is_valid;
ALTER TABLE ingestion_sources
    ADD CONSTRAINT ck_ingestion_sources_ingestion_source_sync_mode_is_valid
    CHECK (sync_mode IN ('manual', 'scheduled'));

CREATE UNIQUE INDEX IF NOT EXISTS uq_ingestion_sources_connection_resource
    ON ingestion_sources (integration_connection_id, resource_type, external_resource_id)
    WHERE deleted_at IS NULL AND external_resource_id IS NOT NULL;

-- 3. A Confluence connection that borrowed the deployment's own credentials
-- can no longer do so: shared credentials across tenants were not isolation.
-- The flag is removed so the connection reports that it needs its own
-- authorization instead of silently reading someone else's account.
UPDATE integration_connections
SET config = config - 'use_environment_credentials',
    status = 'reauth_required',
    status_detail = 'Connect this Confluence account to BoThesis directly'
WHERE config ? 'use_environment_credentials'
  AND deleted_at IS NULL;

UPDATE ingestion_sources AS source
SET status = 'connection_required',
    status_detail = 'Connect this Confluence account to BoThesis directly'
FROM integration_connections AS connection
WHERE connection.id = source.integration_connection_id
  AND connection.status = 'reauth_required'
  AND source.deleted_at IS NULL
  AND source.status = 'ready';

COMMIT;
