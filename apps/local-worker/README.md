# RESOLVE local worker — the laptop "hands"

Runs on your Mac and gives RESOLVE local powers: **sandboxed file** read/write/search,
**web-read**, and **approval-gated shell** — all driven by a Claude agent. The cloud
control plane orchestrates; this worker executes anything that needs your machine.
Progress streams into the dashboard; shell commands ask for your approval first.

## Safety model (the non-negotiable)
- **Files are locked to one folder** (`RESOLVE_WORKSPACE`). Any path that escapes it
  is refused.
- **`run_shell` always asks for approval** (dashboard banner / Telegram) before it runs.
  Reject = it doesn't run.
- Read/write inside the sandbox is allowed without a prompt; everything risky is gated.

## Run it
```bash
cd apps/local-worker
npm install
CONTROL_PLANE_URL=https://resolve-4jqh.onrender.com \
CP_TOKEN=<your CP_TOKEN> \
ANTHROPIC_API_KEY=<your key> \
RESOLVE_WORKSPACE="$HOME/resolve-workspace" \
npm start
```
It prints `RESOLVE local worker online` and starts polling for tasks. Leave it running
(or later: have the desktop app launch it automatically).

Ask RESOLVE something like *"on my laptop, summarize the files in my workspace"* → the
assistant dispatches it here, and you watch it work in the constellation.

## Vault ingests (second brain)
The worker is vault-aware: it loads your Obsidian vault's **`CLAUDE.md` as its operating
manual** and has `vault_read/list/search/write` tools (full file contents, direct disk — no
truncation). `raw/` and `CLAUDE.md` are write-protected. So you can run **CLAUDE.md-compliant
ingests locally**, e.g. ask RESOLVE: *"on my laptop, run a vault ingest of today's activity"* —
it follows the manual's pipeline (source page → propagate → index/log, honest calibration).

## Env
| var | default | notes |
|-----|---------|-------|
| `CONTROL_PLANE_URL` | — | your control plane URL |
| `CP_TOKEN` | — | same token the dashboard uses |
| `ANTHROPIC_API_KEY` | — | for the agent |
| `RESOLVE_WORKSPACE` | `~/resolve-workspace` | the sandbox folder |
| `VAULT_PATH` | `~/Desktop/Obsidian Vault` | your Obsidian vault (for ingests) |
| `WORKER_MODEL` | `claude-opus-4-8` | agent model |

## Roadmap
- Web **interaction** (clicks/forms) via Playwright — currently web-*read* only (free `fetch`).
- Auto-launch from the desktop app.
- Broader tools behind the same approval gate.
