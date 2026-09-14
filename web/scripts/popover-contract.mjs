/**
 * Verifies the account popover's interaction contract:
 * toggle, outside click, Escape, focus return, keyboard traversal, anchoring,
 * long labels, many workspaces, and the collapsed rail.
 *
 *   BASE_URL=http://localhost:3100 node scripts/popover-contract.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";

const makeSession = (workspaceCount) => ({
  access_token: "t",
  token_type: "bearer",
  expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  user_id: "u",
  email: "duy.nguyen@enterprise.ai",
  display_name: "Duy Nguyen",
  active_tenant_id: "t1",
  permissions: ["admin"],
  tenants: Array.from({ length: workspaceCount }, (_, i) => ({
    id: `t${i + 1}`,
    code: `w${i + 1}`,
    name:
      i === 0
        ? "Vikki Bank"
        : i === 1
          ? "A deliberately long workspace name that must truncate"
          : `Workspace ${i + 1}`,
    role_id: "r",
    role_code: i === 0 ? "owner" : "member",
    permissions: i === 0 ? ["admin"] : [],
  })),
  platform_scopes: ["root_admin"],
});

let failures = 0;
const check = (ok, message) => {
  console.log(`  ${ok ? "pass" : "FAIL"}  ${message}`);
  if (!ok) failures += 1;
};

const TRIGGER = "button[aria-label='Account and workspace']";
const browser = await chromium.launch();

async function openPage(workspaceCount, viewport = { width: 1440, height: 900 }) {
  const context = await browser.newContext({ viewport });
  await context.addInitScript((s) => {
    sessionStorage.setItem("bothesis.auth.session", s);
    localStorage.setItem("bothesis-theme", "light");
  }, JSON.stringify(makeSession(workspaceCount)));
  await context.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ items: [], total: 0, recent_documents: [], personal_collection_id: null }) }),
  );
  const page = await context.newPage();
  await page.goto(`${BASE}/app`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  return { context, page };
}

const isOpen = (page) => page.locator("[role='menu']").count().then((n) => n > 0);

// ── interaction ───────────────────────────────────────────────────────────
console.log("\ninteraction");
{
  const { context, page } = await openPage(3);

  await page.click(TRIGGER);
  await page.waitForTimeout(300);
  check(await isOpen(page), "click trigger opens");

  await page.click(TRIGGER);
  await page.waitForTimeout(300);
  check(!(await isOpen(page)), "click trigger again closes");

  await page.click(TRIGGER);
  await page.waitForTimeout(300);
  await page.mouse.click(900, 300);
  await page.waitForTimeout(300);
  check(!(await isOpen(page)), "click outside closes");

  await page.click(TRIGGER);
  await page.waitForTimeout(300);
  await page.keyboard.press("Escape");
  await page.waitForTimeout(300);
  check(!(await isOpen(page)), "Escape closes");
  check(
    await page.evaluate((sel) => document.activeElement === document.querySelector(sel), TRIGGER),
    "focus returns to the trigger after Escape",
  );

  await page.click(TRIGGER);
  await page.waitForTimeout(350);
  check(
    await page.evaluate(() => document.activeElement?.getAttribute("role") === "menuitem"),
    "focus moves into the menu on open",
  );
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("ArrowDown");
  const focusedText = await page.evaluate(() =>
    document.activeElement?.textContent?.trim().replace(/\s+/g, " ").slice(0, 30),
  );
  check(Boolean(focusedText), `ArrowDown traverses items (on "${focusedText}")`);

  const expanded = await page.getAttribute(TRIGGER, "aria-expanded");
  check(expanded === "true", "trigger reports aria-expanded while open");
  await context.close();
}

// ── anchoring and containment ─────────────────────────────────────────────
console.log("\nanchoring");
{
  const { context, page } = await openPage(12);
  await page.click(TRIGGER);
  await page.waitForTimeout(350);
  const geo = await page.evaluate((sel) => {
    const m = document.querySelector("[role='menu']").getBoundingClientRect();
    const t = document.querySelector(sel).getBoundingClientRect();
    const list = document.querySelector("[role='menu'] .overflow-y-auto");
    return {
      width: Math.round(m.width),
      height: Math.round(m.height),
      gap: Math.round(t.top - m.bottom),
      leftDelta: Math.round(m.left - t.left),
      above: m.bottom <= t.top,
      inViewport: m.top >= 0 && m.bottom <= window.innerHeight,
      listScrolls: list ? list.scrollHeight > list.clientHeight + 1 : false,
    };
  }, TRIGGER);
  check(geo.above, "opens upward from the footer");
  check(geo.gap >= 4 && geo.gap <= 12, `sits ${geo.gap}px from the trigger`);
  check(geo.leftDelta === 0, "left edge aligns with the trigger");
  check(geo.width >= 280 && geo.width <= 320, `width ${geo.width}px is within 280–320`);
  check(geo.inViewport, "stays inside the viewport with 12 workspaces");
  check(geo.height <= 600, `height ${geo.height}px stays under 600`);
  check(geo.listScrolls, "workspace list scrolls internally rather than growing");

  const truncates = await page.evaluate(() => {
    // The leaf span that carries the name, not the grid wrapper around it.
    const el = [...document.querySelectorAll("[role='menuitem'] span")].find(
      (s) => s.textContent.includes("deliberately long") && s.children.length === 0,
    );
    return el ? el.scrollWidth > el.clientWidth && getComputedStyle(el).textOverflow === "ellipsis" : false;
  });
  check(truncates, "a long workspace name truncates rather than widening the panel");
  await context.close();
}

// ── collapsed rail and small viewport ─────────────────────────────────────
console.log("\ncollapsed and small viewport");
{
  const { context, page } = await openPage(3);
  await page.click("button[aria-label='Collapse navigation']");
  await page.waitForTimeout(400);
  const railWidth = await page.evaluate(() =>
    Math.round(document.querySelector("nav.shell-nav").getBoundingClientRect().width),
  );
  check(railWidth < 100, `rail collapses to ${railWidth}px`);
  await page.click(TRIGGER);
  await page.waitForTimeout(350);
  check(await isOpen(page), "account popover still opens when collapsed");
  await context.close();
}
{
  const { context, page } = await openPage(3, { width: 760, height: 720 });
  const overlayed = await page.evaluate(() => {
    const nav = document.querySelector("nav.shell-nav");
    return getComputedStyle(nav).position === "fixed";
  });
  check(overlayed, "rail becomes an overlay below the nav breakpoint");
  await context.close();
}

console.log(`\n=== ${failures === 0 ? "popover contract holds" : `${failures} violation(s)`} ===`);
await browser.close();
process.exit(failures === 0 ? 0 : 1);
