import assert from "node:assert/strict";
import test from "node:test";

import {
  isProductNavigationActive,
  productNavigationItems,
} from "../web/src/lib/product-navigation.ts";

test("product destinations have one stable label, route, and icon", () => {
  assert.deepEqual(
    productNavigationItems.map(({ id, label, href }) => ({ id, label, href })),
    [
      { id: "chat", label: "Chat", href: "/app" },
      { id: "knowledge", label: "Knowledge", href: "/knowledge" },
      { id: "apps", label: "Apps", href: "/admin/connectors" },
      { id: "agents", label: "Agents", href: "/workflows" },
      { id: "admin", label: "Admin", href: "/admin" },
    ],
  );
  assert.equal(new Set(productNavigationItems.map((item) => item.icon)).size, 5);
});

test("only the destination that owns the route is active", () => {
  assert.equal(isProductNavigationActive("/app", "/app"), true);
  assert.equal(isProductNavigationActive("/app/conversations/a", "/app"), false);
  assert.equal(isProductNavigationActive("/knowledge/collections/a", "/knowledge"), true);
  assert.equal(isProductNavigationActive("/admin/connectors", "/admin"), false);
  assert.equal(isProductNavigationActive("/admin", "/admin/connectors"), false);
});
