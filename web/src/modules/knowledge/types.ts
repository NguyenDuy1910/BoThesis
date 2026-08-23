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
  spans: ViewerCitationSpan[];
}

export interface ViewerCitationSpan {
  page?: number | null;
  element_id?: string | null;
  start_offset?: number | null;
  end_offset?: number | null;
  bounding_box?: ViewerBoundingBox | null;
}

export interface KnowledgeItemViewer {
  item_id: string;
  title: string;
  content_type: string;
  external_url?: string | null;
  document_url?: string | null;
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
  citation: ViewerCitation;
}
