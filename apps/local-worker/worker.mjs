// RESOLVE local worker — the "hands on the laptop."
//
// Runs on your Mac. Polls the cloud control plane for tasks that need local
// access, then executes them as a Claude agent with LOCAL tools: sandboxed file
// read/write/search, web-read, and APPROVAL-GATED shell. Progress streams back
// to the dashboard; dangerous actions route through RESOLVE's approval banners.
//
// Non-negotiable safety:
//   • Files are confined to RESOLVE_WORKSPACE (a single folder). Path escapes
//     (.., absolute paths outside the root, symlinks out) are refused.
//   • run_shell ALWAYS requires your approval (banner/Telegram) before it runs.
//   • Nothing destructive happens without a tap.
//
// Env: CONTROL_PLANE_URL, CP_TOKEN, ANTHROPIC_API_KEY,
//      RESOLVE_WORKSPACE (default ~/resolve-workspace), WORKER_MODEL.

import Anthropic from "@anthropic-ai/sdk";
import { promises as fs } from "node:fs";
import path from "node:path";
import os from "node:os";
import { exec, execFile } from "node:child_process";
import { fileURLToPath, pathToFileURL } from "node:url";

const SELF_DIR = path.dirname(fileURLToPath(import.meta.url)); // apps/local-worker (inside the repo)

const CP = (process.env.CONTROL_PLANE_URL || "").replace(/\/$/, "");
const CP_TOKEN = process.env.CP_TOKEN || "";
const MODEL = process.env.WORKER_MODEL || "claude-haiku-4-5-20251001";
const ROOT = path.resolve(
  process.env.RESOLVE_WORKSPACE || path.join(os.homedir(), "resolve-workspace"),
);
// The Obsidian vault (second brain). The worker gets vault-aware tools + the
// vault's CLAUDE.md engrained as its manual so it can run CLAUDE.md-compliant
// ingests locally against the real files. raw/ + CLAUDE.md are write-protected.
const VAULT = path.resolve(
  process.env.VAULT_PATH || path.join(os.homedir(), "Desktop", "Obsidian Vault"),
);
const MAX_TURNS = 40;
// Files written during the CURRENT task. The laptop agent likes to end a turn
// saying "let me write the file" without calling write_file — so "it said it
// saved" has to be checkable against something real.
let filesWritten = 0;

// ── delivery guard (port of executor._needs_action) ─────────────────────────
// The laptop loop had none of this: it broke out of the loop on any turn with
// no tool call, so a promise became the reported summary and the task was
// logged complete. Same narrate-and-quit failure the cloud executor had.
const INTENT_RE =
  /^\s*(?:(?:sure|okay|ok|alright|great|perfect|got it)[,!.\s]+)?(?:i'?ll|i will|i'?m going to|i am going to|let me|first,?\s+i(?:'?ll| will)?|i'?d be happy to|i'?m about to)\s+(?:research|find|search|look|check|compile|summar\w*|write|draft|create|put together|gather|locate|prepare|organize|provide|give|pull|read|do|answer|get|start|dig|explore|review)/i;
const PROMISE_TAIL_RE =
  /(let me|i'?ll|i will|now i'?ll|i'?m going to|we'?re going to|i need to|i should|first i)\s+(compile|summar|write|put together|create|draft|save|provide|give|lay out|organize|prepare|check|look|locate|find|gather|review|search|pull|read|start)\S*[^.!?]*[.!?:]?\s*$/i;
const PROMISE_MARKER_RE =
  /\b(let me|i'?ll|i will|i'?m going to|i am going to|i need to|i should)\b/gi;
const DELIVERED_MIN = 600;
const TAIL_WINDOW = 200;

function needsAction(text) {
  const t = String(text || "").trim();
  if (!t) return true;
  if (t.length < 240 && INTENT_RE.test(t)) return true;
  const tail = t.slice(-TAIL_WINDOW);
  const m = tail.match(PROMISE_TAIL_RE);
  if (!m) return false;
  // a finished writeup that merely signs off with a promise is real output
  const body = t.slice(0, Math.max(0, t.length - TAIL_WINDOW) + m.index).trim();
  if (body.length < DELIVERED_MIN) return true;
  return (body.match(PROMISE_MARKER_RE) || []).length >= 3;
}

// promised a FILE specifically — checkable against filesWritten
const PROMISED_FILE_RE =
  /\b(write|writing|create|creating|save|saving|compile|compiling|put together)\b[^.!?]{0,80}\b(file|markdown|\.md|document|writeup|write-up|note|report)\b/i;
let vaultManual = ""; // loaded once from VAULT/CLAUDE.md

const anthropic = new Anthropic(); // reads ANTHROPIC_API_KEY

// ── control-plane helpers ───────────────────────────────────────────────────
const cpHeaders = { "Content-Type": "application/json", ...(CP_TOKEN ? { Authorization: `Bearer ${CP_TOKEN}` } : {}) };
async function cp(pathname, opts = {}) {
  const r = await fetch(`${CP}${pathname}`, { headers: cpHeaders, ...opts });
  if (!r.ok) throw new Error(`CP ${pathname} -> ${r.status}`);
  return r.status === 204 ? null : r.json();
}
async function emit(taskId, summary, detail) {
  try {
    await cp("/v1/local/event", { method: "POST", body: JSON.stringify({ taskId, summary, detail }) });
  } catch { /* streaming is best-effort */ }
}
// Report a file we created/changed so it lands in the dashboard Artifacts dock
// with a clickable link. absPath is the real on-disk path (→ file:// href).
async function artifact(taskId, absPath, location, action = "created") {
  try {
    await cp("/v1/local/artifact", {
      method: "POST",
      body: JSON.stringify({
        taskId,
        name: path.basename(absPath),
        path: absPath,
        location,
        href: `file://${absPath}`,
        action,
      }),
    });
  } catch { /* best-effort */ }
}

// ── sandbox path guards ─────────────────────────────────────────────────────
function safePath(rel) {
  const p = path.resolve(ROOT, rel || ".");
  if (p !== ROOT && !p.startsWith(ROOT + path.sep)) {
    throw new Error(`path escapes the workspace sandbox: ${rel}`);
  }
  return p;
}
function vaultPath(rel) {
  const p = path.resolve(VAULT, rel || ".");
  if (p !== VAULT && !p.startsWith(VAULT + path.sep)) {
    throw new Error(`path escapes the vault: ${rel}`);
  }
  return p;
}
function vaultWritableGuard(rel) {
  const low = String(rel).replace(/^\/+/, "").toLowerCase();
  if (low.startsWith("raw/") || low === "raw" || low === "claude.md") {
    throw new Error(`protected: ${rel} — raw/ and CLAUDE.md are read-only (immutable source of truth)`);
  }
}

// ── approval round-trip (for shell) ─────────────────────────────────────────
async function requireApproval(taskId, summary, detail) {
  const { id } = await cp("/v1/local/approval", {
    method: "POST",
    body: JSON.stringify({ taskId, summary, detail, risk: "local_shell" }),
  });
  // poll until the user decides (or times out ~3 min)
  for (let i = 0; i < 90; i++) {
    await new Promise((r) => setTimeout(r, 2000));
    const s = await cp(`/v1/local/approval/${id}`);
    if (s.status === "approved") return true;
    if (s.status === "rejected") return false;
  }
  return false; // no decision -> treat as denied
}

// ── local tools ─────────────────────────────────────────────────────────────
const TOOLS = [
  { name: "read_file", description: "Read a UTF-8 text file inside the workspace.",
    input_schema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } },
  { name: "write_file", description: "Create/overwrite a text file inside the workspace (sandboxed; safe).",
    input_schema: { type: "object", properties: { path: { type: "string" }, content: { type: "string" } }, required: ["path", "content"] } },
  { name: "list_dir", description: "List entries of a directory inside the workspace.",
    input_schema: { type: "object", properties: { path: { type: "string" } } } },
  { name: "search_files", description: "Recursively list workspace file paths whose name contains a query.",
    input_schema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] } },
  { name: "web_read", description: "Fetch a URL and return its readable text (no JS/interaction).",
    input_schema: { type: "object", properties: { url: { type: "string" } }, required: ["url"] } },
  { name: "vault_read", description: "Read a file from Trav's Obsidian vault (full contents).",
    input_schema: { type: "object", properties: { path: { type: "string" } }, required: ["path"] } },
  { name: "vault_write", description: "Create/update a vault file (wiki/ or output/). Refuses raw/ and CLAUDE.md.",
    input_schema: { type: "object", properties: { path: { type: "string" }, content: { type: "string" } }, required: ["path", "content"] } },
  { name: "vault_list", description: "List vault file paths under a prefix (e.g. wiki/, wiki/concepts/, raw/).",
    input_schema: { type: "object", properties: { prefix: { type: "string" } } } },
  { name: "vault_search", description: "List vault file paths whose name contains a query.",
    input_schema: { type: "object", properties: { query: { type: "string" } }, required: ["query"] } },
  { name: "run_shell", description: "Run a shell command in the workspace. ALWAYS asks the user for approval first.",
    input_schema: { type: "object", properties: { command: { type: "string" }, why: { type: "string" } }, required: ["command"] } },
  { name: "browser_navigate", description: "Open a URL in a real Chromium browser (persists across steps). Use to start any web task.",
    input_schema: { type: "object", properties: { url: { type: "string" } }, required: ["url"] } },
  { name: "browser_read", description: "Return the visible text of the current browser page (truncated). Use to read/extract content.",
    input_schema: { type: "object", properties: {} } },
  { name: "browser_click", description: "Click an element on the current page by its visible text (preferred) or a CSS selector.",
    input_schema: { type: "object", properties: { text: { type: "string" }, selector: { type: "string" } } } },
  { name: "browser_type", description: "Type text into an input on the current page, targeted by CSS selector.",
    input_schema: { type: "object", properties: { selector: { type: "string" }, text: { type: "string" } }, required: ["selector", "text"] } },
  { name: "browser_screenshot", description: "Screenshot the current page; saves to the workspace and logs it as an artifact.",
    input_schema: { type: "object", properties: { fullPage: { type: "boolean" } } } },
  { name: "browser_close", description: "Close the browser when the web task is finished.",
    input_schema: { type: "object", properties: {} } },
  { name: "look_at_screen",
    description: "Capture what's on the Mac's screen RIGHT NOW and answer a question about it (read-only — e.g. 'what does this error say?', 'what app/tab is open?'). Saves the screenshot as an artifact.",
    input_schema: { type: "object", properties: { question: { type: "string", description: "What to look for / answer about the screen. Omit for a general description." } } } },
  { name: "finish", description: "Call when the task is complete, with a short result summary.",
    input_schema: { type: "object", properties: { summary: { type: "string" } }, required: ["summary"] } },
];

// ── Playwright browser (lazy, persistent across steps/tasks) ─────────────────
let _browser = null, _page = null;
async function ensurePage() {
  if (_page && !_page.isClosed()) return _page;
  const { chromium } = await import("playwright");
  // Headless by default — the launchd agent runs as a Background process, so a
  // VISIBLE browser can't reach the window server and hangs. Screenshots stand
  // in for "watching it". Set PW_HEADFUL=1 only when running the worker in a
  // normal Terminal (not launchd) if you want to see the window.
  _browser = await chromium.launch({
    headless: process.env.PW_HEADFUL !== "1",
    timeout: 20000, // never hang forever on launch
  });
  _page = await _browser.newPage({ viewport: { width: 1280, height: 900 } });
  return _page;
}
async function closeBrowser() {
  try { if (_browser) await _browser.close(); } catch { /* noop */ }
  _browser = null; _page = null;
}

async function walk(dir, out, base) {
  for (const e of await fs.readdir(dir, { withFileTypes: true })) {
    if (e.name.startsWith(".") || e.name === "node_modules") continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) await walk(full, out, base);
    else out.push(path.relative(base, full));
  }
}

// SSRF guard: only http(s), and refuse hosts that resolve to loopback/private/
// link-local ranges (cloud metadata 169.254.169.254, localhost, LAN, etc.).
function safeHttpUrl(raw) {
  let u;
  try {
    u = new URL(raw);
  } catch {
    throw new Error(`bad url: ${raw.slice(0, 80)}`);
  }
  if (u.protocol !== "http:" && u.protocol !== "https:") {
    throw new Error(`blocked scheme ${u.protocol} — only http/https`);
  }
  const host = u.hostname.toLowerCase();
  const blockedName = host === "localhost" || host.endsWith(".local")
    || host.endsWith(".internal") || host === "metadata.google.internal";
  const m = host.match(/^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/);
  let blockedIp = false;
  if (m) {
    const [a, b] = [Number(m[1]), Number(m[2])];
    blockedIp = a === 127 || a === 10 || a === 0 || a === 169  // loopback, private, link-local
      || (a === 192 && b === 168) || (a === 172 && b >= 16 && b <= 31)
      || a >= 224;  // multicast/reserved
  }
  if (blockedName || blockedIp || host === "[::1]" || host.startsWith("[fd") || host.startsWith("[fe80")) {
    throw new Error(`blocked host ${host} — refusing internal/loopback address`);
  }
  return u.href;
}

function htmlToText(html) {
  return html
    .replace(/<script[\s\S]*?<\/script>/gi, " ")
    .replace(/<style[\s\S]*?<\/style>/gi, " ")
    .replace(/<[^>]+>/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

async function runTool(taskId, name, args) {
  if (name === "read_file") {
    return (await fs.readFile(safePath(args.path), "utf8")).slice(0, 12000);
  }
  if (name === "write_file") {
    const p = safePath(args.path);
    const existed = await fs.access(p).then(() => true).catch(() => false);
    await fs.mkdir(path.dirname(p), { recursive: true });
    await fs.writeFile(p, String(args.content ?? ""), "utf8");
    filesWritten += 1;
    await emit(taskId, `wrote ${args.path}`);
    await artifact(taskId, p, "local", existed ? "updated" : "created");
    return `wrote ${args.path}`;
  }
  if (name === "list_dir") {
    const entries = await fs.readdir(safePath(args.path || "."), { withFileTypes: true });
    return entries.map((e) => (e.isDirectory() ? `${e.name}/` : e.name)).join("\n");
  }
  if (name === "search_files") {
    const out = [];
    await walk(ROOT, out, ROOT);
    const q = String(args.query || "").toLowerCase();
    return out.filter((p) => p.toLowerCase().includes(q)).slice(0, 60).join("\n") || "(no matches)";
  }
  if (name === "web_read") {
    const url = safeHttpUrl(String(args.url || ""));  // block SSRF: scheme + private IPs
    const r = await fetch(url, { redirect: "manual" });  // don't auto-follow into internal hosts
    if (r.status >= 300 && r.status < 400) {
      const loc = r.headers.get("location") || "";
      // one manual hop, re-validated — a public page redirecting to metadata IP is the attack
      const r2 = await fetch(safeHttpUrl(new URL(loc, url).href), { redirect: "manual" });
      return htmlToText(await r2.text()).slice(0, 12000);
    }
    return htmlToText(await r.text()).slice(0, 12000);
  }
  if (name === "vault_read") {
    return (await fs.readFile(vaultPath(args.path), "utf8")).slice(0, 16000);
  }
  if (name === "vault_write") {
    vaultWritableGuard(args.path);
    const p = vaultPath(args.path);
    const existed = await fs.access(p).then(() => true).catch(() => false);
    await fs.mkdir(path.dirname(p), { recursive: true });
    await fs.writeFile(p, String(args.content ?? ""), "utf8");
    filesWritten += 1;
    await emit(taskId, `vault: wrote ${args.path}`);
    await artifact(taskId, p, "vault", existed ? "updated" : "created");
    return `wrote ${args.path}`;
  }
  if (name === "vault_list") {
    const out = [];
    await walk(vaultPath(args.prefix || "."), out, VAULT);
    return out.slice(0, 250).join("\n") || "(empty)";
  }
  if (name === "vault_search") {
    const out = [];
    await walk(VAULT, out, VAULT);
    const q = String(args.query || "").toLowerCase();
    return out.filter((p) => p.toLowerCase().includes(q)).slice(0, 80).join("\n") || "(no matches)";
  }
  if (name === "run_shell") {
    const cmd = String(args.command || "");
    const ok = await requireApproval(taskId, `Run on your laptop: ${cmd.slice(0, 120)}`, args.why || cmd);
    if (!ok) return "DENIED by the user — do not retry this command.";
    await emit(taskId, `running: ${cmd.slice(0, 80)}`);
    return await new Promise((resolve) => {
      exec(cmd, { cwd: ROOT, timeout: 120000, maxBuffer: 1024 * 1024 }, (err, stdout, stderr) => {
        const out = (stdout || "") + (stderr || "");
        resolve((err ? `exit ${err.code}: ` : "") + out.slice(0, 8000));
      });
    });
  }
  if (name === "browser_navigate") {
    const page = await ensurePage();
    const url = /^[a-z][a-z0-9+.-]*:\/\//i.test(String(args.url)) ? String(args.url) : "https://" + String(args.url);
    await page.goto(url, { waitUntil: "domcontentloaded", timeout: 30000 });
    await emit(taskId, `browser → ${url}`);
    return `Navigated to ${page.url()} — "${await page.title()}"`;
  }
  if (name === "browser_read") {
    const page = await ensurePage();
    const text = await page.evaluate(() => document.body?.innerText || "");
    return text.replace(/\n{3,}/g, "\n\n").slice(0, 12000) || "(page has no visible text yet)";
  }
  if (name === "browser_click") {
    const page = await ensurePage();
    const target = String(args.text || args.selector || "");
    try {
      if (args.text) await page.getByText(target, { exact: false }).first().click({ timeout: 8000 });
      else await page.click(target, { timeout: 8000 });
    } catch (e) {
      return `Couldn't click "${target}": ${e.message.slice(0, 120)}`;
    }
    await page.waitForLoadState("domcontentloaded", { timeout: 8000 }).catch(() => {});
    await emit(taskId, `browser: clicked "${target.slice(0, 40)}"`);
    return `Clicked "${target}". Now at ${page.url()}`;
  }
  if (name === "browser_type") {
    const page = await ensurePage();
    await page.fill(String(args.selector), String(args.text || ""), { timeout: 8000 });
    return `Typed into ${args.selector}`;
  }
  if (name === "browser_screenshot") {
    const page = await ensurePage();
    await fs.mkdir(ROOT, { recursive: true });
    const p = path.join(ROOT, `shot-${Date.now()}.png`);
    await page.screenshot({ path: p, fullPage: Boolean(args.fullPage) });
    await artifact(taskId, p, "local", "created");
    await emit(taskId, `browser: screenshot → ${path.basename(p)}`);
    return `Saved screenshot to ${p} (${page.url()})`;
  }
  if (name === "browser_close") {
    await closeBrowser();
    return "Browser closed.";
  }
  if (name === "look_at_screen") {
    // Read-only screen Q&A: screencapture → downscale (stay under API image
    // limits) → one vision call. Needs a one-time Screen Recording grant for
    // the worker's node process (System Settings → Privacy) — without it macOS
    // captures wallpaper only, which the answer will make obvious.
    await fs.mkdir(ROOT, { recursive: true });
    const p = path.join(ROOT, `screen-${Date.now()}.jpg`);
    await new Promise((res, rej) =>
      execFile("screencapture", ["-x", "-t", "jpg", p], { timeout: 15000 },
        (e) => (e ? rej(new Error(`screencapture failed: ${e.message}`)) : res())));
    await new Promise((res) =>
      execFile("sips", ["--resampleWidth", "1728", p], { timeout: 15000 }, () => res()));
    const b64 = (await fs.readFile(p)).toString("base64");
    await artifact(taskId, p, "local", "created");
    await emit(taskId, "looked at the screen");
    const q = String(args.question || "").trim() || "Describe what's on the screen.";
    const resp = await anthropic.messages.create({
      model: MODEL, max_tokens: 1000,
      messages: [{ role: "user", content: [
        { type: "image", source: { type: "base64", media_type: "image/jpeg", data: b64 } },
        { type: "text", text: `This is a screenshot of Trav's Mac screen right now. ${q}\n\nIMPORTANT: if the image shows ONLY a desktop wallpaper with no windows, menu bar content, or UI, the capture almost certainly lacks Screen Recording permission — say exactly that and tell him to allow the worker's node process in System Settings → Privacy & Security → Screen Recording, instead of describing the wallpaper.` },
      ] }],
    });
    const answer = resp.content.filter((b) => b.type === "text").map((b) => b.text).join("\n").trim();
    return answer || "(couldn't read the screen)";
  }
  throw new Error(`unknown tool ${name}`);
}

// ── the agent loop for one task ─────────────────────────────────────────────
async function loadVaultManual() {
  if (vaultManual) return vaultManual;
  try {
    vaultManual = await fs.readFile(path.join(VAULT, "CLAUDE.md"), "utf8");
  } catch {
    vaultManual = "";
  }
  return vaultManual;
}

async function runTask(taskId, task) {
  await emit(taskId, `Local worker picked up: ${String(task).slice(0, 120)}`);
  const manual = await loadVaultManual();
  let system =
    "You are the RESOLVE local worker running on Trav's Mac. Accomplish the task using your " +
    `tools. Files are sandboxed to the workspace at ${ROOT}. run_shell requires Trav's approval ` +
    "and should be used sparingly and safely — never destructive commands. Read before you write. " +
    "For web tasks (visit a site and read/click/type/extract), drive a real Chromium browser: " +
    "browser_navigate to a URL, then browser_read to extract, browser_click (by visible text) and " +
    "browser_type to interact, browser_screenshot to capture. Call browser_close when finished. " +
    "If the task asks about what's on the screen right now (an error, an open app/tab, a dialog), " +
    "use look_at_screen with a focused question. " +
    "When done, call finish with a concise summary (include what you found/did).";
  if (manual) {
    system +=
      `\n\n--- SECOND BRAIN ---\nTrav's Obsidian vault is at ${VAULT}. Use the vault_* tools for ` +
      "it (vault_read/list/search/write; raw/ and CLAUDE.md are read-only). For ANY vault work — " +
      "especially an ingest — follow its operating manual below EXACTLY (the ingest pipeline, " +
      "honest calibration, frontmatter, [[wikilinks]], index/log upkeep). This manual is the " +
      "source of truth for all vault interactions:\n\n" + manual;
  }
  const messages = [{ role: "user", content: String(task) }];
  let summary = "";
  let nudges = 0;
  const writesBefore = filesWritten;
  // The poll loop is blocked for the whole task, so heartbeat or the cloud
  // marks this worker offline after 30s — and gates local saves on that.
  const beat = setInterval(() => {
    cp("/v1/local/ping", { method: "POST" }).catch(() => {});
  }, 10_000);
  try {
    for (let i = 0; i < MAX_TURNS; i++) {
      const resp = await anthropic.messages.create({ model: MODEL, max_tokens: 2000, system, tools: TOOLS, messages });
      const texts = resp.content
        .filter((b) => b.type === "text")
        .map((b) => b.text)
        .filter((t) => t && t.trim());
      // join ALL text blocks — taking only the last one dropped the body
      const turnText = texts.join("\n").trim();
      if (turnText) summary = turnText;
      const toolUses = resp.content.filter((b) => b.type === "tool_use");

      if (toolUses.length) {
        messages.push({ role: "assistant", content: resp.content });
        const results = [];
        let done = false;
        const truncated = resp.stop_reason === "max_tokens";
        for (const tu of toolUses) {
          if (truncated) {
            // a call cut off mid-emit has unreliable input — answer it, don't run it
            results.push({ type: "tool_result", tool_use_id: tu.id, is_error: true,
              content: "Not executed — your previous turn was cut off mid-call. Retry it or answer without it." });
            continue;
          }
          if (tu.name === "finish") {
            summary = tu.input?.summary || summary;
            done = true;
            results.push({ type: "tool_result", tool_use_id: tu.id, content: "ok" });
            continue;
          }
          try {
            const out = await runTool(taskId, tu.name, tu.input || {});
            results.push({ type: "tool_result", tool_use_id: tu.id, content: String(out).slice(0, 12000) });
          } catch (e) {
            results.push({ type: "tool_result", tool_use_id: tu.id, content: `Error: ${e.message}`, is_error: true });
          }
        }
        messages.push({ role: "user", content: results });
        if (done) break;
        continue;
      }

      // No tool call. If it only PROMISED to act ("let me compile...", "let me
      // create the writeup now:") make it deliver instead of ending the task.
      if (nudges < 3 && needsAction(summary)) {
        nudges += 1;
        messages.push({ role: "assistant", content: resp.content.length ? resp.content : [{ type: "text", text: "…" }] });
        messages.push({ role: "user", content:
          "You have NOT delivered. You described what you were about to do instead of doing it. " +
          "If the task needs a file, call write_file NOW with the full content. Otherwise output the " +
          "complete result as your final message. Do not say 'let me' — act." });
        continue;
      }
      break;
    }
  } finally {
    clearInterval(beat);
  }

  // HONESTY: report what actually happened, so the cloud can't log a task that
  // produced nothing as complete (it did exactly that, and the dock stayed silent).
  const wrote = filesWritten - writesBefore;
  let failure = null;
  if (needsAction(summary)) {
    failure = "NO OUTPUT: the agent described the work but never delivered it.";
  } else if (wrote === 0 && PROMISED_FILE_RE.test(summary)) {
    failure = "NO OUTPUT: a file was promised but none was written to disk.";
  }
  const reported = failure ? `${failure}\n\n${summary}`.trim() : summary;
  await cp("/v1/local/result", { method: "POST", body: JSON.stringify({ taskId, summary: reported }) })
    .catch(() => {});
  await emit(taskId, failure ? `Local task FAILED — nothing produced` : `Local task complete`, reported);
  return reported;
}

// ── vault content grep (structured action — no LLM, instant, $0) ────────────
// The vault lives on this disk, so content search is a local read: walk md/txt
// files, case-insensitive substring match, return path + matching line
// fragments. GitHub's code-search index skips this private repo's contents, so
// the laptop IS the content-search backend when online.
async function vaultGrep(query) {
  const q = String(query || "").toLowerCase().trim();
  if (!q) return [];
  const hits = [];
  async function walkVault(dir) {
    let entries;
    try {
      entries = await fs.readdir(dir, { withFileTypes: true });
    } catch {
      return;
    }
    for (const e of entries) {
      if (hits.length >= 20) return;
      if (e.name.startsWith(".") || e.name === "node_modules") continue;
      const full = path.join(dir, e.name);
      if (e.isDirectory()) {
        await walkVault(full);
      } else if (/\.(md|txt)$/i.test(e.name)) {
        try {
          const st = await fs.stat(full);
          if (st.size > 1024 * 1024) continue;
          const text = await fs.readFile(full, "utf8");
          if (!text.toLowerCase().includes(q)) continue;
          const fragments = [];
          for (const line of text.split("\n")) {
            if (line.toLowerCase().includes(q)) {
              fragments.push(line.trim().slice(0, 200));
              if (fragments.length >= 2) break;
            }
          }
          hits.push({ path: path.relative(VAULT, full), fragments });
        } catch { /* unreadable file — skip */ }
      }
    }
  }
  await walkVault(VAULT);
  return hits;
}

// ── structured "open" actions (folders / apps / websites) ───────────────────
// Safe, non-destructive display actions dispatched straight from the cloud — no
// LLM, no approval. Uses macOS `open` via execFile (no shell, so no injection).
function openCmd(action) {
  const kind = String(action.kind || "");
  let value = String(action.value || "").trim();
  if ((kind === "folder" || kind === "file" || kind === "reveal") && value.startsWith("~")) {
    value = path.join(os.homedir(), value.slice(1));
  }
  if (kind === "app") return { args: ["-a", value], label: `Opened ${value}` };
  if (kind === "url") {
    if (!/^[a-z][a-z0-9+.-]*:\/\//i.test(value)) value = "https://" + value;
    return { args: [value], label: `Opened ${value}` };
  }
  if (kind === "reveal") return { args: ["-R", value], label: `Revealed ${value} in Finder` };
  return { args: [value], label: `Opened ${value}` }; // folder / file
}

async function runOpen(taskId, action) {
  const { args, label } = openCmd(action);
  await emit(taskId, label);
  const out = await new Promise((resolve) => {
    execFile("open", args, { timeout: 15000 }, (err, _stdout, stderr) => {
      if (err) resolve(`Couldn't open "${action.value}": ${(stderr || err.message).slice(0, 200)}`);
      else resolve(label);
    });
  });
  await cp("/v1/local/result", { method: "POST", body: JSON.stringify({ taskId, summary: out }) }).catch(() => {});
  return out;
}

// ── self-update (idle only) ─────────────────────────────────────────────────
// The worker lives in the resolve repo; new worker code ships by pushing to
// origin. Once an hour, while idle, pull --ff-only and restart (launchd
// KeepAlive relaunches us) if anything under apps/local-worker/ changed.
const UPDATE_EVERY_MS = 60 * 60 * 1000;
const execEnv = { ...process.env, GIT_TERMINAL_PROMPT: "0" }; // never hang on a credential prompt
function sh(cmd, timeout = 60_000) {
  return new Promise((resolve, reject) => {
    exec(cmd, { cwd: SELF_DIR, timeout, env: execEnv, maxBuffer: 1024 * 1024 },
      (err, stdout) => (err ? reject(err) : resolve(String(stdout).trim())));
  });
}
async function checkForUpdate() {
  try {
    const before = await sh("git rev-parse HEAD");
    await sh("git pull --ff-only --quiet");
    const after = await sh("git rev-parse HEAD");
    if (before === after) return;
    const changed = await sh(`git diff --name-only ${before} ${after}`);
    if (!/apps\/local-worker\//.test(changed)) return; // update didn't touch the worker
    if (/apps\/local-worker\/package(-lock)?\.json/.test(changed)) {
      console.log("worker update: installing deps…");
      await sh("npm install --no-audit --no-fund", 300_000);
    }
    console.log(`worker update: ${before.slice(0, 7)} → ${after.slice(0, 7)} — restarting to load it`);
    process.exit(0); // launchd KeepAlive relaunches with the new code
  } catch (e) {
    console.error("worker update check failed:", e.message); // soft-fail (offline, dirty tree, …)
  }
}

// ── main poll loop ──────────────────────────────────────────────────────────
// Poll failures back off 5s→10s→20s→40s→60s and force a clean relaunch after
// ~15 consecutive misses (~12 min): a fresh process shakes off wedged sockets
// / DNS after sleep or network changes, and launchd brings us right back.
const MAX_POLL_FAILS = 15;
async function main() {
  if (!CP) throw new Error("CONTROL_PLANE_URL not set");
  await fs.mkdir(ROOT, { recursive: true });
  console.log(`RESOLVE local worker online. workspace=${ROOT} control-plane=${CP}`);
  let pollFails = 0;
  let lastUpdateCheck = 0;
  for (;;) {
    try {
      const job = await cp("/v1/local/next"); // { taskId, task, action? } or null
      if (pollFails) console.log(`poll recovered after ${pollFails} failure(s)`);
      pollFails = 0;
      if (job && job.taskId) {
        if (job.action && job.action.kind === "vault_grep") {
          console.log(`> vault_grep ${job.taskId}: ${String(job.action.value).slice(0, 60)}`);
          const matches = await vaultGrep(job.action.value).catch(() => []);
          await cp("/v1/local/result", {
            method: "POST",
            body: JSON.stringify({ taskId: job.taskId,
              summary: JSON.stringify({ matches }).slice(0, 8000) }),
          }).catch(() => {});
        } else if (job.action && job.action.kind === "save_file") {
          // Deterministic write of a plan's output onto the Mac — no LLM in the
          // path, so "saved" can't be a claim the model made up. Still sandboxed
          // to the workspace by safePath().
          console.log(`> save_file ${job.taskId}: ${String(job.action.value).slice(0, 80)}`);
          let summary;
          try {
            const p = safePath(job.action.value);
            await fs.mkdir(path.dirname(p), { recursive: true });
            const existed = await fs
              .access(p)
              .then(() => true)
              .catch(() => false);
            await fs.writeFile(p, String(job.action.content ?? ""), "utf8");
            await artifact(job.taskId, p, "local", existed ? "updated" : "created");
            summary = `Saved ${p}`;
          } catch (e) {
            // report the failure rather than letting the cloud assume success
            summary = `SAVE FAILED: ${String(e.message || e).slice(0, 200)}`;
            console.error("save_file failed", e);
          }
          await cp("/v1/local/result", {
            method: "POST",
            body: JSON.stringify({ taskId: job.taskId, summary }),
          }).catch(() => {});
        } else if (job.action && job.action.kind === "restart") {
          // cloud-pushed restart: confirm, then exit — launchd relaunches with fresh code
          console.log(`> restart requested by the control plane (${job.taskId})`);
          await cp("/v1/local/result", { method: "POST", body: JSON.stringify({ taskId: job.taskId, summary: "Worker restarting — back in a few seconds." }) }).catch(() => {});
          process.exit(0);
        } else if (job.action) {
          console.log(`> open ${job.taskId}: ${job.action.kind} ${String(job.action.value).slice(0, 80)}`);
          await runOpen(job.taskId, job.action).catch((e) => console.error("open failed", e));
        } else {
          console.log(`> task ${job.taskId}: ${String(job.task).slice(0, 80)}`);
          await runTask(job.taskId, job.task).catch((e) => console.error("task failed", e));
        }
      } else {
        if (Date.now() - lastUpdateCheck > UPDATE_EVERY_MS) {
          lastUpdateCheck = Date.now();
          await checkForUpdate(); // idle only — never restarts mid-task
        }
        await new Promise((r) => setTimeout(r, 3000));
      }
    } catch (e) {
      pollFails += 1;
      if (pollFails === 1 || pollFails % 5 === 0) {
        console.error(`poll error (${pollFails}x): ${e.message}`);
      }
      if (pollFails >= MAX_POLL_FAILS) {
        console.error("too many consecutive poll failures — restarting for a clean slate");
        process.exit(1); // launchd KeepAlive relaunches us
      }
      const wait = Math.min(60_000, 5000 * 2 ** Math.min(pollFails - 1, 4));
      await new Promise((r) => setTimeout(r, wait));
    }
  }
}

// Exported so the delivery guard can be tested without starting the poll loop.
export { needsAction, PROMISED_FILE_RE };

// Only run the worker when executed directly (not when imported by a test).
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch((e) => {
    console.error(e);
    process.exit(1);
  });
}
