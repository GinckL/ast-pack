// Records README media from the real UI against a real repository.
//
//   node e2e/record_media.mjs --mode demo  --repo ../hono --target Hono.fetch --out demo.webm
//   node e2e/record_media.mjs --mode graph --repo ../hono --target Hono.fetch --out graph.png
//   node e2e/record_media.mjs --mode trace --repo ../tests/fixtures/polyglot --out trace.png
//   node e2e/record_media.mjs --mode light --repo ../flask --target Flask.full_dispatch_request --out light.png
//
// Requires `ast-pack` on PATH and Playwright with Chromium.
import { spawn } from "node:child_process";
import { mkdtempSync, readdirSync, renameSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import path from "node:path";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]]] : acc), []),
);
const mode = args.mode ?? "demo";
const port = Number(args.port ?? 7995);
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const server = spawn("ast-pack", ["serve", "-C", args.repo, "--port", String(port), "--json"], { stdio: ["ignore", "pipe", "inherit"] });
await new Promise((r) => server.stdout.once("data", r));
const url = `http://127.0.0.1:${port}/`;

const viewport = { width: 1440, height: 900 };
const browser = await chromium.launch();
const videoDir = mode === "demo" ? mkdtempSync(path.join(tmpdir(), "astpack-video-")) : null;
const ctx = await browser.newContext({
  viewport,
  deviceScaleFactor: mode === "demo" ? 1 : 2,
  colorScheme: mode === "light" ? "light" : "dark",
  ...(videoDir ? { recordVideo: { dir: videoDir, size: viewport } } : {}),
});
await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: url });
const page = await ctx.newPage();

// Smooth, human-like pointer moves.
async function glide(x, y, steps = 18) {
  await page.mouse.move(x, y, { steps });
}
async function hoverSomeNode() {
  const box = await page.locator('[data-testid="graph"] canvas').boundingBox();
  for (let y = box.y + box.height * 0.35; y < box.y + box.height * 0.7; y += 10) {
    for (let x = box.x + box.width * 0.3; x < box.x + box.width * 0.75; x += 10) {
      await page.mouse.move(x, y);
      if ((await page.evaluate(() => document.querySelector('[data-testid="graph"] canvas').style.cursor)) === "pointer") return true;
    }
  }
  return false;
}
async function packTyped(target, typingDelay = 70) {
  await page.keyboard.press("Control+k");
  await sleep(250);
  await page.keyboard.type(target, { delay: typingDelay });
  await page.waitForSelector('[data-testid="command-results"] button');
  await sleep(700);
  await page.keyboard.press("Enter");
  await page.waitForSelector("[data-file]", { timeout: 30000 });
}

await page.goto(url);
await page.waitForFunction(() => document.body.innerText.includes("symbols"));

if (mode === "demo") {
  await sleep(1800);
  await packTyped(args.target ?? "Hono.fetch", 85);
  await sleep(3200);
  await hoverSomeNode();
  await sleep(1400);
  await glide(viewport.width * 0.42, viewport.height * 0.86);
  await page.keyboard.press("]");
  await sleep(1500);
  await page.keyboard.press("[");
  await sleep(600);
  await page.keyboard.press("[");
  await sleep(1600);
  const pill = page.locator('[data-testid="pruned-pill"]').nth(1);
  const pb = await pill.boundingBox();
  if (pb) {
    await glide(pb.x + 120, pb.y + pb.height / 2);
    await pill.click();
    await sleep(1300);
  }
  const copy = await page.locator('[data-testid="copy-button"]').boundingBox();
  await glide(copy.x + copy.width / 2, copy.y + copy.height / 2, 24);
  await sleep(300);
  await page.locator('[data-testid="copy-button"]').click();
  await sleep(2000);
} else if (mode === "graph" || mode === "light") {
  if (mode === "light") await page.evaluate(() => localStorage.setItem("ast-pack-theme", "light"));
  await packTyped(args.target, 20);
  await sleep(4000);
  if (mode === "light") {
    await page.locator('[data-testid="pruned-pill"]').nth(1).click();
    await sleep(900);
  }
  await page.mouse.move(viewport.width * 0.3, 140); // park the pointer: show the whole graph lit
  await sleep(700);
  await page.screenshot({ path: args.out });
} else if (mode === "trace") {
  const trace = [
    "Traceback (most recent call last):",
    '  File "/srv/app/py/shop/api.py", line 14, in checkout_handler',
    '    receipt = process_payment(req, Gateway("sk_live"))',
    '  File "/srv/app/py/shop/payments/service.py", line 12, in process_payment',
    "    validate_request(req)",
    '  File "/srv/app/py/shop/payments/validation.py", line 30, in validate_request',
    '    raise ValidationError("invalid card")',
    "shop.payments.validation.ValidationError: invalid card",
  ].join("\n");
  await page.keyboard.press("Control+k");
  await page.evaluate((t) => {
    const el = document.querySelector('[data-testid="command-input"]');
    const dt = new DataTransfer();
    dt.setData("text/plain", t);
    el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
  }, trace);
  await page.waitForSelector('[data-testid="trace-panel"]');
  await sleep(3500);
  await page.screenshot({ path: args.out });
}

await ctx.close();
await browser.close();
server.kill();
if (videoDir) {
  const file = readdirSync(videoDir).find((f) => f.endsWith(".webm"));
  renameSync(path.join(videoDir, file), args.out);
}
console.log(`wrote ${args.out}`);
