import assert from "node:assert/strict";
import test from "node:test";

import { AgentActivityMapper } from "../src/modules/chat/activity-mapper.ts";
import type { ChatMessagePart } from "../src/modules/chat/types.ts";

const runningPlaceholder: ChatMessagePart[] = [
  {
    type: "data-run",
    id: "run",
    data: { status: "running", startedAt: 1 },
  },
];

test("shows the assistant placeholder before the first streamed output", () => {
  const run = AgentActivityMapper.fromParts(runningPlaceholder, true);

  assert.equal(run.status, "running");
  assert.equal(run.hasActivity, true);
  assert.deepEqual(run.steps, []);
});

test("hides placeholder-only activity when a direct answer starts", () => {
  const run = AgentActivityMapper.fromParts([
    ...runningPlaceholder,
    { type: "text", text: "Hello", state: "streaming" },
  ], true);

  assert.equal(run.hasActivity, false);
});
