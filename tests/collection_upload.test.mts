import assert from "node:assert/strict";
import test from "node:test";

import {
  COLLECTION_UPLOAD_MAX_BYTES,
  collectionUploadFailure,
  validateCollectionUploadFile,
} from "../web/src/modules/knowledge-management/collection-upload.ts";

test("accepts supported collection files within the client-side limit", () => {
  assert.equal(
    validateCollectionUploadFile({ name: "policy.PDF", size: 1024 }),
    null,
  );
  assert.equal(
    validateCollectionUploadFile({ name: "controls.xlsx", size: COLLECTION_UPLOAD_MAX_BYTES }),
    null,
  );
});

test("maps unsupported and oversized files to precise queue failures", () => {
  assert.deepEqual(
    validateCollectionUploadFile({ name: "archive.exe", size: 1024 }),
    {
      status: "unsupported",
      message: "This file type is not supported for indexing.",
    },
  );
  assert.deepEqual(
    validateCollectionUploadFile({ name: "large.pdf", size: COLLECTION_UPLOAD_MAX_BYTES + 1 }),
    {
      status: "failed",
      message: "This file exceeds the 100 MB upload limit.",
    },
  );
});

test("maps API permission and capability failures to actionable upload states", () => {
  assert.deepEqual(collectionUploadFailure(403, "editor access is required"), {
    status: "permission_denied",
    message: "You don’t have permission to upload files to this collection.",
  });
  assert.deepEqual(collectionUploadFailure(404, "not found"), {
    status: "unavailable",
    message: "Uploading directly to this knowledge base is not available in this environment.",
  });
  assert.deepEqual(collectionUploadFailure(422, "unsupported file type: .exe"), {
    status: "unsupported",
    message: "This file type is not supported for indexing.",
  });
  assert.deepEqual(collectionUploadFailure(503, "document storage is temporarily unavailable"), {
    status: "failed",
    message: "document storage is temporarily unavailable",
  });
});
