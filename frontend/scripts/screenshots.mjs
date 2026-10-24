// Screenshot the dashboard and the money screen at projector width.
//
//   npm run build && npx next start -p 3011 &
//   BASE_URL=http://localhost:3011 npm run screenshots
//
// Uses the preinstalled Playwright Chromium (`require('playwright')`).
import { mkdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const { chromium } = require("playwright");

const BASE = process.env.BASE_URL || "http://localhost:3000";
const OUT = join(dirname(fileURLToPath(import.meta.url)), "..", "docs", "screenshots");
mkdirSync(OUT, { recursive: true });

const shots = [
  { name: "dashboard", path: "/", wait: "text=Latest activity", full: true },
  { name: "leases", path: "/leases", wait: "text=LEASE-05", full: true },
  {
    name: "money-screen",
    path: "/exceptions/exc_01_jul_amendment",
    wait: "[data-testid=citation-box] >> nth=1",
    full: true,
    run: async (page) => {
      await page.getByRole("button", { name: "Run investigation" }).click();
      await page.waitForSelector('[data-stage="complete"][data-done="true"]', { timeout: 15000 });
    },
  },
  { name: "money-screen-cam", path: "/exceptions/exc_01_jan_cam", wait: "[data-testid=citation-box] >> nth=1", full: true },
  { name: "audit", path: "/audit", wait: "[data-testid=chain-badge]", full: true },
  { name: "lease-detail", path: "/leases/LEASE-01", wait: "text=Liability close", full: false },
];

const browser = await chromium.launch();
const page = await browser.newPage({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 1 });
page.on("pageerror", (e) => console.error("pageerror:", e.message));
page.on("console", (m) => m.type() === "error" && console.error("console:", m.text()));
for (const s of shots) {
  await page.goto(BASE + s.path, { waitUntil: "networkidle" });
  await page.waitForSelector(s.wait, { timeout: 20000 });
  if (s.run) await s.run(page);
  // let pdf.js finish painting, then park at the top so the sticky header sits there
  await page.waitForFunction(() => Array.from(document.querySelectorAll("canvas")).every((c) => c.width > 0), null, { timeout: 15000 });
  await page.evaluate(() => window.scrollTo(0, 0));
  await page.waitForTimeout(600);
  const file = join(OUT, `${s.name}.png`);
  await page.screenshot({ path: file, fullPage: s.full });
  console.log("saved", file);
}
await browser.close();
