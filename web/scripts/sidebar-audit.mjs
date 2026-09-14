/**
 * Measures the rail against the intended spec: row heights, type scale, icon
 * sizes, the shared label axis, and the account popover's geometry.
 *
 * Reports what it finds rather than asserting a single correct number, so a
 * deliberate change shows up as a changed measurement instead of a failure.
 *
 *   node scripts/sidebar-audit.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";

const session = {
  access_token: "t",
  token_type: "bearer",
  expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  user_id: "u",
  email: "duy.nguyen@enterprise.ai",
  display_name: "Duy Nguyen",
  active_tenant_id: "t1",
  permissions: ["admin"],
  tenants: [
    { id: "t1", code: "vikki", name: "Vikki Bank", role_id: "r", role_code: "owner", permissions: ["admin"] },
    { id: "t2", code: "ai", name: "AI Team", role_id: "r", role_code: "admin", permissions: [] },
    { id: "t3", code: "th", name: "Thesis Project", role_id: "r", role_code: "member", permissions: [] },
  ],
  platform_scopes: ["root_admin"],
};

const browser = await chromium.launch();
const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
await context.addInitScript((s) => {
  sessionStorage.setItem("bothesis.auth.session", s);
  localStorage.setItem("bothesis-theme", "light");
}, JSON.stringify(session));
await context.route("**/api/v1/**", (route) =>
  route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ items: [], total: 0, recent_documents: [], personal_collection_id: null }) }),
);

const page = await context.newPage();
await page.goto(`${BASE}/knowledge`, { waitUntil: "networkidle" });
await page.waitForTimeout(900);

const rail = await page.evaluate(() => {
  const nav = document.querySelector("nav.shell-nav");
  const px = (v) => Math.round(parseFloat(v) * 10) / 10;
  const rows = [...nav.querySelectorAll("a,button")].filter((el) => {
    const r = el.getBoundingClientRect();
    return r.width > 80 && r.height >= 24;
  });
  const describe = (el) => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const label = [...el.children].find((c) => c.tagName === "SPAN" && c.textContent.trim());
    const svg = el.querySelector("svg");
    // The leading element of the row — icon, brand mark or avatar. Its x is
    // the rail's left gutter, which is the alignment that actually matters.
    // The leftmost child wide enough to be an icon, mark or avatar. The
    // active-state accent bar is 3px and is deliberately flush with the row
    // edge, so it is excluded rather than mistaken for the gutter.
    const lead = [...el.children]
      .map((c) => c.getBoundingClientRect())
      .filter((r) => r.width > 8)
      .sort((a, b) => a.x - b.x)[0];
    return {
      text: (el.textContent || "").trim().replace(/\s+/g, " ").slice(0, 22),
      h: Math.round(r.height),
      font: px(cs.fontSize),
      weight: cs.fontWeight,
      padX: px(cs.paddingLeft),
      radius: px(cs.borderTopLeftRadius),
      icon: svg ? Math.round(svg.getBoundingClientRect().width) : null,
      labelX: label ? Math.round(label.getBoundingClientRect().x) : null,
      gutter: lead ? Math.round(lead.x) : null,
      color: cs.color,
    };
  };
  const groupLabels = [...nav.querySelectorAll("p")].map((p) => ({
    text: p.textContent.trim().slice(0, 18),
    font: px(getComputedStyle(p).fontSize),
    weight: getComputedStyle(p).fontWeight,
  }));
  return {
    width: Math.round(nav.getBoundingClientRect().width),
    bg: getComputedStyle(nav).backgroundColor,
    mainBg: getComputedStyle(document.querySelector(".shell__main")).backgroundColor,
    rows: rows.map(describe),
    groupLabels,
  };
});

console.log(`rail width ${rail.width}px   rail bg ${rail.bg}   main bg ${rail.mainBg}\n`);
console.log("row                     h   font  wt   padX  r   icon  gutter");
for (const r of rail.rows) {
  console.log(
    `${r.text.padEnd(22)} ${String(r.h).padStart(3)} ${String(r.font).padStart(6)} ${String(r.weight).padStart(4)} ${String(r.padX).padStart(5)} ${String(r.radius).padStart(3)} ${String(r.icon ?? "-").padStart(5)} ${String(r.gutter ?? "-").padStart(7)}`,
  );
}
console.log("\nsection labels:", rail.groupLabels.map((g) => `${g.text}=${g.font}px/${g.weight}`).join("  "));

const gutters = [...new Set(rail.rows.map((r) => r.gutter).filter(Boolean))];
console.log(`\nleft gutter: ${gutters.join(", ")}px  ${gutters.length === 1 ? "— single gutter" : "— MISALIGNED"}`);
const labelAxes = [...new Set(rail.rows.filter((r) => r.icon === 18).map((r) => r.labelX).filter(Boolean))];
console.log(`nav label axis: ${labelAxes.join(", ")}px  ${labelAxes.length === 1 ? "— single axis" : "— MISALIGNED"}`);
const fonts = [...new Set(rail.rows.map((r) => r.font))].sort((a, b) => a - b);
console.log(`type scale in rows: ${fonts.join(", ")}px`);

// Account popover geometry.
await page.locator("button[aria-label='Account and workspace']").click();
await page.waitForTimeout(450);
const pop = await page.evaluate(() => {
  const menu = document.querySelector("[role='menu']");
  const trigger = document.querySelector("button[aria-label='Account and workspace']");
  const m = menu.getBoundingClientRect();
  const t = trigger.getBoundingClientRect();
  const items = [...menu.querySelectorAll("[role='menuitem']")];
  return {
    w: Math.round(m.width),
    h: Math.round(m.height),
    placement: menu.dataset.placement,
    gapToTrigger: Math.round(t.top - m.bottom),
    leftAlignedWithTrigger: Math.round(m.left - t.left),
    itemCount: items.length,
    itemFont: items[0] ? Math.round(parseFloat(getComputedStyle(items[0]).fontSize) * 10) / 10 : null,
    bg: getComputedStyle(menu).backgroundColor,
    radius: getComputedStyle(menu).borderTopLeftRadius,
    withinViewport: m.top >= 0 && m.bottom <= window.innerHeight,
  };
});
console.log("\npopover:", JSON.stringify(pop, null, 1));

await browser.close();
