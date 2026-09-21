/**
 * UI verification driver.
 *
 * Seeds a browser session so the shells render with a real identity, then
 * captures each address at the requested widths and themes. The backend
 * rejects the synthetic token, so data panels render their error and empty
 * states — which is deliberate: those states are part of what is being
 * reviewed.
 *
 *   node shoot.mjs <outDir> [--width=1440] [--theme=light|dark] [path ...]
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";

const args = process.argv.slice(2);
const outDir = args.shift();
const flags = Object.fromEntries(
  args.filter((a) => a.startsWith("--")).map((a) => a.slice(2).split("=")),
);
// "path::selector" clicks that selector before capturing, so states that only
// exist after an interaction — an open inspector, an expanded menu — can be
// reviewed too.
const paths = args.filter((a) => !a.startsWith("--"));
const width = Number(flags.width ?? 1440);
const height = Number(flags.height ?? 960);
const theme = flags.theme ?? "light";

const session = {
  access_token: "local-verification-token",
  token_type: "bearer",
  expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  user_id: "00000000-0000-0000-0000-000000000002",
  email: "duy.nguyen@enterprise.ai",
  display_name: "Duy Nguyen",
  active_workspace_id: "00000000-0000-0000-0000-000000000001",
  permissions: ["tenant.read", "tenant.manage", "knowledge.read", "user.manage", "role.manage", "group.manage", "audit.read"],
  workspaces: [
    {
      id: "00000000-0000-0000-0000-000000000001",
      code: "vikki",
      name: "Vikki Bank",
      role_codes: ["owner"],
      permissions: ["tenant.read", "tenant.manage"],
    },
    {
      id: "00000000-0000-0000-0000-000000000009",
      code: "ai-team",
      name: "AI Team",
      role_codes: ["admin"],
      permissions: ["tenant.read", "tenant.manage"],
    },
    {
      id: "00000000-0000-0000-0000-00000000000a",
      code: "thesis",
      name: "Thesis Project",
      role_codes: ["member"],
      permissions: [],
    },
  ],
  platform_permissions: ["platform.tenant.read", "platform.user.read", "platform.audit.read", "platform.health.read"],
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width, height } });
await context.addInitScript(
  ([s, t]) => {
    sessionStorage.setItem("bothesis.auth.session", s);
    localStorage.setItem("bothesis-theme", t);
  },
  [JSON.stringify(session), theme],
);

// Fixtures. The backend rejects the synthetic token, and these screens are
// being reviewed for how they present records — so the records are supplied
// here rather than by weakening anything in the product.
const workspaces = {
  total: 126,
  items: [
    { id: "w1", name: "Galaxy FinX", code: "galaxy-finx", status: "active", created_at: "2025-03-04T09:12:00Z", member_count: 248, connection_count: 6, owner: { display_name: "Duy Nguyen" } },
    { id: "w2", name: "Vikki Research", code: "vikki-research", status: "active", created_at: "2025-05-21T11:02:00Z", member_count: 84, connection_count: 4, owner: { display_name: "Alicia Tran" } },
    { id: "w3", name: "Operations Lab", code: "ops-lab", status: "pending", created_at: "2025-06-30T15:45:00Z", member_count: 36, connection_count: 3, owner: { display_name: "Minh Pham" } },
    { id: "w4", name: "External Pilot", code: "external-pilot", status: "inactive", created_at: "2025-07-14T08:20:00Z", member_count: 12, connection_count: 2, owner: { display_name: "Lan Nguyen" } },
    { id: "w5", name: "Sandbox Team", code: "sandbox", status: "active", created_at: "2025-08-02T10:00:00Z", member_count: 47, connection_count: 5, owner: { display_name: "Alex Ho" } },
    { id: "w6", name: "Legacy Workspace", code: "legacy", status: "archived", created_at: "2024-11-19T13:30:00Z", member_count: 9, connection_count: 1, owner: { display_name: "System Admin" } },
  ],
};
const users = {
  total: 24,
  items: [
    { id: "u1", display_name: "Duy Nguyen", email: "duy@enterprise.ai", status: true, created_at: "2025-01-10T09:00:00Z", membership: { role: { code: "owner", display_name: "Owner" } } },
    { id: "u2", display_name: "Alicia Tran", email: "alicia@enterprise.ai", status: true, created_at: "2025-02-02T09:00:00Z", membership: { role: { code: "admin", display_name: "Admin" } } },
    { id: "u3", display_name: "Minh Pham", email: "minh@enterprise.ai", status: true, created_at: "2025-02-18T09:00:00Z", membership: { role: { code: "member", display_name: "Member" } } },
    { id: "u4", display_name: "Lan Nguyen", email: "lan@enterprise.ai", status: true, created_at: "2025-04-06T09:00:00Z", membership: { role: { code: "member", display_name: "Member" } } },
    { id: "u5", display_name: "Vendor Support", email: "vendor@partner.io", status: false, created_at: "2025-05-30T09:00:00Z", membership: { role: { code: "guest", display_name: "Guest" } } },
  ],
};
const overview = {
  tenant: { id: "t1", code: "vikki", name: "Vikki Bank", status: "active", updated_at: "2026-09-01T00:00:00Z" },
  metrics: { active_users: 24, active_roles: 4, active_groups: 3, active_integration_connections: 6, items: 38 },
  attention: { pending_access_requests: 2 },
  recent_activity: [],
};

await context.route(/\/api\/v1\/(?!knowledge(?:\/|$)|agent(?:\/|$))/, async (route) => {
  const url = route.request().url();
  const body = url.includes("/platform/workspaces")
    ? workspaces
    : url.includes("/overview")
      ? overview
      : url.includes("/users")
        ? users
        : { items: [], total: 0 };
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify(body),
  });
});

const knowledgeHome = {
  total: 4,
  personal_collection_id: "c0",
  items: [
    { id: "c0", title: "My collection", description: "Private workspace for personal research material.", document_count: 12, source_count: 2, updated_at: "2026-09-01T10:00:00Z" },
    { id: "c1", title: "Credit policy", description: "Lending policy, limits, and approval matrices.", document_count: 84, source_count: 3, updated_at: "2026-09-08T10:00:00Z" },
    { id: "c2", title: "Operational runbooks", description: "Incident response and platform runbooks.", document_count: 41, source_count: 2, updated_at: "2026-09-05T09:00:00Z" },
    { id: "c3", title: "Vendor agreements", description: "Executed contracts and renewal schedules.", document_count: 27, source_count: 1, updated_at: "2026-08-29T14:00:00Z" },
  ],
  recent_documents: [
    { id: "d1", title: "Retail lending policy v4.2", content_type: "application/pdf", status: "ready", updated_at: "2026-09-11T08:20:00Z", source: { id: "s1", name: "Confluence" } },
    { id: "d2", title: "Q3 collections runbook", content_type: "text/markdown", status: "ready", updated_at: "2026-09-10T16:05:00Z", source: { id: "s2", name: "Google Drive" } },
    { id: "d3", title: "Vendor renewal schedule", content_type: "text/csv", status: "processing", updated_at: "2026-09-10T11:40:00Z", source: { id: "s2", name: "Google Drive" } },
  ],
};

await context.route("**/api/v1/knowledge/**", async (route) => {
  await route.fulfill({
    status: 200,
    contentType: "application/json",
    headers: { "access-control-allow-origin": "*" },
    body: JSON.stringify(knowledgeHome),
  });
});

const page = await context.newPage();
const errors = [];
page.on("pageerror", (e) => errors.push(`[pageerror] ${e.message}`));
page.on("console", (m) => {
  if (m.type() === "error") errors.push(`[console] ${m.text().slice(0, 200)}`);
});

for (const entry of paths) {
  const [path, click] = entry.split("::");
  const name =
    (path.replace(/^\//, "").replace(/[/?=&]/g, "-") || "root") +
    (click ? "-open" : "");
  await page.goto(`${BASE}${path}`, { waitUntil: "networkidle" });
  await page.waitForTimeout(900);
  if (click) {
    await page.locator(click).first().click();
    await page.waitForTimeout(500);
  }
  await page.screenshot({ path: `${outDir}/${name}.png` });
  console.log(`captured ${path} -> ${name}.png`);
}

if (errors.length) {
  console.log("\n--- page errors ---");
  console.log([...new Set(errors)].slice(0, 12).join("\n"));
}

await browser.close();
