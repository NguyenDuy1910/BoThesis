import assert from "node:assert/strict";
import test from "node:test";

import {
  isRailItemActive,
  modeForPath,
  platformControlRailItems,
  visibleRailItems,
  workspaceControlRailItems,
  workspaceControlRailTail,
  workspaceRailItems,
  type RailItem,
} from "../web/src/lib/navigation.ts";

test("the User Workspace rail stays light", () => {
  // WA 01: use AI, and nothing else. Tenant settings, roles, connectors and
  // system configuration are absent here, not disabled.
  assert.deepEqual(
    workspaceRailItems.map(({ id, label, href }) => ({ id, label, href })),
    [
      { id: "new-chat", label: "New chat", href: "/app?action=new" },
      { id: "search", label: "Search", href: "/app?action=search" },
      { id: "library", label: "Library", href: "/library" },
    ],
  );
  assert.equal(
    workspaceRailItems.some((item) => item.href.startsWith("/workspace-control")),
    false,
  );
});

test("Workspace control owns six sections plus a separated Settings", () => {
  assert.deepEqual(
    workspaceControlRailItems.map((item) => item.label),
    ["Overview", "Knowledge", "Agent", "Access", "Experience", "Activity"],
  );
  assert.deepEqual(workspaceControlRailTail.map((item) => item.label), ["Settings"]);
});

test("Platform control is a separate plane that speaks in tenants", () => {
  assert.deepEqual(
    platformControlRailItems.map((item) => item.label),
    [
      "Tenants",
      "Users",
      "Public Workspaces",
      "Models & Capabilities",
      "Integrations",
      "Usage",
      "Audit",
      "System",
    ],
  );
  // Every platform address is nested under the platform prefix, so no platform
  // row can ever light up while workspace control rail is mounted.
  assert.equal(
    platformControlRailItems.every((item) => item.href.startsWith("/workspace-control/platform")),
    true,
  );
});

test("the three modes never share a rail", () => {
  assert.equal(modeForPath("/app"), "workspace");
  assert.equal(modeForPath("/library"), "workspace");
  assert.equal(modeForPath("/workspace-control"), "workspace-control");
  assert.equal(modeForPath("/workspace-control/knowledge"), "workspace-control");
  assert.equal(modeForPath("/workspace-control/platform"), "platform-control");
  assert.equal(modeForPath("/workspace-control/platform/users"), "platform-control");
});

test("only the destination that owns the route is current", () => {
  const at = (id: string, items: readonly RailItem[], pathname: string) => {
    const item = items.find((entry) => entry.id === id);
    assert.ok(item, `${id} is missing`);
    return isRailItemActive(item, pathname);
  };

  // Exact landings must not match their own children, or two rows light up.
  assert.equal(at("overview", workspaceControlRailItems, "/workspace-control"), true);
  assert.equal(at("overview", workspaceControlRailItems, "/workspace-control/knowledge"), false);
  assert.equal(at("tenants", platformControlRailItems, "/workspace-control/platform"), true);
  assert.equal(at("tenants", platformControlRailItems, "/workspace-control/platform/users"), false);

  // Everything else owns its nested detail addresses.
  assert.equal(at("knowledge", workspaceControlRailItems, "/workspace-control/knowledge/doc-1"), true);
  assert.equal(at("users", platformControlRailItems, "/workspace-control/platform/users/u-1"), true);

  // An action starts something where you already are; it is never current.
  assert.equal(at("new-chat", workspaceRailItems, "/app"), false);
  assert.equal(at("search", workspaceRailItems, "/app"), false);
});

test("a rail only offers what the caller may actually open", () => {
  const holding = (...granted: string[]) => (codes: readonly string[]) =>
    codes.some((code) => granted.includes(code));

  assert.deepEqual(
    visibleRailItems(workspaceControlRailItems, holding("knowledge.read")).map((item) => item.id),
    ["knowledge"],
  );
  // Someone with nothing granted can open no admin section at all.
  assert.deepEqual(visibleRailItems(workspaceControlRailItems, holding()).map((item) => item.id), []);
  // An item with no permission codes is always offered.
  assert.deepEqual(
    visibleRailItems(workspaceRailItems, holding()).map((item) => item.id),
    ["new-chat", "search", "library"],
  );
});

test("every control-plane rail address is one the console can resolve", () => {
  // The control plane resolves an address by the single path segment that
  // follows `/workspace-control` (or `/workspace-control/platform`). A rail item that addressed a
  // deeper path would render the not-found page, so the shape is a contract
  // between the rail and the resolver — not a style preference.
  for (const item of [...workspaceControlRailItems, ...workspaceControlRailTail]) {
    assert.match(item.href, /^\/workspace-control(\/[a-z-]+)?$/, `${item.id} addresses too deep`);
  }
  for (const item of platformControlRailItems) {
    assert.match(item.href, /^\/workspace-control\/platform(\/[a-z-]+)?$/, `${item.id} addresses too deep`);
  }

  // Exactly one item per mode may take the landing address.
  assert.deepEqual(
    [...workspaceControlRailItems, ...workspaceControlRailTail].filter((item) => item.href === "/workspace-control").map((item) => item.id),
    ["overview"],
  );
  assert.deepEqual(
    platformControlRailItems.filter((item) => item.href === "/workspace-control/platform").map((item) => item.id),
    ["tenants"],
  );
});

test("a platform section id can never collide with a workspace one", () => {
  // The console prefixes platform ids with `platform-`. That only stays
  // unambiguous while no workspace section is named that way.
  const workspaceIds = [...workspaceControlRailItems, ...workspaceControlRailTail].map((item) => item.id);
  for (const id of workspaceIds) {
    assert.ok(!id.startsWith("platform-"), `${id} would shadow a platform section`);
  }

  const allIds = [...workspaceIds, ...platformControlRailItems.map((item) => `platform-${item.id}`)];
  assert.equal(new Set(allIds).size, allIds.length, "two sections resolve to the same id");

  const allHrefs = [
    ...workspaceControlRailItems,
    ...workspaceControlRailTail,
    ...platformControlRailItems,
  ].map((item) => item.href);
  assert.equal(new Set(allHrefs).size, allHrefs.length, "two sections share an address");
});
