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

test("keeps only secondary tool activity out of the primary reasoning flow", () => {
  const run = AgentActivityMapper.fromParts([
    ...runningPlaceholder,
    {
      type: "data-status",
      id: "generation-0",
      data: {
        phase: "model",
        state: "completed",
        label: "Think",
        activityType: "next_step_generation",
        stepId: "generation-0",
        turn: 0,
      },
    },
    {
      type: "data-reasoning",
      id: "reasoning-model-0",
      data: {
        source: "model",
        turn: 0,
        text: "I’ll verify the policy before answering.",
        state: "done",
      },
    },
    {
      type: "data-status",
      id: "tool-search-1",
      data: {
        phase: "retrieval",
        state: "completed",
        label: "Observe · Search knowledge base",
        activityType: "knowledge_retrieval",
        stepId: "tool-search-1",
        resultCount: 2,
      },
    },
    {
      type: "data-status",
      id: "generation-1",
      data: {
        phase: "model",
        state: "completed",
        label: "Final response",
        activityType: "final_response_generation",
        stepId: "generation-1",
        turn: 1,
      },
    },
  ], false);

  assert.deepEqual(run.steps.map((step) => step.label), ["Search knowledge base"]);
  assert.equal(run.steps[0]?.description, undefined);
  assert.equal(run.reasoning[0]?.text, "I’ll verify the policy before answering.");
});
