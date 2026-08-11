import assert from "node:assert/strict";
import test from "node:test";

import { StreamEventDeduplicator } from "../src/modules/chat/stream-deduplicator.ts";

test("accepts ordered events and rejects duplicate IDs or sequences", () => {
  const deduplicator = new StreamEventDeduplicator();

  assert.equal(deduplicator.shouldAccept({ event_id: "event-1", sequence: 1 }), true);
  assert.equal(deduplicator.shouldAccept({ event_id: "event-1", sequence: 2 }), false);
  assert.equal(deduplicator.shouldAccept({ event_id: "event-2", sequence: 1 }), false);
  assert.equal(deduplicator.shouldAccept({ event_id: "event-2", sequence: 2 }), true);
});
