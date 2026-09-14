import assert from "node:assert/strict";
import test from "node:test";

import {
  isRailItemActive,
  modeForPath,
  platformAdminRailItems,
  visibleRailItems,
  workspaceAdminRailItems,
  workspaceAdminRailTail,
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
    workspaceRailItems.some((item) => item.href.startsWith("/admin")),
    false,
  );
});

test("Workspace Admin owns six sections plus a separated Settings", () => {
  assert.deepEqual(
    workspaceAdminRailItems.map((item) => item.label),
    ["Overview", "Knowledge", "Agent", "Access", "Experience", "Activity"],
  );
  assert.deepEqual(workspaceAdminRailTail.map((item) => item.label), ["Settings"]);
});

test("Platform Admin is a separate control plane that speaks in tenants", () => {
  assert.deepEqual(
    platformAdminRailItems.map((item) => item.label),
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
  // row can ever light up while the workspace admin rail is mounted.
  assert.equal(
    platformAdminRailItems.every((item) => item.href.startsWith("/admin/platform")),
    true,
  );
});

test("the three modes never share a rail", () => {
  assert.equal(modeForPath("/app"), "workspace");
  assert.equal(modeForPath("/library"), "workspace");
  assert.equal(modeForPath("/admin"), "workspace-admin");
  assert.equal(modeForPath("/admin/knowledge"), "workspace-admin");
  assert.equal(modeForPath("/admin/platform"), "platform-admin");
  assert.equal(modeForPath("/admin/platform/users"), "platform-admin");
});

test("only the destination that owns the route is current", () => {
  const at = (id: string, items: readonly RailItem[], pathname: string) => {
    const item = items.find((entry) => entry.id === id);
    assert.ok(item, `${id} is missing`);
    return isRailItemActive(item, pathname);
  };

  // Exact landings must not match their own children, or two rows light up.
  assert.equal(at("overview", workspaceAdminRailItems, "/admin"), true);
  assert.equal(at("overview", workspaceAdminRailItems, "/admin/knowledge"), false);
  assert.equal(at("tenants", platformAdminRailItems, "/admin/platform"), true);
  assert.equal(at("tenants", platformAdminRailItems, "/admin/platform/users"), false);

  // Everything else owns its nested detail addresses.
  assert.equal(at("knowledge", workspaceAdminRailItems, "/admin/knowledge/doc-1"), true);
  assert.equal(at("users", platformAdminRailItems, "/admin/platform/users/u-1"), true);

  // An action starts something where you already are; it is never current.
  assert.equal(at("new-chat", workspaceRailItems, "/app"), false);
  assert.equal(at("search", workspaceRailItems, "/app"), false);
});

test("a rail only offers what the caller may actually open", () => {
  const holding = (...granted: string[]) => (codes: readonly string[]) =>
    codes.some((code) => granted.includes(code));

  assert.deepEqual(
    visibleRailItems(workspaceAdminRailItems, holding("knowledge.read")).map((item) => item.id),
    ["knowledge"],
  );
  // Someone with nothing granted can open no admin section at all.
  assert.deepEqual(visibleRailItems(workspaceAdminRailItems, holding()).map((item) => item.id), []);
  // An item with no permission codes is always offered.
  assert.deepEqual(
    visibleRailItems(workspaceRailItems, holding()).map((item) => item.id),
    ["new-chat", "search", "library"],
  );
});

test("every admin rail address is one the console can resolve", () => {
  // The Admin console resolves an address by the single path segment that
  // follows `/admin` (or `/admin/platform`). A rail item that addressed a
  // deeper path would render the not-found page, so the shape is a contract
  // between the rail and the resolver — not a style preference.
  for (const item of [...workspaceAdminRailItems, ...workspaceAdminRailTail]) {
    assert.match(item.href, /^\/admin(\/[a-z-]+)?$/, `${item.id} addresses too deep`);
  }
  for (const item of platformAdminRailItems) {
    assert.match(item.href, /^\/admin\/platform(\/[a-z-]+)?$/, `${item.id} addresses too deep`);
  }

  // Exactly one item per mode may take the landing address.
  assert.deepEqual(
    [...workspaceAdminRailItems, ...workspaceAdminRailTail].filter((item) => item.href === "/admin").map((item) => item.id),
    ["overview"],
  );
  assert.deepEqual(
    platformAdminRailItems.filter((item) => item.href === "/admin/platform").map((item) => item.id),
    ["tenants"],
  );
});

test("a platform section id can never collide with a workspace one", () => {
  // The console prefixes platform ids with `platform-`. That only stays
  // unambiguous while no workspace section is named that way.
  const workspaceIds = [...workspaceAdminRailItems, ...workspaceAdminRailTail].map((item) => item.id);
  for (const id of workspaceIds) {
    assert.ok(!id.startsWith("platform-"), `${id} would shadow a platform section`);
  }

  const allIds = [...workspaceIds, ...platformAdminRailItems.map((item) => `platform-${item.id}`)];
  assert.equal(new Set(allIds).size, allIds.length, "two sections resolve to the same id");

  const allHrefs = [
    ...workspaceAdminRailItems,
    ...workspaceAdminRailTail,
    ...platformAdminRailItems,
  ].map((item) => item.href);
  assert.equal(new Set(allHrefs).size, allHrefs.length, "two sections share an address");
});
