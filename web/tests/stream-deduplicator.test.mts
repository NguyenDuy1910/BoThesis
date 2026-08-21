import assert from "node:assert/strict";
import test from "node:test";

import { StreamEventDeduplicator } from "../src/modules/chat/stream-deduplicator.ts";

test("accepts ordered events and rejects duplicate sequence numbers", () => {
  const deduplicator = new StreamEventDeduplicator();

  assert.equal(deduplicator.shouldAccept({ sequence_number: 1 }), true);
  assert.equal(deduplicator.shouldAccept({ sequence_number: 1 }), false);
  assert.equal(deduplicator.shouldAccept({ sequence_number: 0 }), false);
  assert.equal(deduplicator.shouldAccept({ sequence_number: 2 }), true);
});
