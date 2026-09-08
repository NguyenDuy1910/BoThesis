import assert from "node:assert/strict";
import test from "node:test";

import { artifactPreviewActivity, isSameActivity } from "../src/modules/chat/activity.ts";
import { artifactSizeLabel, turnArtifacts } from "../src/modules/chat/artifacts.ts";
import { ARTIFACT_ANNOTATION_TYPE, DOCUMENT_CITATION_TYPE } from "../src/modules/chat/types.ts";
import type { OutputTextAnnotation, TurnState } from "../src/modules/chat/types.ts";

function artifact(overrides: Partial<Record<string, unknown>> = {}): OutputTextAnnotation {
  return {
    type: ARTIFACT_ANNOTATION_TYPE,
    start_index: 18,
    end_index: 18,
    artifact: {
      id: "artifact-1",
      title: "Q3 memo",
      file_name: "Q3-memo.md",
      mime_type: "text/markdown",
      revision: 1,
      size_bytes: 2048,
      updated_at: "2026-09-06T00:00:00+00:00",
      ...overrides,
    },
  };
}

function turnWithAnnotations(perResponse: OutputTextAnnotation[][]): TurnState {
  const responses: TurnState["responses"] = {};
  const responseOrder: string[] = [];
  perResponse.forEach((annotations, index) => {
    const id = `response-${index}`;
    responseOrder.push(id);
    responses[id] = {
      id,
      status: "completed",
      itemOrder: ["message"],
      items: {
        message: {
          type: "message",
          id: "message",
          role: "assistant",
          status: "completed",
          content: [{ type: "output_text", text: "The memo is ready.", annotations }],
        },
      },
    };
  });
  return { id: "turn", status: "completed", responses, responseOrder };
}

test("collects a produced file once, from its annotation", () => {
  const artifacts = turnArtifacts(turnWithAnnotations([[artifact()]]));

  assert.equal(artifacts.length, 1);
  assert.deepEqual(artifacts[0], {
    id: "artifact-1",
    title: "Q3 memo",
    fileName: "Q3-memo.md",
    mimeType: "text/markdown",
    revision: 1,
    sizeBytes: 2048,
    updatedAt: "2026-09-06T00:00:00+00:00",
  });
});

test("a file presented twice keeps its newest revision and first position", () => {
  const artifacts = turnArtifacts(turnWithAnnotations([
    [artifact({ revision: 1 }), artifact({ id: "artifact-2", title: "Checklist" })],
    [artifact({ revision: 2, size_bytes: 4096 })],
  ]));

  assert.deepEqual(artifacts.map((entry) => [entry.id, entry.revision]), [
    ["artifact-1", 2],
    ["artifact-2", 1],
  ]);
  assert.equal(artifacts[0]?.sizeBytes, 4096);
});

test("a container file citation never reaches the client as one", () => {
  // The backend consumes the provider's own citation and republishes it as a
  // BoThesis file, so an unknown provider annotation contributes nothing.
  const provider: OutputTextAnnotation = {
    type: "container_file_citation",
    container_id: "cntr_1",
    file_id: "cfile_1",
    filename: "/mnt/data/Q3-memo.md",
  };

  assert.deepEqual(turnArtifacts(turnWithAnnotations([[provider]])), []);
});

test("citation and unknown annotations are ignored", () => {
  const citation: OutputTextAnnotation = {
    type: DOCUMENT_CITATION_TYPE,
    citation: { id: "e1", item_id: "item-1", chunk_id: "chunk-1" },
  };
  assert.deepEqual(turnArtifacts(turnWithAnnotations([[citation, { type: "file_path", path: "/x" }]])), []);
  assert.deepEqual(turnArtifacts(undefined), []);
});

test("sizes read naturally", () => {
  assert.equal(artifactSizeLabel(512), "512 B");
  assert.equal(artifactSizeLabel(2048), "2.0 KB");
  assert.equal(artifactSizeLabel(3 * 1024 * 1024), "3.0 MB");
});

test("the preview activity is keyed by document and revision", () => {
  const [first] = turnArtifacts(turnWithAnnotations([[artifact({ revision: 2 })]]));
  const activity = artifactPreviewActivity(first!);

  assert.deepEqual(activity, { type: "artifact", artifactId: "artifact-1", title: "Q3 memo", revision: 2 });
  assert.equal(isSameActivity(activity, artifactPreviewActivity(first!)), true);
  assert.equal(isSameActivity(activity, { ...activity, revision: 3 }), false);
  assert.equal(
    isSameActivity(activity, { type: "knowledge_document", citationId: "c", itemId: "i", chunkId: "k", title: "t" }),
    false,
  );
});
