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

const CP = (process.env.CONTROL_PLANE_URL || "").replace(/\/$/, "");
const CP_TOKEN = process.env.CP_TOKEN || "";
const MODEL = process.env.WORKER_MODEL || "claude-opus-4-8";
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
  { name: "finish", description: "Call when the task is complete, with a short result summary.",
    input_schema: { type: "object", properties: { summary: { type: "string" } }, required: ["summary"] } },
];

async function walk(dir, out, base) {
  for (const e of await fs.readdir(dir, { withFileTypes: true })) {
    if (e.name.startsWith(".") || e.name === "node_modules") continue;
    const full = path.join(dir, e.name);
    if (e.isDirectory()) await walk(full, out, base);
    else out.push(path.relative(base, full));
  }
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
    const r = await fetch(String(args.url), { redirect: "follow" });
    const body = await r.text();
    return htmlToText(body).slice(0, 12000);
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
    "When done, call finish with a concise summary of what you did.";
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
  for (let i = 0; i < MAX_TURNS; i++) {
    const resp = await anthropic.messages.create({ model: MODEL, max_tokens: 2000, system, tools: TOOLS, messages });
    const texts = resp.content.filter((b) => b.type === "text").map((b) => b.text);
    if (texts.length) summary = texts[texts.length - 1];
    const toolUses = resp.content.filter((b) => b.type === "tool_use");
    if (resp.stop_reason !== "tool_use" || !toolUses.length) break;
    messages.push({ role: "assistant", content: resp.content });
    const results = [];
    let done = false;
    for (const tu of toolUses) {
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
  }
  await cp("/v1/local/result", { method: "POST", body: JSON.stringify({ taskId, summary }) });
  await emit(taskId, `Local task complete`, summary);
  return summary;
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

// ── main poll loop ──────────────────────────────────────────────────────────
async function main() {
  if (!CP) throw new Error("CONTROL_PLANE_URL not set");
  await fs.mkdir(ROOT, { recursive: true });
  console.log(`RESOLVE local worker online. workspace=${ROOT} control-plane=${CP}`);
  for (;;) {
    try {
      const job = await cp("/v1/local/next"); // { taskId, task, action? } or null
      if (job && job.taskId) {
        if (job.action) {
          console.log(`> open ${job.taskId}: ${job.action.kind} ${String(job.action.value).slice(0, 80)}`);
          await runOpen(job.taskId, job.action).catch((e) => console.error("open failed", e));
        } else {
          console.log(`> task ${job.taskId}: ${String(job.task).slice(0, 80)}`);
          await runTask(job.taskId, job.task).catch((e) => console.error("task failed", e));
        }
      } else {
        await new Promise((r) => setTimeout(r, 3000));
      }
    } catch (e) {
      console.error("poll error:", e.message);
      await new Promise((r) => setTimeout(r, 5000));
    }
  }
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
