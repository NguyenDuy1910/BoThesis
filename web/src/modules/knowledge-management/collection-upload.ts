export const COLLECTION_UPLOAD_MAX_BYTES = 100 * 1024 * 1024;

export const COLLECTION_UPLOAD_ACCEPT = [
  ".pdf",
  ".docx",
  ".pptx",
  ".xlsx",
  ".csv",
  ".txt",
  ".md",
  ".markdown",
  ".html",
  ".htm",
  ".json",
  ".jsonl",
  ".log",
  ".rst",
  ".sql",
  ".tsv",
  ".xml",
  ".yaml",
  ".yml",
  ".avif",
  ".bmp",
  ".gif",
  ".jpeg",
  ".jpg",
  ".png",
  ".tif",
  ".tiff",
  ".webp",
] as const;

const acceptedExtensions = new Set<string>(COLLECTION_UPLOAD_ACCEPT);

export type CollectionUploadQueueStatus =
  | "queued"
  | "uploading"
  | "processing"
  | "ready"
  | "unsupported"
  | "permission_denied"
  | "unavailable"
  | "failed";

export interface CollectionUploadFailure {
  status: Extract<
    CollectionUploadQueueStatus,
    "unsupported" | "permission_denied" | "unavailable" | "failed"
  >;
  message: string;
}

export function validateCollectionUploadFile(file: {
  name: string;
  size: number;
}): CollectionUploadFailure | null {
  const extension = file.name.includes(".")
    ? `.${file.name.split(".").at(-1)?.toLowerCase()}`
    : "";
  if (!acceptedExtensions.has(extension)) {
    return {
      status: "unsupported",
      message: "This file type is not supported for indexing.",
    };
  }
  if (file.size < 1) {
    return { status: "failed", message: "This file is empty." };
  }
  if (file.size > COLLECTION_UPLOAD_MAX_BYTES) {
    return {
      status: "failed",
      message: "This file exceeds the 100 MB upload limit.",
    };
  }
  return null;
}

export function collectionUploadFailure(
  statusCode: number | undefined,
  detail: string,
): CollectionUploadFailure {
  if (statusCode === 403) {
    return {
      status: "permission_denied",
      message: "You don’t have permission to upload files to this collection.",
    };
  }
  if (statusCode === 404) {
    return {
      status: "unavailable",
      message: "Uploading directly to this knowledge base is not available in this environment.",
    };
  }
  if (statusCode === 413) {
    return {
      status: "failed",
      message: "This file exceeds the upload limit configured for this workspace.",
    };
  }
  if (statusCode === 422 && detail.toLowerCase().includes("unsupported")) {
    return {
      status: "unsupported",
      message: "This file type is not supported for indexing.",
    };
  }
  return {
    status: "failed",
    message: detail || "The file could not be uploaded. Try again.",
  };
}
