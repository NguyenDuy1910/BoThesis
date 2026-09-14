/**
 * Finds Tailwind arbitrary-value classes that compile to nothing.
 *
 * `text-[var(--x)]` is ambiguous in Tailwind v4 — the value could be a colour
 * or a length — so Tailwind emits no rule at all and the declaration silently
 * does nothing. The same trap applies to `border-`, `ring-`, `outline-` and
 * friends. This walks every such class in the source, looks it up in the built
 * stylesheet, and reports the ones with no rule behind them.
 *
 *   node scripts/arbitrary-value-audit.mjs <path-to-built-css>
 */
import { readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";

const cssPath = process.argv[2];
if (!cssPath) {
  console.error("usage: node scripts/arbitrary-value-audit.mjs <built.css>");
  process.exit(2);
}
const css = readFileSync(cssPath, "utf8");

function walk(dir, out = []) {
  for (const entry of readdirSync(dir)) {
    const full = join(dir, entry);
    if (statSync(full).isDirectory()) {
      if (entry === "node_modules" || entry === ".next") continue;
      walk(full, out);
    } else if (/\.(tsx|ts)$/.test(entry)) {
      out.push(full);
    }
  }
  return out;
}

const CLASS_RE = /(?:^|[\s"'`])((?:[a-z-]+:)*)([a-z]+(?:-[a-z]+)*)-\[([^\]\s]+)\]/g;
const found = new Map();

for (const file of walk("src")) {
  const src = readFileSync(file, "utf8");
  for (const m of src.matchAll(CLASS_RE)) {
    const [, variants, util, value] = m;
    if (!value.includes("var(--")) continue;
    const cls = `${variants}${util}-[${value}]`;
    if (!found.has(cls)) found.set(cls, { util, value, files: new Set(), variants });
    found.get(cls).files.add(file.replace(/^src\//, ""));
  }
}

// A class is live if its escaped selector appears in the stylesheet.
const escapeClass = (cls) => cls.replace(/[.[\]()+*:,#>~/%]/g, (c) => `\\${c}`);

const dead = [];
for (const [cls, info] of found) {
  const selector = `.${escapeClass(cls)}`;
  if (!css.includes(selector)) dead.push({ cls, ...info });
}

console.log(`${found.size} arbitrary var() classes in source, ${dead.length} with no rule\n`);

const byUtil = new Map();
for (const d of dead) {
  if (!byUtil.has(d.util)) byUtil.set(d.util, []);
  byUtil.get(d.util).push(d);
}
for (const [util, items] of [...byUtil].sort((a, b) => b[1].length - a[1].length)) {
  console.log(`  ${String(items.length).padStart(3)}  ${util}-[…]`);
  for (const i of items.slice(0, 4)) {
    console.log(`        ${i.cls}   (${[...i.files][0]}${i.files.size > 1 ? ` +${i.files.size - 1}` : ""})`);
  }
  if (items.length > 4) console.log(`        …and ${items.length - 4} more`);
}

process.exit(dead.length ? 1 : 0);
