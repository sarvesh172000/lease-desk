// The live mirror gate (PLAN C5), two browser windows against the live API:
// approve an exception in window A; window B's queue and tiles refetch and
// change with no reload, because the backend mirrored the commit to
// SpacetimeDB (backend/app/work/live.py) and B's useLiveStatus() heard it.
//
//   LEASEDESK_DB_NAME=leasedesk_demo make demo-data          # fresh January
//   SPACETIME_DB=leasedesk-live SPACETIME_TOKEN=... SPACETIME_HOST=http://127.0.0.1:3100 \
//     (cd backend && python3 -m uvicorn app.main:app --port 8000) &
//   NEXT_PUBLIC_API_URL=http://localhost:8000 NEXT_PUBLIC_SPACETIME_URI=ws://127.0.0.1:3100 \
//     NEXT_PUBLIC_SPACETIME_DB=leasedesk-live npm run build && npx next start -p 3000 &
//   BASE_URL=http://localhost:3000 node scripts/live-mirror-e2e.mjs
//
// Mutates the database it runs against: run it on a fresh demo database.
// Not run in CI (needs Postgres, the API, SpacetimeDB and a browser).
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://localhost:3000";
const API = process.env.API_URL || "http://localhost:8000";
const EMAIL = process.env.LIVE_EMAIL || "dana.whitfield@northbaypt.example";
const PASSWORD = process.env.LIVE_PASSWORD || "demo";

const problems = [];
const check = (ok, what) => {
  console.log(`${ok ? "ok  " : "FAIL"} ${what}`);
  if (!ok) problems.push(what);
};

async function signedIn(browser) {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  const page = await ctx.newPage();
  page.on("pageerror", (e) => problems.push(`pageerror: ${e.message}`));
  await page.goto(BASE + "/login", { waitUntil: "networkidle" });
  await page.fill("#email", EMAIL);
  await page.fill("#password", PASSWORD);
  await page.getByRole("button", { name: "Sign in" }).click();
  await page.waitForSelector("[data-testid=exception-row]");
  return page;
}

const browser = await chromium.launch();
const a = await signedIn(browser);
const b = await signedIn(browser);

const rowsBefore = await b.locator("[data-testid=exception-row]").count();
const navigations = [];
b.on("framenavigated", (f) => f === b.mainFrame() && navigations.push(f.url()));
const refetched = b.waitForResponse((r) => r.url().startsWith(API + "/api/exceptions") && r.request().method() === "GET",
  { timeout: 10000 }).then(() => true, () => false);

// A approves the first open exception through the API, as its Approve button does.
const [id, status] = await a.evaluate(async (api) => {
  const list = await (await fetch(`${api}/api/exceptions`, { credentials: "include" })).json();
  const target = list[0].exception_id;
  const r = await fetch(`${api}/api/exceptions/${target}/approve`, { method: "POST", credentials: "include" });
  return [target, r.status];
}, API);
check(status === 200, `window A approved ${id} (${status})`);

check(await refetched, "window B refetched /api/exceptions on its own");
await b.waitForFunction((n) => document.querySelectorAll("[data-testid=exception-row]").length !== n, rowsBefore,
  { timeout: 10000 }).catch(() => undefined);
const rowsAfter = await b.locator("[data-testid=exception-row]").count();
check(rowsAfter !== rowsBefore, `window B's queue changed with no reload (${rowsBefore} -> ${rowsAfter} rows)`);
check(navigations.length === 0, "window B never navigated");

await browser.close();
if (problems.length) {
  console.error(`\n${problems.length} problem(s)`);
  process.exit(1);
}
console.log("\nlive mirror gate: ok");
