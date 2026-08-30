-- Generalize persisted connector state without changing canonical Item IDs or
-- deleting source lineage. Raw objects and derived vector points are untouched.
BEGIN;

DROP TRIGGER IF EXISTS trg_plugin_bindings_validate ON plugin_bindings;
DROP TRIGGER IF EXISTS trg_item_origins_validate ON item_origins;
DROP FUNCTION IF EXISTS bothesis_validate_plugin_binding();
DROP FUNCTION IF EXISTS bothesis_validate_item_origin();

ALTER TABLE plugin_connections RENAME TO integration_connections;
ALTER TABLE integration_connections RENAME COLUMN plugin_key TO connector_key;
ALTER TABLE integration_connections
    RENAME CONSTRAINT pk_plugin_connections TO pk_integration_connections;
ALTER TABLE integration_connections
    RENAME CONSTRAINT ck_plugin_connections_owner_matches_type
    TO ck_integration_connections_owner_matches_type;
ALTER TABLE integration_connections
    RENAME CONSTRAINT uq_plugin_connections_tenant_id_display_name
    TO uq_integration_connections_tenant_id_display_name;
ALTER TABLE integration_connections
    RENAME CONSTRAINT fk_plugin_connections_tenant_id_tenants
    TO fk_integration_connections_tenant_id_tenants;
ALTER TABLE integration_connections
    RENAME CONSTRAINT fk_plugin_connections_owner_user_id_users
    TO fk_integration_connections_owner_user_id_users;
ALTER TABLE integration_connections
    RENAME CONSTRAINT fk_plugin_connections_created_by_user_id_users
    TO fk_integration_connections_created_by_user_id_users;
ALTER INDEX ix_plugin_connections_owner_user_id_status
    RENAME TO ix_integration_connections_owner_user_id_status;
ALTER INDEX ix_plugin_connections_tenant_id_plugin_key_status
    RENAME TO ix_integration_connections_tenant_id_connector_key_status;

ALTER TABLE plugin_credentials RENAME TO integration_credentials;
ALTER TABLE integration_credentials
    RENAME COLUMN connection_id TO integration_connection_id;
ALTER TABLE integration_credentials
    RENAME CONSTRAINT pk_plugin_credentials TO pk_integration_credentials;
ALTER TABLE integration_credentials
    RENAME CONSTRAINT uq_plugin_credentials_connection_id
    TO uq_integration_credentials_integration_connection_id;
ALTER TABLE integration_credentials
    RENAME CONSTRAINT fk_plugin_credentials_connection_id_plugin_connections
    TO fk_integration_credentials_integration_connection_id_integration_connections;

ALTER TABLE plugin_bindings RENAME TO ingestion_sources;
ALTER TABLE ingestion_sources
    RENAME COLUMN connection_id TO integration_connection_id;
ALTER TABLE ingestion_sources
    RENAME COLUMN last_synced_at TO last_ingested_at;
ALTER TABLE ingestion_sources
    RENAME CONSTRAINT pk_plugin_bindings TO pk_ingestion_sources;
ALTER TABLE ingestion_sources
    RENAME CONSTRAINT fk_plugin_bindings_connection_id_plugin_connections
    TO fk_ingestion_sources_integration_connection_id_integration_connections;
ALTER TABLE ingestion_sources
    RENAME CONSTRAINT fk_plugin_bindings_target_item_id_items
    TO fk_ingestion_sources_target_item_id_items;
ALTER TABLE ingestion_sources
    RENAME CONSTRAINT fk_plugin_bindings_created_by_user_id_users
    TO fk_ingestion_sources_created_by_user_id_users;
ALTER INDEX ix_plugin_bindings_connection_id_status
    RENAME TO ix_ingestion_sources_integration_connection_id_status;
ALTER INDEX ix_plugin_bindings_target_item_id_status
    RENAME TO ix_ingestion_sources_target_item_id_status;

ALTER TABLE item_origins RENAME TO external_resources;
ALTER TABLE external_resources RENAME COLUMN binding_id TO ingestion_source_id;
ALTER TABLE external_resources
    RENAME CONSTRAINT pk_item_origins TO pk_external_resources;
ALTER TABLE external_resources
    RENAME CONSTRAINT uq_item_origins_binding_id_external_id
    TO uq_external_resources_ingestion_source_id_external_id;
ALTER TABLE external_resources
    RENAME CONSTRAINT fk_item_origins_item_id_items
    TO fk_external_resources_item_id_items;
ALTER TABLE external_resources
    RENAME CONSTRAINT fk_item_origins_binding_id_plugin_bindings
    TO fk_external_resources_ingestion_source_id_ingestion_sources;
ALTER INDEX ix_item_origins_item_id RENAME TO ix_external_resources_item_id;
ALTER INDEX ix_item_origins_binding_id_last_seen_at
    RENAME TO ix_external_resources_ingestion_source_id_last_seen_at;

CREATE FUNCTION bothesis_validate_ingestion_source() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM integration_connections c JOIN items i ON i.id = NEW.target_item_id
    WHERE c.id = NEW.integration_connection_id AND c.tenant_id = i.tenant_id
    AND c.deleted_at IS NULL AND i.item_type = 'collection' AND i.deleted_at IS NULL
  ) THEN
    RAISE EXCEPTION
      'Ingestion Source target must be a Collection in the Integration Connection tenant';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_ingestion_sources_validate
BEFORE INSERT OR UPDATE OF integration_connection_id, target_item_id
ON ingestion_sources
FOR EACH ROW EXECUTE FUNCTION bothesis_validate_ingestion_source();

CREATE FUNCTION bothesis_validate_external_resource() RETURNS trigger AS $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM items i
    JOIN ingestion_sources s ON s.id = NEW.ingestion_source_id
    JOIN integration_connections c ON c.id = s.integration_connection_id
    WHERE i.id = NEW.item_id AND i.tenant_id = c.tenant_id
  ) THEN
    RAISE EXCEPTION
      'External Resource and Ingestion Source must belong to the same tenant';
  END IF;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER trg_external_resources_validate
BEFORE INSERT OR UPDATE OF item_id, ingestion_source_id ON external_resources
FOR EACH ROW EXECUTE FUNCTION bothesis_validate_external_resource();

COMMIT;
