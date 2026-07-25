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
