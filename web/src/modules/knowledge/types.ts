export interface ViewerBoundingBox {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface ViewerElement {
  element_id: string;
  text: string;
  page?: number | null;
  section?: string | null;
  section_path: string[];
  anchor?: string | null;
  bounding_box?: ViewerBoundingBox | null;
}

export interface ViewerFocus {
  chunk_id: string;
  chunk_text: string;
  citation: ViewerCitation;
}

export interface ViewerCitation {
  section?: string | null;
  section_path: string[];
  anchor?: string | null;
  page_start?: number | null;
  page_end?: number | null;
  spans: ViewerCitationSpan[];
}

export interface ViewerCitationSpan {
  page?: number | null;
  element_id?: string | null;
  start_offset?: number | null;
  end_offset?: number | null;
  bounding_box?: ViewerBoundingBox | null;
}

export type ItemStatus =
  | "pending"
  | "processing"
  | "ready"
  | "failed"
  | "unsupported"
  | "deleted";

export type PreviewRepresentation = "original" | "image" | "pages";

/** One rendered page of a source, behind a short-lived authorized URL. */
export interface PreviewAsset {
  url: string;
  content_type: string;
  size_bytes: number;
  width: number;
  height: number;
  page?: number | null;
}

export interface PreviewOriginal {
  url: string;
  file_name: string;
  content_type: string;
  size_bytes: number;
}

/**
 * The presentation view of an authorized source. Asset pages and citation span
 * pages share one-based numbering, and the backend states the coordinate space
 * its bounding boxes are expressed in.
 */
export interface KnowledgePreview {
  representation: PreviewRepresentation;
  original: PreviewOriginal;
  assets: PreviewAsset[];
  page_count?: number | null;
  truncated: boolean;
  coordinate_space: "normalized_top_left";
}

export interface KnowledgeItemViewer {
  item_id: string;
  title: string;
  content_type: string;
  status: ItemStatus;
  external_url?: string | null;
  document_url?: string | null;
  preview?: KnowledgePreview | null;
  elements: ViewerElement[];
  focus?: ViewerFocus | null;
}

export interface KnowledgeCitationResponse {
  item_id: string;
  chunk_id: string;
  title: string;
  content_type: string;
  document_url?: string | null;
  external_url?: string | null;
  preview?: KnowledgePreview | null;
  citation: ViewerCitation;
}
