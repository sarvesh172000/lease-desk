// Headless Chrome over the DevTools protocol, shared by the scripts that walk
// the app (rehearsal-walk.mjs, ui-suite.mjs): no dependency beyond an
// installed Chrome.
import { spawn } from "node:child_process";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";

export const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

/**
 * Start Chrome and attach to its page. Returns `send(method, params)` for
 * commands, `onEvent(fn)` for everything Chrome reports, and `close()`.
 * A port per process, so two walks at once don't collide.
 */
export async function launchChrome({ width = 1280, height = 800, prefix = "ldwalk-" } = {}) {
  const port = 9300 + (process.pid % 500);
  const proc = spawn(CHROME, [
    "--headless=new", `--remote-debugging-port=${port}`, "--hide-scrollbars", "--use-angle=swiftshader", "--enable-unsafe-swiftshader",
    `--user-data-dir=${mkdtempSync(join(tmpdir(), prefix))}`, `--window-size=${width},${height}`, "about:blank",
  ], { stdio: "ignore" });
  let target;
  for (let i = 0; i < 60 && !target; i++) {
    await sleep(200);
    try { target = (await (await fetch(`http://127.0.0.1:${port}/json/list`)).json()).find((t) => t.type === "page"); } catch {}
  }
  if (!target) { proc.kill(); throw new Error("Chrome did not start"); }
  const ws = new WebSocket(target.webSocketDebuggerUrl);
  await new Promise((r) => ws.addEventListener("open", r, { once: true }));
  let id = 0;
  const pending = new Map();
  const listeners = [];
  ws.addEventListener("message", (ev) => {
    const m = JSON.parse(ev.data);
    if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); return; }
    for (const fn of listeners) fn(m);
  });
  const send = (method, params = {}) => new Promise((r) => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({ id: i, method, params })); });
  return {
    send,
    onEvent: (fn) => listeners.push(fn),
    close: () => { ws.close(); proc.kill(); },
  };
}

/**
 * Report what goes wrong on the page: console errors (and warnings when asked),
 * uncaught exceptions, responses of 400 and above, and requests that failed.
 * `report` gets { kind: "console" | "network", type?, text?, status?, url? }.
 */
export function watchProblems(chrome, report, { warnings = false } = {}) {
  chrome.onEvent((m) => {
    const p = m.params;
    if (m.method === "Runtime.consoleAPICalled" && (p.type === "error" || (warnings && p.type === "warning"))) {
      report({ kind: "console", type: p.type, text: p.args.map((a) => a.value ?? a.description ?? "").join(" ").slice(0, 300) });
    } else if (m.method === "Runtime.exceptionThrown") {
      report({ kind: "console", type: "exception", text: (p.exceptionDetails.exception?.description ?? p.exceptionDetails.text).slice(0, 1500) });
    } else if (m.method === "Network.responseReceived" && p.response.status >= 400) {
      report({ kind: "network", status: p.response.status, url: p.response.url });
    } else if (m.method === "Network.loadingFailed" && !p.canceled) {
      report({ kind: "network", status: "failed", url: p.errorText });
    }
  });
}
