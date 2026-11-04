// End-to-end smoke test: real `ast-pack serve` + built UI in Chromium.
//
//   node e2e/smoke.mjs [--repo PATH] [--shots DIR] [--target NAME]
//
// Requires `ast-pack` on PATH and Playwright with Chromium.
import { spawn } from "node:child_process";
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const here = path.dirname(fileURLToPath(import.meta.url));
const args = Object.fromEntries(
  process.argv.slice(2).reduce((acc, a, i, all) => (a.startsWith("--") ? [...acc, [a.slice(2), all[i + 1]]] : acc), []),
);
const repo = args.repo ?? path.resolve(here, "../../tests/fixtures/polyglot");
const shots = args.shots ?? null;
const target = args.target ?? "process_payment";
const port = Number(args.port ?? 7991);

function startServer() {
  return new Promise((resolve, reject) => {
    const proc = spawn("ast-pack", ["serve", "-C", repo, "--port", String(port), "--json", "--watch-interval", "0.5"], {
      stdio: ["ignore", "pipe", "inherit"],
    });
    let buf = "";
    proc.stdout.on("data", (d) => {
      buf += d;
      const line = buf.split("\n").find((l) => l.startsWith("{"));
      if (line) resolve({ proc, info: JSON.parse(line) });
    });
    proc.on("exit", (code) => reject(new Error(`server exited ${code}`)));
    setTimeout(() => reject(new Error("server did not start")), 30000);
  });
}

const counterText = (page) =>
  page.locator('[data-testid="token-counter"] [role="text"]').evaluateAll((els) => els.map((e) => e.getAttribute("aria-label")).join(" | "));
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function check(cond, msg) {
  if (!cond) throw new Error(`FAILED: ${msg}`);
  console.log(`  ✓ ${msg}`);
}

const { proc, info } = await startServer();
console.log(`server ${info.url} (ui: ${info.ui})`);
const browser = await chromium.launch();
const errors = [];
try {
  const ctx = await browser.newContext({ viewport: { width: 1600, height: 960 }, deviceScaleFactor: 1, colorScheme: "dark" });
  await ctx.grantPermissions(["clipboard-read", "clipboard-write"], { origin: info.url });
  const page = await ctx.newPage();
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
  page.on("pageerror", (e) => errors.push(String(e)));
  if (shots) mkdirSync(shots, { recursive: true });
  const shot = async (name) => shots && page.screenshot({ path: path.join(shots, `${name}.png`) });

  await page.goto(info.url);
  check(info.ui === true, "server reports the UI bundle");
  const ld = await page.locator('script[type="application/ld+json"]').textContent();
  check(ld.includes("SoftwareSourceCode") && ld.includes("SoftwareApplication"), "JSON-LD present");
  await page.waitForFunction(() => document.body.innerText.includes("symbols"), null, { timeout: 15000 });
  await sleep(1800);
  await shot("01-idle");

  // Search
  await page.keyboard.press("Control+k");
  await page.keyboard.type(target.slice(0, 7), { delay: 40 });
  await page.waitForSelector('[data-testid="command-results"] button', { timeout: 8000 });
  await sleep(250);
  await shot("02-search");
  const firstRow = await page.locator('[data-testid="command-results"] button').first().innerText();
  check(firstRow.length > 0, `search shows results (${firstRow.split("\n")[0]})`);

  // Pack
  await page.keyboard.press("Enter");
  await page.waitForSelector('[data-file]', { timeout: 15000 });
  await page.waitForFunction(() => document.querySelector('[data-testid="token-counter"]')?.textContent?.includes("Saved"), null, { timeout: 10000 });
  await sleep(2200);
  await shot("03-packed");
  const files = await page.locator("[data-file]").count();
  check(files > 0, `code pane shows ${files} file(s)`);
  const pills = await page.locator('[data-testid="pruned-pill"]').count();
  check(pills > 0, `pruned pills rendered (${pills})`);
  const highlighted = await page.locator(".shiki-line span[style]").count();
  check(highlighted > 20, `syntax highlighting applied (${highlighted} tokens)`);

  // Depth: keyboard ([ ]) and the slider
  const counterBefore = await counterText(page);
  await page.keyboard.press("[");
  await sleep(1800);
  await shot("04-depth1");
  const counterAfter = await counterText(page);
  check(counterBefore !== counterAfter, `depth keys update the token counter (${counterBefore} → ${counterAfter})`);
  check((await page.locator('[data-testid="depth-slider"]').inputValue()) === "1", "slider follows the [ key");
  await page.keyboard.press("]");
  await page.keyboard.press("]");
  await sleep(1500);
  check((await page.locator('[data-testid="depth-slider"]').inputValue()) === "3", "slider follows the ] key");
  await page.locator('[data-testid="depth-slider"]').fill("2");
  await sleep(1500);
  check((await page.locator('[data-testid="depth-slider"]').inputValue()) === "2", "dragging the slider sets the depth");
  await shot("05-depth2");

  // Expand a pruned pill
  await page.locator('[data-testid="pruned-pill"]').first().click();
  await sleep(700);
  check((await page.locator('[data-testid="pruned-pill"][aria-expanded="true"]').count()) === 1, "pruned pill expands");
  await shot("06-pill");

  // Copy
  await page.locator('[data-testid="copy-button"]').click();
  await sleep(250);
  await shot("07-copied");
  const clip = await page.evaluate(() => navigator.clipboard.readText());
  check(clip.includes("## Context:"), `clipboard holds the bundle (${clip.length} chars)`);

  // Stack trace paste
  const trace = [
    "Traceback (most recent call last):",
    '  File "/srv/app/py/shop/api.py", line 14, in checkout_handler',
    '    receipt = process_payment(req, Gateway("sk_live"))',
    '  File "/srv/app/py/shop/payments/validation.py", line 30, in validate_request',
    '    raise ValidationError("invalid card")',
    "shop.payments.validation.ValidationError: invalid card",
  ].join("\n");
  if (repo.endsWith("polyglot")) {
    await page.keyboard.press("Control+k");
    await page.evaluate((t) => {
      const el = document.querySelector('[data-testid="command-input"]');
      const dt = new DataTransfer();
      dt.setData("text/plain", t);
      el.dispatchEvent(new ClipboardEvent("paste", { clipboardData: dt, bubbles: true, cancelable: true }));
    }, trace);
    await page.waitForSelector('[data-testid="trace-panel"]', { timeout: 10000 });
    await sleep(2000);
    await shot("08-trace");
    check(true, "pasting a stack trace packs it");
  }

  // Theme + shortcuts overlay
  await page.locator("body").click({ position: { x: 5, y: 500 } });
  await page.keyboard.press("t");
  await sleep(900);
  await shot("09-light");
  await page.keyboard.press("?");
  await sleep(400);
  await shot("10-shortcuts");
  check(await page.getByRole("dialog", { name: "Keyboard shortcuts" }).isVisible(), "shortcuts overlay opens");

  check(errors.length === 0, `no console errors${errors.length ? ": " + errors.join(" | ") : ""}`);
  console.log("e2e passed");
} finally {
  await browser.close();
  proc.kill();
}
