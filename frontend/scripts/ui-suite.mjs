// The UI test plan (docs/UI_TEST_PLAN.md), case by case, in headless Chrome over
// the DevTools protocol: no dependency beyond an installed Chrome. Every case
// prints PASS or FAIL with what it saw; each step also collects console errors,
// uncaught exceptions, failed or 4xx/5xx requests and horizontal overflow, and
// saves a screenshot. Exits 1 if anything failed.
//
// usage: node scripts/ui-suite.mjs <base> <outDir>
//   MUTATE=1   also run the M cases (approvals): a fresh local desk only
//   ONLY=R08,R10   run just these cases (the sign-in they need still runs)
import { mkdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { launchChrome, sleep, watchProblems } from "./lib/chrome.mjs";

const [BASE = "http://localhost:3000", OUT = "out/ui"] = process.argv.slice(2);
const MUTATE = process.env.MUTATE === "1";
const ONLY = process.env.ONLY ? new Set(process.env.ONLY.split(",")) : null;
// Passwords are typed only into a local desk; elsewhere the demo picker signs in.
const LOCAL = /^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?$/.test(BASE);
if (MUTATE && !LOCAL) {
  console.error("MUTATE=1 approves and posts: run it against a fresh local desk only");
  process.exit(2);
}
mkdirSync(OUT, { recursive: true });

// --- Chrome over CDP -------------------------------------------------------------
const chrome = await launchChrome({ width: 1440, height: 900, prefix: "ldui-" });
const { send } = chrome;
let current = "setup";
const noise = { console: [], network: [] };
watchProblems(chrome, (e) => {
  if (e.kind === "console") {
    noise.console.push({ case: current, text: (e.type === "exception" ? "uncaught: " : "") + e.text.slice(0, 300) });
    return;
  }
  // signed out, /me answering 401 is the answer, not an error; an aborted load is navigation
  if (e.status === 401 && e.url.includes("/api/auth/me")) return;
  if (e.status === "failed" && /ERR_ABORTED/.test(e.url)) return;
  noise.network.push({ case: current, status: e.status, url: e.url.replace(BASE, "") });
});
const js = async (expression) => {
  const r = await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true });
  if (r.result?.exceptionDetails) throw new Error(r.result.exceptionDetails.exception?.description ?? r.result.exceptionDetails.text);
  return r.result?.result?.value;
};
const waitFor = async (expr, timeout = 15000) => {
  const t0 = Date.now();
  while (Date.now() - t0 < timeout) {
    try { if (await js(`!!(${expr})`)) return true; } catch {}
    await sleep(150);
  }
  return false;
};
const go = async (path) => { await send("Page.navigate", { url: BASE + path }); await sleep(600); };
const q = (sel) => `document.querySelector(${JSON.stringify(sel)})`;
const qa = (sel) => `[...document.querySelectorAll(${JSON.stringify(sel)})]`;
const text = () => js("document.body.innerText");
const has = (s) => `document.body.innerText.includes(${JSON.stringify(s)})`;
const click = (sel) => js(`(() => { const el = ${q(sel)}; if (!el) return false; el.click(); return true; })()`);
const clickText = (sel, t) => js(`(() => { const el = ${qa(sel)}.find((e) => e.textContent.trim().includes(${JSON.stringify(t)})); if (!el) return false; el.click(); return true; })()`);
const pointerDown = (sel) => js(`(() => { const el = ${q(sel)}; if (!el) return false; el.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerType: "mouse" })); return true; })()`);
const key = (k, extra = "") => js(`document.dispatchEvent(new KeyboardEvent("keydown", { key: ${JSON.stringify(k)}, bubbles: true ${extra} }))`);
// React reads the native setter; a plain .value = would be ignored
const type = (sel, value) => js(`(() => { const el = ${q(sel)}; if (!el) return false; const set = Object.getOwnPropertyDescriptor(el.constructor.prototype, "value").set; set.call(el, ${JSON.stringify(value)}); el.dispatchEvent(new Event("input", { bubbles: true })); return true; })()`);
const overflow = () => js("document.documentElement.scrollWidth - document.documentElement.clientWidth");
const viewport = (width, height, mobile = false) => send("Emulation.setDeviceMetricsOverride", { width, height, deviceScaleFactor: 1, mobile });
const api = (path, init = "{}") => js(`fetch(${JSON.stringify(path)}, Object.assign({ credentials: "include" }, ${init})).then(async (r) => ({ status: r.status, body: await r.text() }))`);

// --- cases ----------------------------------------------------------------------
const results = [];
let checks = [];
const check = (ok, what) => { checks.push({ ok: !!ok, what }); return !!ok; };

async function test(caseId, title, body, { allow = [] } = {}) {
  if (ONLY && !ONLY.has(caseId)) return;
  current = caseId;
  checks = [];
  const before = { c: noise.console.length, n: noise.network.length };
  let error = null;
  try { await body(); } catch (e) { error = e.message.split("\n")[0]; }
  await sleep(400);
  const ov = await overflow().catch(() => 0);
  if (ov > 0) check(false, `no horizontal scroll (${ov}px over)`);
  const consoleErrors = noise.console.slice(before.c);
  const badRequests = noise.network.slice(before.n).filter((n) => !allow.includes(n.status));
  if (consoleErrors.length) check(false, `console clean (${consoleErrors.length}: ${consoleErrors[0].text.slice(0, 120)})`);
  const seen = badRequests.slice(0, 3).map((n) => n.status + " " + n.url).join("; ");
  if (badRequests.length) check(false, `requests clean (${seen})`);
  if (error) check(false, `ran without error: ${error}`);
  const ok = checks.length > 0 && checks.every((c) => c.ok);
  results.push({ id: caseId, title, ok, checks });
  try {
    const s = await send("Page.captureScreenshot", { format: "png" });
    writeFileSync(join(OUT, `${caseId}.png`), Buffer.from(s.result.data, "base64"));
  } catch {}
  console.log(`${ok ? "PASS" : "FAIL"} ${caseId} ${title}`);
  for (const c of checks.filter((c) => !c.ok)) console.log(`       ✗ ${c.what}`);
}

/** What the API says is open: the count every list should agree with. */
const openExceptions = () => api("/api/exceptions").then((r) => JSON.parse(r.body).filter((e) => e.status !== "balanced").length);

async function signInAs(name) {
  // the persona menu switches in demo mode; from signed out, the login picker
  if (await js(`!!${q('button[aria-label^="Signed in as"]')}`)) {
    const mine = q('button[aria-label^="Signed in as ' + name + '"]');
    if (await js(`!!${mine}`)) return true;
    await pointerDown('button[aria-label^="Signed in as"]');
    await waitFor(`${qa('[role="menuitem"]')}.length > 0`, 5000);
    await clickText('[role="menuitem"]', name);
  } else {
    await go("/login");
    await waitFor(q('[data-testid="personas"] button'));
    await clickText('[data-testid="personas"] button', name);
  }
  return waitFor(q(`button[aria-label^="Signed in as ${name}"]`), 15000);
}

await send("Page.enable");
await send("Runtime.enable");
await send("Network.enable");
await viewport(1440, 900);
await go("/login");
await js(`fetch("/api/auth/logout", { method: "POST", credentials: "include" }).catch(() => 0)`);
await js(`localStorage.setItem("leasedesk-theme", "dark")`);

await test("R01", "Front door, signed out", async () => {
  await go("/");
  check(await waitFor(`location.pathname === "/welcome"`), "/ lands on /welcome");
  check(await waitFor(q("main h1")), "the hero renders");
  check(await waitFor(q('[data-testid="tech-strip"]')), "the sponsor strip renders");
  check(await js(`!!${q('[data-testid="proof-footer"]')}`), "the proof footer renders");
  check(await js(`!!${q('a[href="/login"]')}`), "a sign-in link");
});

await test("R02", "Deep link, signed out", async () => {
  await go("/exceptions/exc_18");
  check(await waitFor(`location.pathname === "/login" && location.search.includes("next=")`), "goes to /login?next=…");
}, { allow: [401] }); // the page's first data calls are what find out the session is gone

if (LOCAL) {
  await test("R03", "Sign-in form, wrong password", async () => {
    await go("/login");
    // the persona list comes from the API, so it is there once React owns the form
    await waitFor(q('[data-testid="personas"] button'));
    await type('input[type="email"]', "priya.raghunathan@northbaypt.example");
    await type('input[type="password"]', "not-the-password");
    await clickText("form button", "Sign in");
    check(await waitFor(has("Email or password is incorrect."), 8000), "says the email or password is incorrect");
    check(await js(`location.pathname === "/login"`), "stays on /login");
  }, { allow: [401] }); // a wrong password is a 401
}

await test("R04", "Demo sign-in", async () => {
  await go("/login");
  check(await waitFor(q('[data-testid="personas"] button')), "the persona list renders");
  const names = await js(`${qa('[data-testid="personas"] button')}.map((b) => b.innerText.split(String.fromCharCode(10))[0])`);
  check(names?.length >= 4, `four people to sign in as (${names?.join(", ")})`);
  await clickText('[data-testid="personas"] button', "Priya");
  check(await waitFor(`location.pathname === "/" && ${q('[data-testid="tiles"]')}`, 15000), "Priya lands on Today");
});

// the cases below need a session even when ONLY skipped R04
await go("/");
if (!(await waitFor(q('button[aria-label^="Signed in as"]'), 6000))) await signInAs("Priya");

await test("R05", "Shell", async () => {
  await go("/");
  await waitFor(q('nav[aria-label="Main"]'));
  const links = await js(`${qa('nav[aria-label="Main"] a')}.map((a) => a.getAttribute("href"))`);
  check(["/", "/exceptions", "/leases", "/audit"].every((h) => links?.includes(h)), `the rail has the screens (${links?.join(" ")})`);
  check(await waitFor(q('button[aria-label^="Signed in as Priya"]'), 10000), "the persona button names Priya");
  check(await js(`/live api/i.test((${q('[data-testid="data-source"]')} || {}).innerText || "")`), "data source is the live API");
});

await test("R06", "Today, controller", async () => {
  await go("/");
  check(await waitFor(q('[data-testid="tiles"]')), "tiles");
  check(await waitFor(q('[data-testid="hero-card"]')), "the hero card");
  check(await waitFor(`${qa('[data-testid="queue-table"] tbody tr')}.length >= 1`), "the queue has rows");
  const rows = await js(`${qa('[data-testid="queue-table"] tbody tr')}.length`);
  const open = await openExceptions();
  check(rows === open, `the queue lists every open exception (${rows} of ${open})`);
});

await test("R07", "Exceptions list", async () => {
  await go("/exceptions");
  const open = await openExceptions();
  check(await waitFor(`${qa("main tbody tr")}.length === ${open}`), `one row per open exception (${open})`);
  await js(`${qa("main tbody tr")}[0].click()`);
  check(await waitFor(`location.pathname.startsWith("/exceptions/exc_")`), "a row opens its exception");
});

await test("R08", "January hold", async () => {
  await go("/exceptions/exc_6");
  check(await waitFor(has("LEASE SUPPORTS") || has("Lease supports")), "the header figures");
  check(await waitFor(`${qa('[data-testid="citation-box"]')}.length >= 1`, 20000), "the invoice line is boxed");
  check(await js(`!!${q('[role="img"][aria-label="Confidence 56%"]')}`), "confidence ring reads 56%");
  check(!(await js(`!!${q('[role="img"][aria-label="Confidence 0%"]')}`)), "never a 0% ring");
  for (const tab of ["Evidence", "Sources", "Investigation"]) {
    // Radix tabs switch on pointer-down, not click
    await js(`(() => { const t = ${qa('[role="tab"]')}.find((e) => e.textContent.includes(${JSON.stringify(tab)})); if (!t) return false; t.dispatchEvent(new PointerEvent("pointerdown", { bubbles: true, button: 0, pointerType: "mouse" })); t.dispatchEvent(new MouseEvent("mousedown", { bubbles: true, button: 0 })); return true; })()`);
    check(await waitFor(`(${qa('[role="tab"]')}.find((t) => t.textContent.includes(${JSON.stringify(tab)})) || {}).getAttribute?.("data-state") === "active"`, 4000), `the ${tab} tab opens`);
  }
});

await test("R09", "Why?", async () => {
  await go("/exceptions/exc_6");
  await waitFor(has("LEASE SUPPORTS") || has("Lease supports"));
  await clickText("button", "Why?");
  check(await waitFor(q('[data-testid="why-answer"]'), 30000), "the drawer answers");
  const words = await js(`(${q('[data-testid="why-answer"]')} || {}).innerText || ""`);
  check(words.length > 40, `in words (${words.slice(0, 80)}…)`);
  await key("Escape");
});

await test("R10", "July hold", async () => {
  await go("/exceptions/exc_18");
  check(await waitFor(has("LEASE SUPPORTS") || has("Lease supports")), "the header figures");
  const inv = await waitFor(has("Explains the variance"), 10000);
  if (inv) {
    check(await waitFor(q('[data-testid="balance-assertion"]'), 10000), "the balance seal on the entries");
    check(await js(`/LEASE-01 v2/.test(document.body.innerText)`), "the approval card names LEASE-01 v2");
    check(await js(`!!${qa('a[href="/leases/LEASE-01"]')}.find((a) => /v2/.test(a.innerText))`), "and links the lease");
  } else {
    check(await js(`!!${qa("button")}.find((b) => b.textContent.includes("Run investigation"))`), "not yet investigated: offers Run investigation");
  }
});

await test("R11", "Leases", async () => {
  await go("/leases");
  check(await waitFor(`${qa('[data-testid="runway-row"]')}.length >= 5`), "five runway rows");
  const v2 = await api("/api/leases/LEASE-01/versions").then((r) => JSON.parse(r.body).length > 1);
  if (v2) check(await js(`!!${q('[data-testid="runway-ghost"]')}`), "LEASE-01 shows the newer version's ghost");
});

await test("R12", "Lease detail", async () => {
  await go("/leases/LEASE-01");
  check(await waitFor(`${qa('[data-testid="term-row"]')}.length >= 10`, 20000), "the terms table");
  check(await waitFor(q('[data-testid="term-quote"]')), "a term's quote");
  const versions = await js(`${qa('ol[aria-label="Versions"] li')}.length`);
  check(versions >= 1, `versions listed (${versions})`);
  check(await waitFor(q('[data-testid="schedule-chart"]'), 15000), "the schedule chart");
});

await test("R13", "Month, Obligations, Disputes, Policies, Questions", async () => {
  const screens = [
    ["/month", `${q('[data-testid="tiles"]')} || ${q('[data-testid="batch-panel"]')}`],
    ["/obligations", `${q('[data-testid="obligations-river"]')} || ${has("No deadlines")} || ${has("Nothing")}`],
    ["/disputes", `${q('[data-testid="disputes-table"]')} || ${has("No disputes")} || ${has("Nothing")}`],
    ["/policies", `${q('[data-testid="policy-list"]')} || ${q('[data-testid="onboard"]')}`],
    ["/questions", `${q('[data-testid="questions"]')} || ${q('[data-testid="questions-empty"]')}`],
  ];
  for (const [path, ready] of screens) {
    await go(path);
    const ok = await waitFor(ready, 15000);
    const broken = await js(`/Could not load|Something went wrong/.test(document.body.innerText)`);
    check(ok && !broken, `${path} renders${broken ? " (error state)" : ""}`);
  }
});

await test("R14", "Policy detail", async () => {
  await go("/policies");
  await waitFor(`${q('[data-testid="policy-list"]')} || ${q('[data-testid="onboard"]')}`);
  const href = await js(`(${q('a[href^="/policies/"]')} || {}).getAttribute?.("href") || null`);
  if (!href) { check(true, "no policies yet: nothing to open"); return; }
  await go(href);
  check(await waitFor(q('[data-testid="policy-title"]')), "the policy opens");
  check(await waitFor(q('[data-testid="rule-words"]')), "its rule in words");
});

await test("R15", "Audit", async () => {
  await go("/audit");
  check(await waitFor(q('[data-testid="chain-banner"]'), 20000), "the chain banner");
  check(await waitFor(`/verified/i.test((${q('[data-testid="chain-banner"]')} || {}).innerText || "")`, 20000), "says verified");
  check(await waitFor(`${qa('[data-testid="audit-row"]')}.length > 0`), "rows");
  await js(`${qa('[data-testid="audit-row"]')}[0].click()`);
  check(await waitFor(q('[data-testid="event-detail"]'), 5000), "a row opens its detail");
  await key("Escape");
  if (await click('[data-testid="simulate-toggle"]')) {
    check(await waitFor(`/broken|break|tamper/i.test((${q('[data-testid="chain-banner"]')} || {}).innerText || "") || ${q('[data-testid="simulation-label"]')}`, 5000), "the simulation shows a break");
    await click('[data-testid="simulate-toggle"]');
    check(await waitFor(`/verified/i.test((${q('[data-testid="chain-banner"]')} || {}).innerText || "")`, 5000), "and restores");
  }
});

await test("R16", "Command palette", async () => {
  await go("/");
  await waitFor(q('[data-testid="tiles"]'));
  await key("k", ", metaKey: true");
  check(await waitFor(q("[cmdk-input]"), 4000), "⌘K opens the palette");
  // the leases load when the palette opens; a person reads the list before typing
  await waitFor(`${qa("[cmdk-item]")}.some((i) => i.textContent.includes("LEASE-"))`, 10000);
  await type("[cmdk-input]", "LEASE-01");
  check(await waitFor(`${qa("[cmdk-item]")}.some((i) => i.textContent.includes("LEASE-01"))`, 4000), "finds LEASE-01");
  await js(`${qa("[cmdk-item]")}.find((i) => i.textContent.includes("LEASE-01")).click()`);
  check(await waitFor(`location.pathname.startsWith("/leases/LEASE-01") || location.pathname.startsWith("/exceptions/")`, 6000), "and goes there");
});

await test("R17", "Theme", async () => {
  await go("/");
  await waitFor(q('[data-testid="tiles"]'));
  const before = await js("document.documentElement.dataset.theme || document.documentElement.className");
  check(await click('button[aria-label^="Switch to"]'), "the toggle is there");
  await sleep(500);
  const after = await js("document.documentElement.dataset.theme || document.documentElement.className");
  check(before !== after, `the theme changes (${before} → ${after})`);
  check(await js(`!!${q('[data-testid="tiles"]')}`), "the page keeps rendering");
  await click('button[aria-label^="Switch to"]');
});

await test("R18", "Roles", async () => {
  check(await signInAs("Dana"), "switch to Dana");
  await go("/");
  check(await waitFor(q('[data-testid="queue-table"]'), 15000), "Dana has a queue");
  check(await signInAs("Marcus"), "switch to Marcus");
  await go("/");
  check(await waitFor(q('[data-testid="ap-hero"]'), 15000), "Marcus sees the AP view");
  check(await signInAs("External Auditor"), "switch to the auditor");
  await go("/");
  check(await waitFor(q('[data-testid="auditor-hero"]'), 15000), "the auditor sees the auditor view");
  await go("/exceptions/exc_18");
  check(await waitFor(q('[data-testid="no-actions"]'), 15000), "no action buttons for the auditor on the July hold");
  check(await signInAs("Priya"), "back to Priya");
});

await test("R19", "Not found", async () => {
  await go("/no-such-page");
  check(await waitFor(has("No such page"), 8000), "says No such page");
}, { allow: [404] }); // the 404 is the page under test

await test("R20", "Phone width (375 px)", async () => {
  await viewport(375, 812, true);
  for (const path of ["/", "/exceptions/exc_6", "/leases"]) {
    await go(path);
    await sleep(2500);
    const ov = await overflow();
    check(ov <= 0, `${path} has no horizontal scroll (${ov}px)`);
  }
  await js(`fetch("/api/auth/logout", { method: "POST", credentials: "include" })`);
  for (const path of ["/welcome", "/login"]) {
    await go(path);
    await sleep(2500);
    const ov = await overflow();
    check(ov <= 0, `${path} has no horizontal scroll (${ov}px)`);
  }
  await viewport(1440, 900);
  await signInAs("Priya");
}, { allow: [401] }); // it signs out halfway, and the open page's last calls answer 401

// --- mutating cases: a fresh local desk only ----------------------------------------
if (MUTATE) {
  await test("M01", "Run investigation on the July hold", async () => {
    await signInAs("Priya");
    await go("/exceptions/exc_18");
    await waitFor(has("LEASE SUPPORTS") || has("Lease supports"));
    check(await clickText("button", "Run investigation"), "Run investigation is offered");
    check(await waitFor(q('[data-testid="balance-assertion"]'), 60000), "the entries arrive with the balance seal");
    check(await waitFor(has("443,255.70"), 10000), "liability +$443,255.70");
    check(await waitFor(`/They post when a controller approves/.test(document.body.innerText)`, 10000), "the approval card says it waits on the controller");
  });

  await test("M02", "Approve the lease change", async () => {
    await go("/leases/LEASE-01");
    check(await waitFor(q('[data-testid="confirm-version"]'), 15000), "v2 offers Confirm to the controller");
    await click('[data-testid="confirm-version"]');
    if (await waitFor(q('[data-testid="confirm-action"]'), 3000)) await click('[data-testid="confirm-action"]');
    check(await waitFor(`!${q('[data-testid="confirm-version"]')}`, 15000), "v2 is confirmed");
    await go("/exceptions/exc_18");
    check(await waitFor(`/the gateway posted the 4 balanced entries/.test(document.body.innerText)`, 15000), "the July page says the gateway posted");
  });

  await test("M03", "Uphold a January hold as Dana", async () => {
    check(await signInAs("Dana"), "switch to Dana");
    await go("/exceptions/exc_6");
    await waitFor(q('[data-testid="actions"] button'), 15000);
    check(await clickText('[data-testid="actions"] button', "Uphold hold"), "Uphold hold is offered");
    check(await waitFor(q('[data-testid="confirm-action"]'), 4000), "asks to confirm");
    await click('[data-testid="confirm-action"]');
    check(await waitFor(q('[data-testid="action-result"]'), 20000), "shows the result");
  });

  await test("M04", "Pay as billed needs a reason", async () => {
    check(await signInAs("Priya"), "switch to Priya");
    await go("/exceptions/exc_7");
    await waitFor(q('[data-testid="pay-as-billed"]'), 15000);
    check(await click('[data-testid="pay-as-billed"]'), "Pay as billed is offered");
    check(await waitFor(q('[data-testid="pay-as-billed-form"]'), 4000), "asks for a reason");
    check(await js(`(${q('[data-testid="confirm-action"]')} || {}).disabled === true`), "will not submit empty");
    await key("Escape");
  });

  await test("M05", "Auditor cannot approve", async () => {
    check(await signInAs("External Auditor"), "switch to the auditor");
    const r = await api("/api/exceptions/exc_9/approve", `{ method: "POST", headers: { "Content-Type": "application/json" }, body: "{}" }`);
    check(r.status === 403, `a forced approve is refused (${r.status})`);
    await go("/audit");
    check(await waitFor(`${qa('[data-testid="audit-row"]')}.some((r) => /PER-AUD|Auditor/.test(r.innerText) && /refused|denied|✕|not allowed/i.test(r.innerText))`, 15000), "the audit trail shows the denied row");
    await signInAs("Priya");
  }, { allow: [403] }); // the refusal is the point

  await test("M06", "Connect chat", async () => {
    await go("/");
    await pointerDown('button[aria-label^="Signed in as"]');
    await waitFor(q('[data-testid="menu-connect-chat"]'), 4000);
    await click('[data-testid="menu-connect-chat"]');
    check(await waitFor(q('[data-testid="mint-code"]') + " || " + q('[data-testid="pairing-code"]'), 5000), "the dialog opens");
    await click('[data-testid="mint-code"]');
    check(await waitFor(`/^[A-Z0-9]{4}-[A-Z0-9]{4}$/.test(((${q('[data-testid="pairing-code"] .font-mono')} || {}).innerText || "").trim())`, 8000), "an 8-character code");
    check(await js(`!!${q('[data-testid="pairing-countdown"]')}`), "a countdown");
    await key("Escape");
  });
}

// --- report ---------------------------------------------------------------------
const failed = results.filter((r) => !r.ok);
writeFileSync(join(OUT, "ui-suite.json"), JSON.stringify({ base: BASE, mutate: MUTATE, results, noise }, null, 2));
console.log(`\n${results.length - failed.length}/${results.length} cases passed · ${OUT}/ui-suite.json`);
chrome.close();
process.exit(failed.length ? 1 : 0);
