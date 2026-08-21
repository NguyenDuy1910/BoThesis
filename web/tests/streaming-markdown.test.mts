import assert from "node:assert/strict";
import test from "node:test";

import {
  nextRevealLength,
  splitStreamingMarkdown,
} from "../src/modules/chat/streaming-markdown.ts";

test("keeps a fenced code block whole even when it contains a blank line", () => {
  const text = "Here is the fix:\n\n```python\na = 1\n\nb = 2\n```\nDone.";
  const { stable, tail } = splitStreamingMarkdown(text);

  assert.equal(stable, "Here is the fix:\n\n");
  assert.equal(tail, "```python\na = 1\n\nb = 2\n```\nDone.");
});

test("keeps an unterminated fence in the tail", () => {
  const { stable, tail } = splitStreamingMarkdown("Intro.\n\n```ts\nconst a = 1;\n");

  assert.equal(stable, "Intro.\n\n");
  assert.equal(tail, "```ts\nconst a = 1;\n");
});

test("keeps a loose list in one piece so it renders as one list", () => {
  const { stable, tail } = splitStreamingMarkdown("Steps:\n\n- First\n\n- Second\n\n- Third\n");

  assert.equal(stable, "Steps:\n\n");
  assert.equal(tail, "- First\n\n- Second\n\n- Third\n");
});

test("keeps a numbered list in one piece so numbering never restarts", () => {
  const { stable, tail } = splitStreamingMarkdown("Order:\n\n1. One\n\n2. Two\n\n3. Th");

  assert.equal(stable, "Order:\n\n");
  assert.equal(tail, "1. One\n\n2. Two\n\n3. Th");
});

test("keeps an indented list continuation with its item", () => {
  const text = "Checklist:\n\n- Parent\n\n    Detail for the parent.\n\n- Next\n";

  const { stable, tail } = splitStreamingMarkdown(text);

  assert.equal(stable, "Checklist:\n\n");
  assert.equal(tail, "- Parent\n\n    Detail for the parent.\n\n- Next\n");
});

test("releases a completed list once the next top-level block starts", () => {
  const { stable, tail } = splitStreamingMarkdown("Steps:\n\n- First\n\n- Second\n\nThen deploy");

  assert.equal(stable, "Steps:\n\n- First\n\n- Second\n\n");
  assert.equal(tail, "Then deploy");
});

test("keeps a display math block whole", () => {
  const text = "The rate is:\n\n$$\nr = \\frac{a}{b}\n\nc = 1\n$$\n\nDone";
  const { stable, tail } = splitStreamingMarkdown(text);

  assert.equal(stable, "The rate is:\n\n$$\nr = \\frac{a}{b}\n\nc = 1\n$$\n\n");
  assert.equal(tail, "Done");
});

test("parses text that uses reference definitions as a single document", () => {
  const text = "See the [policy][p] for detail.\n\n[p]: https://example.com/policy\n";

  assert.deepEqual(splitStreamingMarkdown(text), { stable: "", tail: text });
});

test("advances the boundary to the last finished block", () => {
  const text = "# Title\n\nFirst paragraph.\n\n## Section\n\nSecond para";
  const { stable, tail } = splitStreamingMarkdown(text);

  assert.equal(stable, "# Title\n\nFirst paragraph.\n\n## Section\n\n");
  assert.equal(tail, "Second para");
});

test("holds the first block until a later one starts", () => {
  assert.deepEqual(splitStreamingMarkdown("A partial para"), { stable: "", tail: "A partial para" });
});

test("reveals whole words and never overshoots the received text", () => {
  const text = "The quick brown fox jumps over the lazy dog and keeps running along.";

  let length = 0;
  const paints: string[] = [];
  while (length < text.length) {
    length = nextRevealLength(text, length);
    paints.push(text.slice(0, length));
  }

  assert.ok(paints.length > 1, "a burst is revealed over several commits");
  assert.equal(paints.at(-1), text);
  for (const paint of paints.slice(0, -1)) {
    assert.match(paint, /(^$|[ \n\t]$)/, `"${paint}" ends mid-word`);
  }
});

test("drains a large backlog within a few hundred milliseconds", () => {
  const text = "word ".repeat(2000); // 10k characters arriving at once

  let length = 0;
  let commits = 0;
  while (length < text.length) {
    length = nextRevealLength(text, length);
    commits += 1;
  }

  // 32ms per commit, so the worst case is ~1.6s for text no model streams that
  // fast: the reveal paces paints, it does not hold text back.
  assert.ok(commits <= 50, `took ${commits} commits`);
});

test("reveals a slow trickle without waiting for more text", () => {
  assert.equal(nextRevealLength("Hi", 0), 2);
  assert.equal(nextRevealLength("Hi there", 2), 8);
});
