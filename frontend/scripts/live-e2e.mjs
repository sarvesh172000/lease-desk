// The thin slice, end to end, against the live API (chunk A8).
//
//   LEASEDESK_DB_NAME=leasedesk_demo make demo-data          # fresh January
//   (cd backend && python3 -m uvicorn app.main:app --port 8000) &
//   NEXT_PUBLIC_API_URL=http://localhost:8000 npm run build && npx next start -p 3000 &
//   BASE_URL=http://localhost:3000 npm run live-e2e
//
// Signs in as the Bay Area regional manager, opens two held January
// exceptions with both real documents boxed, streams the investigation,
// approves a correct charge until the gateway posts it, holds an over-bill,
// switches to the auditor (no Approve offered; a forced request is refused
// and lands in the audit trail as a denied row), and checks the chain.
// Screenshots go to docs/screenshots/live-*.png. Exits non-zero on any failure.
//
// Mutates the database it runs against: run it on a fresh demo database.
import { mkdirSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://localhost:8000";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "docs", "screenshots");
mkdirSync(OUT, { recursive: true });

const problems = [];
const check = (ok, what) => {
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
  if (!ok) problems.push(what);
};

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
page.on("console", (m) => m.type() === "error" && console.error("console:", m.text()));
page.on("response", (r) => r.status() >= 500 && problems.push(`HTTP ${r.status()} ${r.url()}`));

async function shot(name, full = true) {
  await page.waitForFunction(() => Array.from(document.querySelectorAll("canvas")).every((c) => c.width > 0), null, { timeout: 20000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(500);
  const file = join(OUT, `live-${name}.png`);
  await page.screenshot({ path: file, fullPage: full });
  console.log("     saved", file);
}

async function openCharge(match) {
  await page.goto(BASE + "/", { waitUntil: "networkidle" });
  await page.waitForSelector("[data-testid=charge-row]");
  const row = page.locator("[data-testid=charge-row]", { hasText: match }).first();
  await row.click();
  await page.waitForURL(/\/exceptions\/exc_\d+$/);
  return page.url().split("/").pop();
}

async function moneyScreen(name, match) {
  const id = await openCharge(match);
  await page.waitForSelector("[data-testid=citation-box] >> nth=1", { timeout: 20000 });
  check((await page.locator("[data-testid=citation-box]").count()) === 2, `${name}: invoice line and lease clause both boxed (${id})`);
  await page.getByRole("button", { name: "Run investigation" }).click();
  await page.waitForSelector('[data-stage="complete"][data-done="true"]', { timeout: 20000 });
  check((await page.locator('[data-stage="found"][data-done="true"]').count()) === 1, `${name}: investigation found the cited clause`);
  check((await page.locator('[data-stage="remeasured"][data-done="true"]').count()) === 0, `${name}: no remeasurement invented`);
  await shot(`money-${name}`);
  return id;
}

// 1. sign in
await page.goto(BASE + "/login", { waitUntil: "networkidle" });
await page.fill("#email", "dana.whitfield@northbaypt.example");
await page.fill("#password", "demo");
await page.getByRole("button", { name: "Sign in" }).click();
await page.waitForSelector("text=Latest activity");
await page.waitForSelector("[data-testid=exception-row]");
check((await page.locator("text=Fixtures").count()) === 0, "dashboard is live (no Fixtures badge)");
check((await page.locator("text=Dana Whitfield").count()) > 0, "signed in as Dana Whitfield");
check((await page.locator("text=$25,736.36").count()) === 1, "dollars held is the five over-bills, $25,736.36");
check((await page.locator("[data-testid=exception-row]").count()) === 5, "five held January exceptions listed");
await page.waitForTimeout(400);
await shot("dashboard");

// 2. the money screen, twice
await moneyScreen("suite-118", "billed $4,820.00");
await moneyScreen("duplicate-rent", "billed $19,626.65, lease supports $0.00");

// 3. approve a correct charge: the gateway posts it
const goodId = await openCharge("CLINIC-02 Jan 2026 base_rent: $9,700.00 matches the lease");
await page.waitForSelector("[data-testid=citation-box] >> nth=1", { timeout: 20000 });
await page.getByTestId("actions").getByRole("button", { name: "Approve", exact: true }).click();
// a financial action confirms first, restating the amount
await page.getByTestId("confirm-action").click();
await page.waitForSelector("[data-testid=action-result]", { timeout: 20000 });
const result = await page.locator("[data-testid=action-result]").innerText();
check(/posted to the ledger/.test(result) && /POSTED/.test(result), `approve ${goodId}: "${result}"`);
await page.waitForSelector('[data-state="POSTED"]', { timeout: 10000 });
check((await page.getByTestId("actions").getByRole("button", { name: "Approve", exact: true }).count()) === 0, "after posting, Approve is gone");
await shot("approved-posted");

// 4. hold an over-bill
const camId = await openCharge("cam_estimate: billed $6,458.33");
await page.waitForSelector("[data-testid=actions] button");
await page.getByTestId("actions").getByRole("button", { name: "Hold", exact: true }).click();
await page.waitForSelector("[data-testid=action-result]", { timeout: 20000 });
check(/Held · HELD/.test(await page.locator("[data-testid=action-result]").innerText()), `hold ${camId}: HELD`);

// 5. the auditor: nothing to press, and the server refuses a forced approve
await page.selectOption('select[aria-label="Act as (demo)"]', "PER-AUD");
await page.locator("header div.font-medium", { hasText: /^External Auditor$/ }).waitFor();
const pendingId = await openCharge("CLINIC-03 Jan 2026 cam_estimate: $4,387.50 matches the lease");
await page.waitForSelector("[data-testid=no-actions]", { timeout: 20000 });
check((await page.getByTestId("actions").getByRole("button", { name: "Approve", exact: true }).count()) === 0, `auditor is not offered Approve on ${pendingId}`);
await shot("auditor-no-approve", false);
const forced = await page.evaluate(
  async ([api, id]) => (await fetch(`${api}/api/exceptions/${id}/approve`, { method: "POST", credentials: "include" })).status,
  [API, pendingId],
);
check(forced === 403, `a forced approve as the auditor is refused (${forced})`);

// 6. the audit trail: chain verified, the refusal on record
await page.goto(BASE + "/audit", { waitUntil: "networkidle" });
await page.waitForSelector("[data-testid=chain-badge]");
check((await page.getAttribute("[data-testid=chain-badge]", "data-verified")) === "true", "audit chain verified");
await page.check("text=Denied attempts only");
await page.waitForSelector("text=Denied");
const denied = await page.locator("tbody tr").count();
check(denied >= 1, `audit trail shows ${denied} denied attempt(s)`);
check((await page.locator("tbody tr", { hasText: "PER-AUD" }).count()) >= 1, "the auditor's refused approve is a denied row");
await shot("audit-denied", false);
await page.uncheck("text=Denied attempts only");
await shot("audit");

await browser.close();
if (problems.length) {
  console.error(`\n${problems.length} problem(s):\n- ${problems.join("\n- ")}`);
  process.exit(1);
}
console.log("\nlive end to end: all checks passed");
