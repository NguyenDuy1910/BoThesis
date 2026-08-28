export interface Paginated<T> {
  items: T[];
  total: number;
  page?: number;
  page_size?: number;
}

export interface ItemOrigin {
  id: string;
  external_id: string;
  source_url: string | null;
  binding_id: string;
  connection: {
    id: string;
    display_name: string;
    plugin_key: string;
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
  origins: ItemOrigin[];
  metadata?: Record<string, unknown>;
  inherit_access?: boolean;
  collection_access?: CollectionGrant[];
}

export interface PluginConnection {
  [key: string]: unknown;
  id: string;
  plugin_key: string;
  display_name: string;
  config: Record<string, unknown>;
  credential_configured: boolean;
  owner_type: "tenant" | "user";
  status: "draft" | "active" | "disabled" | "error";
  binding_count: number;
  created_at: string;
  updated_at: string;
}

export interface PluginSchedule {
  id: string;
  schedule_type: "cron" | "interval";
  cron_expression: string;
  timezone: string | null;
  enabled: boolean;
  overlap_policy: "skip" | "queue" | "replace";
  next_run_at: string | null;
  last_run_at: string | null;
}

export interface PluginBinding {
  [key: string]: unknown;
  id: string;
  connection_id: string;
  target_item_id: string;
  display_name: string | null;
  config: Record<string, unknown>;
  checkpoint: Record<string, unknown>;
  status: "active" | "disabled" | "error";
  last_synced_at: string | null;
  last_indexed_at: string | null;
  schedule: PluginSchedule | null;
}

export interface SyncRun {
  [key: string]: unknown;
  id: string;
  binding_id: string;
  trigger_type: "manual" | "scheduled" | "webhook" | "initial";
  status: "pending" | "running" | "completed" | "failed" | "cancelled" | "skipped";
  discovered_item_count: number;
  processed_item_count: number;
  written_chunk_count: number;
  deleted_item_count: number;
  error_code: string | null;
  error_message: string | null;
  started_at: string | null;
  finished_at: string | null;
  created_at: string;
  connection: { id: string; display_name: string; plugin_key: string };
  binding: { id: string; display_name: string | null; target_item_id: string };
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
