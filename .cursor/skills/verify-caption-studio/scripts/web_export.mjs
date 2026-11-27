#!/usr/bin/env node
// Drive the packaged Caption Studio UI in headless Chromium over raw CDP (no extra deps):
// node web_export.mjs <url> <srt|vtt|ass> <evidenceDir> <chromeProfileDir>
// Clicks the toolbar export button (inside [aria-label="자막 내보내기"]) and waits for the download.
import { spawn } from "node:child_process";
import { mkdirSync, readdirSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const [url, fmt, evidence, profile] = process.argv.slice(2);
const label = { srt: "SRT 내보내기", vtt: "VTT", ass: "ASS" }[fmt];
if (!label) throw new Error(`unknown format ${fmt}`);
const downloadDir = join(evidence, "web-download");
mkdirSync(downloadDir, { recursive: true });
mkdirSync(profile, { recursive: true });

const chrome = spawn(process.env.CHROMIUM ?? "chromium", [
  "--headless=new", "--no-sandbox", "--disable-gpu", "--no-first-run",
  `--user-data-dir=${profile}`, "--remote-debugging-port=0", "about:blank",
], { stdio: ["ignore", "ignore", "pipe"] });
writeFileSync(join(profile, "..", "chrome.pid"), String(chrome.pid));
const fail = (message) => { console.error(`web-export FAIL: ${message}`); chrome.kill(); process.exit(1); };
setTimeout(() => fail("timeout"), 45_000).unref();

const wsUrl = await new Promise((resolve) => {
  let buffer = "";
  chrome.stderr.on("data", (chunk) => {
    buffer += chunk;
    const match = buffer.match(/DevTools listening on (ws:\/\/\S+)/);
    if (match) resolve(match[1]);
  });
});
const ws = new WebSocket(wsUrl);
await new Promise((resolve) => ws.addEventListener("open", resolve, { once: true }));
let nextId = 0;
const pending = new Map();
const listeners = [];
ws.addEventListener("message", ({ data }) => {
  const msg = JSON.parse(data);
  if (msg.id && pending.has(msg.id)) {
    const { resolve, reject } = pending.get(msg.id);
    pending.delete(msg.id);
    msg.error ? reject(new Error(msg.error.message)) : resolve(msg.result);
  } else listeners.forEach((fn) => fn(msg));
});
const send = (method, params = {}, sessionId) => new Promise((resolve, reject) => {
  const id = ++nextId;
  pending.set(id, { resolve, reject });
  ws.send(JSON.stringify({ id, method, params, sessionId }));
});
const waitFor = (pred) => new Promise((resolve) => listeners.push((m) => pred(m) && resolve(m)));

await send("Browser.setDownloadBehavior", { behavior: "allow", downloadPath: downloadDir, eventsEnabled: true });
const { targetId } = await send("Target.createTarget", { url: "about:blank" });
const { sessionId } = await send("Target.attachToTarget", { targetId, flatten: true });
await send("Page.enable", {}, sessionId);
await send("Emulation.setDeviceMetricsOverride", { width: 1600, height: 900, deviceScaleFactor: 1, mobile: false }, sessionId);
const loaded = waitFor((m) => m.method === "Page.loadEventFired" && m.sessionId === sessionId);
await send("Page.navigate", { url }, sessionId);
await loaded;

const evaluate = async (expression) =>
  (await send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true }, sessionId)).result.value;
let found = false;
for (let i = 0; i < 50 && !found; i++) {
  found = await evaluate(`[...document.querySelectorAll('[aria-label="자막 내보내기"] button')].some(b => b.textContent.trim() === ${JSON.stringify(label)})`);
  if (!found) await new Promise((r) => setTimeout(r, 200));
}
if (!found) fail(`export button "${label}" not found`);
const shot = await send("Page.captureScreenshot", { format: "png" }, sessionId);
writeFileSync(join(evidence, "web-toolbar.png"), Buffer.from(shot.data, "base64"));

const done = waitFor((m) => m.method === "Browser.downloadProgress" && m.params.state === "completed");
const clicked = await evaluate(`(() => { const b = [...document.querySelectorAll('[aria-label="자막 내보내기"] button')].find(b => b.textContent.trim() === ${JSON.stringify(label)}); b.click(); return true; })()`);
if (!clicked) fail("click failed");
await done;
const files = readdirSync(downloadDir).filter((name) => name.endsWith(`.${fmt}`));
if (!files.length) fail(`no .${fmt} file in ${downloadDir}`);
console.log(`web-export OK: ${join(downloadDir, files[0])}`);
ws.close();
chrome.kill();
process.exit(0);
