# RESOLVE

Personal Jarvis platform: a durable goal control plane, policy-gated multi-agent execution, and a
cinematic command-center dashboard.

Originally extracted from the `vault1` scaffold so the platform could grow without touching the
deployed single-file Telegram bot. That strangler migration is done — every capability now runs
through this repo's own connectors, and both directions of Telegram (notifications out, approval
buttons and `/resolve` in) are handled by the control plane.

## Layout

```
docs/JARVIS_SYSTEM_PLAN.md     full architecture plan and migration roadmap
docs/DIRECTION.md              agent roster, storage split, UI v2 spec
apps/dashboard                 the Jarvis command-center web app (Next.js)
apps/local-worker              the laptop "hands": sandboxed files, web-read, gated shell
apps/desktop, apps/mobile      native shells around the hosted dashboard (Electron / Capacitor)
services/control_plane         assistant, planner/executor, policies, approvals, connectors (FastAPI)
config/                        model routes, tool policies, connector strategy (data, not code)
infra/                         Postgres schema, local docker-compose, env template
```

## Quick start

Dashboard — talks to a control plane via `CONTROL_PLANE_URL` + `CP_TOKEN` in `.env.local`:

```sh
cd apps/dashboard
npm install
npm run dev        # http://localhost:3000
```

Control plane (API + worker + Postgres + Redis):

```sh
cd infra
docker compose up  # API on :8000, schema auto-applied
```

Tests:

```sh
cd services/control_plane
python -m pytest tests -q
```

## Status

- Control plane: live. Assistant loop, planner + executor worker, policy engine, approvals (dashboard
  banners and Telegram buttons), routines, cost tracking, and the laptop worker bridge all run.
- Dashboard: live-only. Panels are driven by `/v1/snapshot` plus the `/v1/events` SSE stream; an
  unreachable backend reads OFFLINE and shows nothing rather than simulated data.
- Model routes and tool policies are config-as-data; IDs verified against provider catalogs 2026-07-10.

## Capabilities

54 assistant tools. The non-obvious ones and why they exist:

| Area | Notes |
|---|---|
| **Attachments** | Photos, screenshots, PDFs, and voice notes sent over Telegram are read directly (`media.py`). Voice is transcribed with whisper-1 before it reaches the model. Telegram photo sizes are chosen under the vision pixel cap, so no tokens are spent on pixels the API discards. |
| **Web search** | The assistant searches directly (`ASSISTANT_WEB_SEARCH`). It used to have none, so every current-info question was forced through `plan_project` and the pricier planner. |
| **Google Workspace** | Create, **read**, append, and **targeted edit** for Docs/Sheets/Slides. `replace_in_google_doc` / `update_google_sheet` change existing content; the older `edit_*` tools only append. A 0-occurrence replace is reported as a failure, never as success. |
| **Email** | `draft_email` writes a real Gmail draft (nothing sent) and is the default; `send_email` still requires approval. Inbox triage now leaves drafts in Gmail instead of in the chat. |
| **School** | Canvas via the personal **calendar-feed ICS** — UVA doesn't issue student API tokens, and the feed needs none. Due dates only; grades and announcements go through the laptop's logged-in browser. |
| **World** | Weather and driving time from Open-Meteo and OSRM — both keyless, so no extra secrets and no per-call cost. |
| **Memory** | `vault_read` greps exactly; `vault_recall` searches the vault by meaning (pgvector + `text-embedding-3-small`, re-indexed nightly, unchanged chunks skipped by hash). |
| **Code** | `code_task` = architect plans → laptop implements and runs tests → `review_code` reads the diff in a fresh context. Uses the `coding_architect` / `code_reviewer` routes. |
| **GitHub** | Issues, PRs, and Actions status via REST on the existing token — "did the build pass?" is answerable. |
| **Music** | Spotify playback, search, and now-playing. Needs an active device and a pinned account (see `COMPOSIO_ACCOUNTS`). |

Every tool is policy-gated (`config/tool_policies.json`); a test asserts that each declared tool has
both a policy entry and a dispatch branch, so one can't be exposed to the model half-wired.
