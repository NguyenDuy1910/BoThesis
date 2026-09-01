export interface Paginated<T> {
  items: T[];
  total: number;
  page?: number;
  page_size?: number;
}

export interface ExternalResource {
  id: string;
  external_id: string;
  source_url: string | null;
  ingestion_source_id: string;
  integration_connection: {
    id: string;
    display_name: string;
    connector_key: string;
  };
}

export interface KnowledgeItem {
  [key: string]: unknown;
  id: string;
  item_type: "collection" | "document";
  document_type: string | null;
  title: string;
  mime_type: string | null;
  size_bytes: number | null;
  parent_item_id: string | null;
  parent_relation: string | null;
  status: "pending" | "processing" | "ready" | "failed" | "unsupported";
  indexed: boolean;
  item_count?: number;
  source_count?: number;
  created_by_user_id: string | null;
  created_at: string;
  updated_at: string;
  external_resources: ExternalResource[];
  metadata?: Record<string, unknown>;
  inherit_access?: boolean;
  collection_access?: CollectionGrant[];
}

export interface IntegrationConnection {
  [key: string]: unknown;
  id: string;
  connector_key: string;
  display_name: string;
  config: Record<string, unknown>;
  credential_configured: boolean;
  owner_type: "tenant" | "user";
  status: "draft" | "active" | "disabled" | "error";
  source_count: number;
  created_at: string;
  updated_at: string;
}

export interface IngestionSchedule {
  id: string;
  schedule_type: "cron" | "interval";
  cron_expression: string;
  timezone: string | null;
  enabled: boolean;
  overlap_policy: "skip" | "queue" | "replace";
  next_run_at: string | null;
  last_run_at?: string | null;
}

export interface IngestionSource {
  [key: string]: unknown;
  id: string;
  integration_connection_id: string;
  target_item_id: string;
  display_name: string | null;
  config: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  status: "active" | "disabled" | "error";
  last_ingested_at: string | null;
  last_indexed_at: string | null;
  integration_connection: {
    id: string;
    display_name: string;
    connector_key: string;
  };
  schedule: IngestionSchedule | null;
}

export interface IngestionRun {
  [key: string]: unknown;
  id: string;
  workflow_id: string;
  run_id: string;
  source_id: string;
  integration_connection_id: string;
  connector_key: string;
  trigger_type: "manual" | "scheduled" | "webhook" | "initial" | null;
  status: "running" | "completed" | "failed" | "cancelled" | "terminated" | "timed_out" | "unknown";
  started_at: string;
  finished_at: string | null;
  history_length: number;
}

export interface CollectionGrant {
  [key: string]: unknown;
  item_id: string;
  principal_type: "user" | "group";
  principal_id: string;
  role: "owner" | "editor" | "viewer";
  created_at: string;
  updated_at: string;
}

export interface DirectoryUser {
  [key: string]: unknown;
  id: string;
  email: string;
  display_name: string | null;
  status: string;
}

export interface DirectoryGroup {
  [key: string]: unknown;
  id: string;
  display_name: string;
  status: string;
  member_count: number;
}

export interface CollectionUploadResponse {
  document: {
    id: string;
    parent_item_id: string | null;
    file_name: string;
    content_type: string;
    size_bytes: number;
    status: "pending" | "processing" | "ready" | "failed" | "unsupported";
    indexed: boolean;
    upload_status: "pending" | "available" | "failed" | null;
    created_at: string;
    uploaded_at: string | null;
  };
  ingestion_status: "ready" | "failed";
  created: boolean;
}
