import assert from "node:assert/strict";
import test from "node:test";

import {
  isProductNavigationActive,
  productNavigationActions,
  productNavigationItems,
} from "../web/src/lib/product-navigation.ts";

test("product navigation has stable global actions and destinations", () => {
  assert.deepEqual(
    productNavigationActions.map(({ id, label, href }) => ({ id, label, href })),
    [
      { id: "new-chat", label: "New chat", href: "/app?action=new" },
      { id: "search-chats", label: "Search chats", href: "/app?action=search" },
    ],
  );
  assert.deepEqual(
    productNavigationItems.map(({ id, label, href }) => ({ id, label, href })),
    [
      { id: "knowledge", label: "Knowledge", href: "/knowledge" },
      { id: "library", label: "Library", href: "/knowledge?view=library" },
      { id: "apps", label: "Apps", href: "/apps" },
      { id: "agents", label: "Agents", href: "/workflows" },
      { id: "workspace", label: "Workspace", href: "/admin" },
    ],
  );
  assert.equal(new Set(productNavigationItems.map((item) => item.icon)).size, 5);
});

test("only the destination that owns the route is active", () => {
  assert.equal(isProductNavigationActive("/app", "/app"), true);
  assert.equal(isProductNavigationActive("/app/conversations/a", "/app"), false);
  assert.equal(isProductNavigationActive("/knowledge/collections/a", "/knowledge"), true);
  assert.equal(isProductNavigationActive("/knowledge", "/knowledge?view=library", "view=library"), true);
  assert.equal(isProductNavigationActive("/knowledge", "/knowledge", "view=library"), false);
  assert.equal(isProductNavigationActive("/apps", "/apps"), true);
  assert.equal(isProductNavigationActive("/apps", "/admin"), false);
  assert.equal(isProductNavigationActive("/admin", "/apps"), false);
});
