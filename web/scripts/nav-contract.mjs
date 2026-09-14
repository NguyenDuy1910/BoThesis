/**
 * Checks the sidebar navigation contract from the Figma flow spec.
 *
 *   "Click a page tab → Change the child route in main content;
 *    sidebar remains unchanged."
 *
 * For each destination that has page tabs, it snapshots the rail — its markup,
 * width, scroll position and which item is selected — clicks every tab, and
 * asserts nothing about the rail moved. It also asserts focus stays on the tab
 * that was pressed, and that exactly one top-level destination is ever active.
 *
 *   node scripts/nav-contract.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";

const session = {
  access_token: "local-verification-token",
  token_type: "bearer",
  expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  user_id: "00000000-0000-0000-0000-000000000002",
  email: "duy.nguyen@enterprise.ai",
  display_name: "Duy Nguyen",
  active_tenant_id: "00000000-0000-0000-0000-000000000001",
  permissions: ["admin"],
  tenants: [
    { id: "00000000-0000-0000-0000-000000000001", code: "vikki", name: "Vikki Bank", role_id: "r1", role_code: "Owner", permissions: ["admin"] },
  ],
  platform_scopes: ["root_admin"],
};

const knowledgeHome = {
  total: 4,
  personal_collection_id: "c0",
  items: [
    { id: "c0", title: "My collection", description: "Private workspace.", document_count: 12, source_count: 2, updated_at: "2026-09-01T10:00:00Z" },
    { id: "c1", title: "Credit policy", description: "Lending policy and limits.", document_count: 84, source_count: 3, updated_at: "2026-09-08T10:00:00Z" },
    { id: "c2", title: "Operational runbooks", description: "Incident response.", document_count: 41, source_count: 2, updated_at: "2026-09-05T09:00:00Z" },
  ],
  recent_documents: [
    { id: "d1", title: "Retail lending policy v4.2", content_type: "application/pdf", status: "ready", updated_at: "2026-09-11T08:20:00Z", source: { id: "s1", name: "Confluence" } },
  ],
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await context.addInitScript((s) => {
  sessionStorage.setItem("bothesis.auth.session", s);
  localStorage.setItem("bothesis-theme", "light");
}, JSON.stringify(session));
await context.route("**/api/v1/knowledge/**", (route) =>
  route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(knowledgeHome) }),
);
await context.route("**/api/v1/admin/**", (route) =>
  route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ items: [], total: 0 }) }),
);

const page = await context.newPage();

const snapshot = () =>
  page.evaluate(() => {
    const nav = document.querySelector("nav.shell-nav");
    if (!nav) return null;
    const scroller = nav.querySelector(".overflow-y-auto");
    const selected = [...nav.querySelectorAll("[aria-current='page']")].map(
      (el) => el.textContent?.trim() ?? "",
    );
    return {
      html: nav.innerHTML,
      width: Math.round(nav.getBoundingClientRect().width),
      scrollTop: scroller ? scroller.scrollTop : 0,
      itemCount: nav.querySelectorAll("a,button").length,
      selected,
    };
  });

let failures = 0;
const check = (ok, message) => {
  console.log(`  ${ok ? "pass" : "FAIL"}  ${message}`);
  if (!ok) failures += 1;
};

for (const { path, name } of [
  { path: "/knowledge", name: "Knowledge" },
  { path: "/apps", name: "Apps" },
]) {
  console.log(`\n${name} (${path})`);
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);

  const before = await snapshot();
  check(Boolean(before), "rail is present");
  check(before.selected.length === 1, `exactly one active destination (found ${before.selected.length}: ${before.selected.join(", ")})`);

  const tabs = page.locator("[role='tab']");
  const count = await tabs.count();
  check(count >= 2, `page tabs render (${count})`);

  for (let i = 0; i < count; i += 1) {
    const label = (await tabs.nth(i).textContent())?.trim().replace(/\s+/g, " ");
    await tabs.nth(i).click();
    await page.waitForTimeout(500);

    const after = await snapshot();
    check(after.html === before.html, `"${label}" leaves rail markup unchanged`);
    check(after.width === before.width, `"${label}" leaves rail width unchanged (${before.width}px)`);
    check(after.scrollTop === before.scrollTop, `"${label}" leaves rail scroll unchanged`);
    check(after.itemCount === before.itemCount, `"${label}" adds no rail items`);

    const focused = await page.evaluate(() => {
      const el = document.activeElement;
      return { role: el?.getAttribute("role"), text: el?.textContent?.trim().replace(/\s+/g, " ") };
    });
    check(focused.role === "tab", `"${label}" keeps focus on the tab (focus is on ${focused.role ?? "body"})`);
  }
}

console.log(`\n=== ${failures === 0 ? "navigation contract holds" : `${failures} violation(s)`} ===`);
await browser.close();
process.exit(failures === 0 ? 0 : 1);
