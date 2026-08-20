import { chromium } from "playwright";

const SCRATCH = "/private/tmp/claude-502/-Users-duynguyen-Documents-vikki-bank-code-ai-team-BoThesis/3ba7257d-bb56-4578-a38f-00143938855b/scratchpad";

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 900 } });
page.on("console", (msg) => console.log("[console]", msg.type(), msg.text()));
page.on("pageerror", (err) => console.log("[pageerror]", err.message));

await page.goto("http://127.0.0.1:3000/app", { waitUntil: "networkidle" });
await page.screenshot({ path: `${SCRATCH}/01-loaded.png` });

const textarea = page.locator("textarea").first();
await textarea.waitFor({ state: "visible", timeout: 15000 });
await textarea.fill("Search the knowledge base for our internal leave or vacation policy and summarize it with sources.");
await page.keyboard.press("Enter");

// Capture mid-stream (tool activity / commentary showing)
await page.waitForTimeout(2500);
await page.screenshot({ path: `${SCRATCH}/02-midstream.png`, fullPage: true });

// Wait for completion
await page.waitForTimeout(20000);
await page.screenshot({ path: `${SCRATCH}/03-done.png`, fullPage: true });

const bodyText = await page.locator(".assistant-turn").first().innerText().catch(() => "(no assistant-turn found)");
console.log("=== assistant-turn text ===");
console.log(bodyText);

await browser.close();
