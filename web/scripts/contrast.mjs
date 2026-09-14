/**
 * WCAG AA contrast audit.
 *
 * Walks every visible text node on a page, resolves the colour it is painted
 * in against the first opaque background behind it, and reports anything under
 * the AA threshold for its size. Run per theme.
 *
 *   node contrast.mjs [--theme=light|dark] <path ...>
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";

const args = process.argv.slice(2);
const flags = Object.fromEntries(
  args.filter((a) => a.startsWith("--")).map((a) => a.slice(2).split("=")),
);
const paths = args.filter((a) => !a.startsWith("--"));
const theme = flags.theme ?? "light";

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

const workspaces = {
  total: 126,
  items: [
    { id: "w1", name: "Galaxy FinX", code: "galaxy-finx", status: "active", created_at: "2025-03-04T09:12:00Z", member_count: 248, connection_count: 6, owner: { display_name: "Duy Nguyen" } },
    { id: "w3", name: "Operations Lab", code: "ops-lab", status: "pending", created_at: "2025-06-30T15:45:00Z", member_count: 36, connection_count: 3, owner: { display_name: "Minh Pham" } },
    { id: "w4", name: "External Pilot", code: "external-pilot", status: "inactive", created_at: "2025-07-14T08:20:00Z", member_count: 12, connection_count: 2, owner: { display_name: "Lan Nguyen" } },
    { id: "w6", name: "Legacy Workspace", code: "legacy", status: "archived", created_at: "2024-11-19T13:30:00Z", member_count: 9, connection_count: 1, owner: { display_name: "System Admin" } },
  ],
};
const users = {
  total: 24,
  items: [
    { id: "u1", display_name: "Duy Nguyen", email: "duy@enterprise.ai", status: true, created_at: "2025-01-10T09:00:00Z", membership: { role: { code: "owner", display_name: "Owner" } } },
    { id: "u5", display_name: "Vendor Support", email: "vendor@partner.io", status: false, created_at: "2025-05-30T09:00:00Z", membership: { role: { code: "guest", display_name: "Guest" } } },
  ],
};
const overview = {
  tenant: { id: "t1", code: "vikki", name: "Vikki Bank", status: "active", updated_at: "2026-09-01T00:00:00Z" },
  metrics: { active_users: 24, active_roles: 4, active_groups: 3, active_integration_connections: 6, items: 38 },
  attention: { pending_access_requests: 2 },
  recent_activity: [],
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1560, height: 960 } });
await context.addInitScript(
  ([s, t]) => {
    sessionStorage.setItem("bothesis.auth.session", s);
    localStorage.setItem("bothesis-theme", t);
  },
  [JSON.stringify(session), theme],
);
await context.route("**/api/v1/admin/**", async (route) => {
  const url = route.request().url();
  const body = url.includes("/platform/workspaces")
    ? workspaces
    : url.includes("/overview")
      ? overview
      : url.includes("/users")
        ? users
        : { items: [], total: 0 };
  await route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify(body) });
});

const page = await context.newPage();
let failures = 0;
let checked = 0;

for (const path of paths) {
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);

  const result = await page.evaluate(() => {
    const parse = (c) => {
      const m = c.match(/[\d.]+/g)?.map(Number) ?? [];
      return { r: m[0] ?? 0, g: m[1] ?? 0, b: m[2] ?? 0, a: m[3] ?? 1 };
    };
    const lin = (v) => {
      const s = v / 255;
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4;
    };
    const lum = ({ r, g, b }) => 0.2126 * lin(r) + 0.7152 * lin(g) + 0.0722 * lin(b);
    const over = (fg, bg) => ({
      r: fg.r * fg.a + bg.r * (1 - fg.a),
      g: fg.g * fg.a + bg.g * (1 - fg.a),
      b: fg.b * fg.a + bg.b * (1 - fg.a),
      a: 1,
    });

    function backdrop(el) {
      let acc = null;
      let node = el;
      while (node && node !== document.documentElement) {
        const bg = parse(getComputedStyle(node).backgroundColor);
        if (bg.a > 0) acc = acc ? over(acc, bg) : bg;
        if (acc && acc.a >= 0.999) return acc;
        node = node.parentElement;
      }
      const root = parse(getComputedStyle(document.body).backgroundColor);
      return acc ? over(acc, root.a > 0 ? root : { r: 255, g: 255, b: 255, a: 1 })
                 : root.a > 0 ? root : { r: 255, g: 255, b: 255, a: 1 };
    }

    const out = [];
    const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
    const seen = new Set();
    while (walker.nextNode()) {
      const text = walker.currentNode.textContent?.trim();
      if (!text || text.length < 2) continue;
      const el = walker.currentNode.parentElement;
      if (!el || seen.has(el)) continue;
      seen.add(el);
      const cs = getComputedStyle(el);
      if (cs.visibility === "hidden" || cs.display === "none" || Number(cs.opacity) < 0.3) continue;
      const rect = el.getBoundingClientRect();
      if (rect.width < 2 || rect.height < 2) continue;

      const size = parseFloat(cs.fontSize);
      const weight = Number(cs.fontWeight) || 400;
      const large = size >= 24 || (size >= 18.66 && weight >= 700);
      const fg = parse(cs.color);
      const bg = backdrop(el);
      const solid = fg.a < 1 ? over(fg, bg) : fg;
      const l1 = lum(solid);
      const l2 = lum(bg);
      const ratio = (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
      const threshold = large ? 3 : 4.5;
      out.push({
        text: text.slice(0, 42),
        ratio: Math.round(ratio * 100) / 100,
        threshold,
        color: cs.color,
        size,
        pass: ratio >= threshold,
      });
    }
    return out;
  });

  checked += result.length;
  const bad = result.filter((r) => !r.pass);
  failures += bad.length;
  console.log(`\n${path}  —  ${result.length} text elements, ${bad.length} below AA`);
  for (const b of bad.slice(0, 14)) {
    console.log(`  ${String(b.ratio).padStart(5)}:1 (needs ${b.threshold})  ${b.size}px  ${b.color}  "${b.text}"`);
  }
}

console.log(`\n=== ${theme}: ${checked} checked, ${failures} below AA ===`);
await browser.close();
