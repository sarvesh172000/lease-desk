// Round 8: walk the judge's path at 1280x800 through headless Chrome, timing each
// step, recording console errors, failed or 4xx/5xx requests and layout shifts,
// and saving a screenshot per step.
// usage: node r8-walk.mjs <base> <outDir> <theme> [reduced-motion:0|1] [suffix] [steps: comma list or all]
import { execSync, spawn } from "node:child_process";
import { mkdirSync, writeFileSync, mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const [BASE, OUT, THEME = "dark", REDUCED = "0", SUFFIX = "", STEPS = "all"] = process.argv.slice(2);
const API = process.env.API_URL || "http://localhost:8000";
const want = (n) => STEPS === "all" || STEPS.split(",").includes(n);
mkdirSync(OUT, { recursive: true });
const PORT = 9300 + Math.floor(Math.random() * 500);
const chrome = spawn("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", [
  "--headless=new", `--remote-debugging-port=${PORT}`, "--hide-scrollbars", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
  `--user-data-dir=${mkdtempSync(join(tmpdir(), "ldr8-"))}`, "--window-size=1280,800", "about:blank",
], { stdio: "ignore" });
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
let target;
for (let i = 0; i < 60 && !target; i++) {
  await sleep(200);
  try { target = (await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json()).find((t) => t.type === "page"); } catch {}
}
const ws = new WebSocket(target.webSocketDebuggerUrl);
await new Promise((r) => ws.addEventListener("open", r, { once: true }));
let id = 0; const pending = new Map();
const log = { console: [], network: [], steps: [] };
let current = "setup";
ws.addEventListener("message", (ev) => {
  const m = JSON.parse(ev.data);
  if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
  if (m.method === "Runtime.consoleAPICalled" && (m.params.type === "error" || m.params.type === "warning")) {
    log.console.push({ step: current, type: m.params.type, text: m.params.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 300) });
  }
  if (m.method === "Runtime.exceptionThrown") {
    log.console.push({ step: current, type: "exception", text: (m.params.exceptionDetails.exception?.description ?? m.params.exceptionDetails.text).slice(0, 1500) });
  }
  if (m.method === "Network.responseReceived" && m.params.response.status >= 400) {
    log.network.push({ step: current, status: m.params.response.status, url: m.params.response.url.replace(API, "").replace(BASE, "") });
  }
  if (m.method === "Network.loadingFailed" && !m.params.canceled) {
    log.network.push({ step: current, status: "failed", url: m.params.errorText });
  }
});
const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
const evalJs = async (expression) => (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result?.result?.value;
const shot = async (name) => {
  const s = await send("Page.captureScreenshot", { format: "png" });
  const f = join(OUT, `${String(log.steps.length).padStart(2, "0")}-${name}${SUFFIX}-${THEME}.png`);
  writeFileSync(f, Buffer.from(s.result.data, "base64"));
};
// poll until the page says it is ready for the next beat
const waitFor = async (js, timeout = 15000) => {
  const t0 = performance.now();
  while (performance.now() - t0 < timeout) {
    if (await evalJs(`!!(${js})`)) return performance.now() - t0;
    await sleep(100);
  }
  return null;
};
const q = (sel) => `document.querySelector(${JSON.stringify(sel)})`;
const clickSel = (sel) => evalJs(`(() => { const el = ${q(sel)}; if (!el) return false; el.click(); return true; })()`);
const clickText = (sel, text) => evalJs(`(() => { const el = [...document.querySelectorAll(${JSON.stringify(sel)})].find((e) => e.textContent.trim().includes(${JSON.stringify(text)})); if (!el) return false; el.click(); return true; })()`);
const pointerDown = (sel) => evalJs(`(() => { const el = ${q(sel)}; if (!el) return false; el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerType: "mouse" })); return true; })()`);
const cls = () => evalJs("window.__cls || 0");

/** One beat of the path: do the thing, wait until `ready`, note the time, screenshot. */
async function step(name, action, ready, { settle = 1200, timeout = 15000 } = {}) {
  if (!want(name)) return;
  current = name;
  await evalJs("window.__cls = 0; window.__shifts = []; window.__t0 = performance.now()");
  const t0 = performance.now();
  const did = await action();
  const readyMs = await waitFor(ready, timeout);
  const total = Math.round(performance.now() - t0);
  await sleep(settle);
  const shift = await cls();
  const url = await evalJs("location.pathname");
  const overflow = await evalJs("document.documentElement.scrollWidth - document.documentElement.clientWidth");
  const shifts = (await evalJs("JSON.stringify((window.__shifts || []).filter((s) => s.v >= 0.01))")) ?? "[]";
  log.steps.push({ name, did, readyMs: readyMs == null ? null : Math.round(readyMs), total, cls: Number(shift.toFixed(3)), url, overflow, shifts: JSON.parse(shifts) });
  if (overflow > 0) console.log(`   horizontal overflow ${overflow}px`);
  if (shift >= 0.03) console.log("   shifts:", shifts.slice(0, 400));
  console.log(`${name.padEnd(16)} ${readyMs == null ? "NOT READY" : Math.round(readyMs) + "ms"}  cls=${Number(shift).toFixed(3)}  ${url}${did ? "" : "  (action missed)"}`);
  await shot(name);
}

await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await send("Emulation.setDeviceMetricsOverride", { width: 1280, height: 800, deviceScaleFactor: 1, mobile: false });
if (REDUCED === "1") await send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
await send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: mkdtempSync(join(tmpdir(), "ldr8dl-")) });
await send("Page.addScriptToEvaluateOnNewDocument", {
  source: `window.__cls = 0; window.__shifts = []; try { new PerformanceObserver((l) => { for (const e of l.getEntries()) if (!e.hadRecentInput) { window.__cls += e.value; const who = (e.sources || []).slice(0, 3).map((s) => { const n = s.node; if (!n || !n.tagName) return "?"; const t = n.getAttribute && (n.getAttribute("data-testid") || n.getAttribute("aria-label")); return n.tagName.toLowerCase() + (t ? "[" + t + "]" : "") + (n.className && typeof n.className === "string" ? "." + n.className.split(" ").slice(0, 3).join(".") : ""); }); const moved = (e.sources || []).slice(0, 3).map((s) => Math.round((s.currentRect?.top ?? 0) - (s.previousRect?.top ?? 0))); window.__shifts.push({ v: Number(e.value.toFixed(3)), t: Math.round(e.startTime - (window.__t0 || 0)), who, moved }); } }).observe({ type: "layout-shift", buffered: true }); } catch {}`,
});
await send("Page.navigate", { url: BASE + "/login" }); await sleep(2000);
await evalJs(`localStorage.setItem("leasedesk-theme","${THEME}")`);
// a clean desk every run: whoever was signed in last time is signed out
await evalJs(`fetch("${API}/api/auth/logout",{method:"POST",credentials:"include"}).then(r=>r.status).catch(()=>0)`);

const pathStart = performance.now();
await step("welcome", async () => { const r = await send("Page.navigate", { url: BASE + "/welcome" }); if (r.result?.errorText) console.log("navigate:", r.result.errorText); await sleep(400); return !r.result?.errorText; }, `location.pathname === "/welcome" && ${q("main h1")} && document.body.innerText.includes("$")`, { settle: 3000 });
await step("login", () => clickSel('header a[href="/login"]'), q('[data-testid="personas"]'));
await step("today", () => clickText('[data-testid="personas"] button', process.env.PERSONA || "Priya"), `${q('[data-testid="tiles"]')} && (${q('[data-testid="hero-card"], [data-testid="ap-hero"], [data-testid="auditor-hero"]')} || document.body.innerText.includes("Nothing waits"))`, { settle: 2500 });
await step("money", () => clickSel('[data-testid="hero-card"] a[href^="/exceptions/"]'), `document.body.innerText.includes("LEASE SUPPORTS") && ${q("main img")}`, { settle: 2500 });
await step("investigate", () => clickText("button", "Run investigation"), `${q('[data-testid="balance-assertion"]')} && ${q('[data-testid="remeasurement-delta"]')}`, { settle: 2500, timeout: 30000 });
await step("why", () => clickText("button", "Why?"), q('[data-testid="why-answer"]'), { settle: 1500, timeout: 30000 });
await evalJs(`document.dispatchEvent(new KeyboardEvent("keydown",{key:"Escape",bubbles:true}))`); await sleep(600);
await step("evidence-pack", () => clickText("button", "Evidence pack"), `!document.body.innerText.includes("Building")`, { settle: 2500, timeout: 30000 });
await step("switch-dana", async () => { await pointerDown('button[aria-label^="Signed in as"]'); await sleep(500); return clickText('[role="menuitem"]', "Dana"); }, q('button[aria-label^="Signed in as Dana"]'), { settle: 2000 });
await step("dana-today", async () => { await clickSel('a[href="/"]'); return true; }, q('[data-testid="queue-table"] a[href^="/exceptions/"]'), { settle: 2000 });
// the January $4,820 hold, from her queue
const janHold = `[...document.querySelectorAll('[data-testid="queue-table"] a[href^="/exceptions/"]')].find((a) => a.closest("tr")?.textContent.includes("4,820.00"))`;
await step("jan-hold", () => evalJs(`(() => { const a = ${janHold}; if (!a) return false; a.click(); return true; })()`), `document.body.innerText.includes("LEASE SUPPORTS") && ${q("main img")}`, { settle: 2500 });
await step("uphold", async () => { await clickText('[data-testid="actions"] button', "Uphold hold"); await sleep(600); return clickSel('[data-testid="confirm-action"]'); }, q('[data-testid="action-result"]'), { settle: 2500, timeout: 20000 });
// nothing on the backend sweeps for disputes after an uphold yet; the demo prep runs the sweep by hand
if (process.env.DISPUTES_HOOK) { try { console.log("   disputes sweep:", execSync(process.env.DISPUTES_HOOK, { encoding: "utf8" }).trim().split("\n").pop()); } catch (e) { console.log("   disputes sweep failed", e.message); } }
await step("disputes", () => clickSel('a[href="/disputes"]'), q('[data-testid="disputes-table"] a[href^="/disputes/"]'), { settle: 2000 });
await step("dispute-letter", () => clickSel('[data-testid="disputes-table"] a[href^="/disputes/"]'), q('[data-testid="letter"]'), { settle: 2000 });
await step("audit", () => clickSel('a[href="/audit"]'), `${q('[data-testid="chain-banner"]')} && ${q('[data-testid="audit-row"]')}`, { settle: 3000 });
await step("month", () => clickSel('a[href="/month"]'), `${q('[data-testid="tiles"], [data-testid="batch-panel"], [data-testid="queue-table"]')}`, { settle: 2500 });
await step("leases", () => clickSel('a[href="/leases"]'), q('[data-testid="runway-row"]'), { settle: 3000 });
await step("lease-detail", () => evalJs(`(() => { const r = [...document.querySelectorAll('[data-testid="runway-row"]')].find((e) => e.textContent.includes("LEASE-01")); if (!r) return false; r.click(); return true; })()`), q('[data-testid="term-quote"]'), { settle: 3000 });
const pathMs = Math.round(performance.now() - pathStart);
const cold = async (name, path, ready) => {
  if (!want(name)) return;
  current = name;
  const t0 = performance.now();
  await send("Page.navigate", { url: BASE + path });
  const readyMs = await waitFor(ready, 20000);
  const nav = JSON.parse((await evalJs(`JSON.stringify((() => { const n = performance.getEntriesByType("navigation")[0]; return n ? { dcl: Math.round(n.domContentLoadedEventEnd), load: Math.round(n.loadEventEnd), ttfb: Math.round(n.responseStart) } : null; })())`)) ?? "null");
  const total = Math.round(performance.now() - t0);
  log.steps.push({ name, cold: true, readyMs: readyMs == null ? null : Math.round(readyMs), total, nav, url: path });
  console.log(`${name.padEnd(16)} ready ${readyMs == null ? "NOT" : Math.round(readyMs) + "ms"}  ttfb ${nav?.ttfb}ms dcl ${nav?.dcl}ms load ${nav?.load}ms`);
  await sleep(1500);
};
await send("Network.setCacheDisabled", { cacheDisabled: true });
await cold("cold-today", "/", `${q('[data-testid="tiles"]')} && (${q('[data-testid="hero-card"], [data-testid="ap-hero"], [data-testid="auditor-hero"]')} || document.body.innerText.includes("Nothing waits"))`);
await cold("cold-money", await evalJs(`(${q('[data-testid="queue-table"] a[href^="/exceptions/"]')} || {}).getAttribute?.("href") || "/exceptions"`), `document.body.innerText.includes("LEASE SUPPORTS") && ${q("main img")}`);

const report = { base: BASE, theme: THEME, reducedMotion: REDUCED === "1", pathMs, ...log };
writeFileSync(join(OUT, `walk${SUFFIX}-${THEME}.json`), JSON.stringify(report, null, 2));
console.log(`path ${(pathMs / 1000).toFixed(1)}s incl. settles · console ${log.console.length} · network ${log.network.length}`);
for (const c of log.console) console.log("  console", c.step, c.type, c.text.slice(0, 160));
for (const n of log.network) console.log("  network", n.step, n.status, n.url);
ws.close();
chrome.kill();
