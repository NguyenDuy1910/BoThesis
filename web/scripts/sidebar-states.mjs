/**
 * Verifies the rail's interaction states and its quieter tiers:
 * default / hover / focus-visible / active / restricted, the Recent section's
 * density, the collapsed rail, and dark mode.
 *
 *   BASE_URL=http://localhost:3100 node scripts/sidebar-states.mjs
 */
import { chromium } from "playwright";

const BASE = process.env.BASE_URL ?? "http://localhost:3000";

const session = (permissions) => ({
  access_token: "t",
  token_type: "bearer",
  expires_at: new Date(Date.now() + 86_400_000).toISOString(),
  user_id: "u",
  email: "duy.nguyen@enterprise.ai",
  display_name: "Duy Nguyen",
  active_workspace_id: "t1",
  permissions,
  workspaces: [{ id: "t1", code: "v", name: "Vikki Bank", role_codes: ["owner"], permissions }],
  platform_permissions: [],
});

const now = Date.now();
const conversations = [
  { id: "c1", title: "Policy comparison", titleSource: "user", createdAt: now - 1e6, updatedAt: now - 1e5 },
  { id: "c2", title: "Expense review", titleSource: "user", createdAt: now - 2e6, updatedAt: now - 2e5 },
  {
    id: "c3",
    title: "A deliberately long conversation title that has to truncate inside the rail",
    titleSource: "user",
    createdAt: now - 3e6,
    updatedAt: now - 3e5,
  },
];

let failures = 0;
const check = (ok, message) => {
  console.log(`  ${ok ? "pass" : "FAIL"}  ${message}`);
  if (!ok) failures += 1;
};

const browser = await chromium.launch();

async function open({ permissions = ["tenant.read", "knowledge.read"], theme = "light", seedChats = false } = {}) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 900 } });
  await context.addInitScript(
    ([s, t, chats]) => {
      sessionStorage.setItem("bothesis.auth.session", s);
      localStorage.setItem("bothesis-theme", t);
      if (chats) {
        for (const key of ["bothesis-conversations:u:t1", "bothesis-conversations:duy.nguyen@enterprise.ai:t1"]) {
          localStorage.setItem(key, chats);
        }
      }
    },
    [JSON.stringify(session(permissions)), theme, seedChats ? JSON.stringify(conversations) : ""],
  );
  await context.route("**/api/v1/**", (route) =>
    route.fulfill({ status: 200, contentType: "application/json", headers: { "access-control-allow-origin": "*" }, body: JSON.stringify({ items: [], total: 0, recent_documents: [], personal_collection_id: null }) }),
  );
  const page = await context.newPage();
  await page.goto(`${BASE}/app`, { waitUntil: "networkidle" });
  await page.waitForTimeout(800);
  return { context, page };
}

const styleOf = (page, selector) =>
  page.evaluate((sel) => {
    const el = document.querySelector(sel);
    if (!el) return null;
    const cs = getComputedStyle(el);
    return { bg: cs.backgroundColor, color: cs.color, shadow: cs.boxShadow, outline: cs.outlineStyle, cursor: cs.cursor };
  }, selector);

// ── row states ────────────────────────────────────────────────────────────
console.log("\nrow states");
{
  const { context, page } = await open();
  const LIB = "nav.shell-nav a[href='/knowledge?view=library']";
  const KNOW = "nav.shell-nav a[href='/knowledge']";

  const base = await styleOf(page, LIB);
  check(base.bg === "rgba(0, 0, 0, 0)", `default has no fill (${base.bg})`);

  await page.hover(LIB);
  await page.waitForTimeout(220);
  const hover = await styleOf(page, LIB);
  check(hover.bg !== base.bg, `hover paints a fill (${hover.bg})`);

  await page.evaluate((sel) => document.querySelector(sel).focus(), LIB);
  await page.keyboard.press("Tab");
  await page.keyboard.press("Shift+Tab");
  await page.waitForTimeout(200);
  const focused = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    el.focus();
    const cs = getComputedStyle(el);
    return { shadow: cs.boxShadow, matches: el.matches(":focus-visible") };
  }, LIB);
  check(focused.shadow !== "none", `focus paints a ring (${focused.shadow.slice(0, 42)}…)`);

  check(
    hover.color !== base.color,
    `hover strengthens the label (${base.color} -> ${hover.color})`,
  );

  await page.goto(`${BASE}/knowledge`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  const active = await styleOf(page, KNOW);
  check(active.bg !== "rgba(0, 0, 0, 0)", `active paints a tint (${active.bg})`);
  check(active.color !== base.color, `active recolours the label (${active.color})`);
  const indicator = await page.evaluate((sel) => {
    const el = document.querySelector(sel);
    const bar = [...el.children].find((c) => c.getBoundingClientRect().width <= 4);
    if (!bar) return null;
    const r = bar.getBoundingClientRect();
    return { w: Math.round(r.width), h: Math.round(r.height), bg: getComputedStyle(bar).backgroundColor };
  }, KNOW);
  check(indicator?.w === 3, `active carries a ${indicator?.w}px accent indicator, ${indicator?.h}px tall`);
  await context.close();
}

// ── restricted ────────────────────────────────────────────────────────────
console.log("\nrestricted destination");
{
  const { context, page } = await open({ permissions: ["knowledge.read"] });
  const restricted = await page.evaluate(() => {
    const el = [...document.querySelectorAll("nav.shell-nav [aria-disabled='true']")].find((e) =>
      e.textContent.includes("Apps"),
    );
    if (!el) return null;
    return {
      tag: el.tagName,
      cursor: getComputedStyle(el).cursor,
      title: el.getAttribute("title"),
      srText: el.querySelector(".sr-only")?.textContent ?? "",
      isLink: el.tagName === "A",
    };
  });
  check(Boolean(restricted), "an unpermitted destination still appears in the rail");
  check(restricted?.isLink === false, `it is inert, not a link (<${restricted?.tag.toLowerCase()}>)`);
  check(restricted?.cursor === "not-allowed", "it shows a not-allowed cursor");
  check(Boolean(restricted?.srText), `it explains itself: "${restricted?.srText.slice(0, 56)}…"`);

  const stillVisible = await page.evaluate(
    () => document.querySelectorAll("nav.shell-nav a[href='/knowledge']").length,
  );
  check(stillVisible === 1, "permitted destinations are unaffected");
  await context.close();
}

// ── recent section ────────────────────────────────────────────────────────
console.log("\nrecent conversations");
{
  const { context, page } = await open({ seedChats: true });
  const recent = await page.evaluate(() => {
    const nav = document.querySelector("nav.shell-nav");
    const label = [...nav.querySelectorAll("p")].find((p) => /today|recent|previous|days|older/i.test(p.textContent));
    const rows = [...nav.querySelectorAll("button")].filter((b) => b.title && /Policy comparison|Expense review|deliberately long/.test(b.title));
    const first = rows[0];
    const navRow = nav.querySelector("a[href='/knowledge']");
    const px = (v) => Math.round(parseFloat(v));
    const longRow = rows.find((r) => r.title.includes("deliberately long"));
    const longLabel = [...(longRow?.querySelectorAll("span") ?? [])].find((s) =>
      s.className.includes("truncate"),
    );
    return {
      labelText: label?.textContent.trim() ?? null,
      labelFont: label ? px(getComputedStyle(label).fontSize) : null,
      rowCount: rows.length,
      rowHeight: first ? Math.round(first.getBoundingClientRect().height) : null,
      rowFont: first ? px(getComputedStyle(first).fontSize) : null,
      rowIcon: first ? Math.round(first.querySelector("svg").getBoundingClientRect().width) : null,
      navFont: px(getComputedStyle(navRow).fontSize),
      truncates: longLabel ? longLabel.scrollWidth > longLabel.clientWidth : false,
      hasTitle: Boolean(longRow?.title),
    };
  });
  check(recent.rowCount >= 3, `recent rows render (${recent.rowCount})`);
  check(recent.rowHeight === 32, `recent row is ${recent.rowHeight}px — shorter than a destination`);
  check(recent.rowFont < recent.navFont, `recent type (${recent.rowFont}px) is quieter than nav (${recent.navFont}px)`);
  check(recent.rowIcon === 16, `recent icon is ${recent.rowIcon}px`);
  check(recent.labelFont === 11, `section label "${recent.labelText}" is ${recent.labelFont}px`);
  check(recent.truncates, "a long conversation title truncates");
  check(recent.hasTitle, "a long conversation title carries a tooltip");

  const widest = await page.evaluate(() => {
    const nav = document.querySelector("nav.shell-nav");
    const railWidth = nav.getBoundingClientRect().width;
    const rows = [...nav.querySelectorAll("a,button")].filter(
      (el) => el.getBoundingClientRect().height >= 24,
    );
    return {
      railWidth: Math.round(railWidth),
      widest: Math.round(Math.max(...rows.map((r) => r.getBoundingClientRect().width))),
    };
  });
  check(
    widest.widest <= widest.railWidth,
    `no row outgrows the rail (widest ${widest.widest}px of ${widest.railWidth}px)`,
  );

  const trailing = await page.evaluate(() => {
    const nav = document.querySelector("nav.shell-nav");
    const row = [...nav.querySelectorAll(".group\\/recent")][0];
    const menu = row?.querySelector(":scope > span");
    return menu ? Number(getComputedStyle(menu).opacity) : null;
  });
  check(trailing === 0, "the row menu is hidden until hover or focus");
  await context.close();
}

// ── collapsed rail ────────────────────────────────────────────────────────
console.log("\ncollapsed rail");
{
  const { context, page } = await open();
  await page.click("button[aria-label='Collapse navigation']");
  await page.waitForTimeout(400);
  const collapsed = await page.evaluate(() => {
    const nav = document.querySelector("nav.shell-nav");
    const row = nav.querySelector("a[href='/knowledge']");
    return {
      width: Math.round(nav.getBoundingClientRect().width),
      rowTitle: row.getAttribute("title"),
      labelHidden: !row.querySelector("span:not(.sr-only)"),
      justify: getComputedStyle(row).justifyContent,
    };
  });
  check(collapsed.width === 60, `rail is ${collapsed.width}px`);
  check(collapsed.labelHidden, "labels are dropped, not squeezed");
  check(collapsed.rowTitle === "Knowledge", "each icon keeps a tooltip");
  check(collapsed.justify === "center", "icons centre in the collapsed rail");
  await context.close();
}

// ── dark ──────────────────────────────────────────────────────────────────
console.log("\ndark mode");
{
  const { context, page } = await open({ theme: "dark" });
  await page.goto(`${BASE}/knowledge`, { waitUntil: "networkidle" });
  await page.waitForTimeout(700);
  const dark = await page.evaluate(() => {
    const nav = document.querySelector("nav.shell-nav");
    const main = document.querySelector(".shell__main");
    const active = nav.querySelector("a[href='/knowledge']");
    return {
      nav: getComputedStyle(nav).backgroundColor,
      main: getComputedStyle(main).backgroundColor,
      activeBg: getComputedStyle(active).backgroundColor,
      activeColor: getComputedStyle(active).color,
    };
  });
  const lum = (rgb) => {
    const [r, g, b] = rgb.match(/\d+/g).map(Number);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  check(lum(dark.nav) < 60, `rail is dark (${dark.nav})`);
  check(dark.nav !== dark.main, `rail and working surface stay distinct (${dark.nav} vs ${dark.main})`);
  check(
    dark.activeBg !== "rgba(0, 0, 0, 0)" && dark.activeBg !== dark.nav,
    `active state is visible in dark (${dark.activeBg})`,
  );
  await context.close();
}

console.log(`\n=== ${failures === 0 ? "sidebar states hold" : `${failures} issue(s)`} ===`);
await browser.close();
process.exit(failures === 0 ? 0 : 1);
