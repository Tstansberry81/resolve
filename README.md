# RESOLVE

Personal Jarvis platform: a durable goal control plane, policy-gated multi-agent execution, and a
cinematic command-center dashboard.

Extracted from the `vault1` scaffold (`agent/jarvis-control-plane` branch) so the platform can grow
without touching the deployed single-file Telegram bot. The legacy bot remains the capability adapter
during the strangler migration described in the system plan.

## Layout

```
docs/JARVIS_SYSTEM_PLAN.md     full architecture plan and migration roadmap
apps/dashboard                 the Jarvis command-center web app (Next.js)
services/control_plane         goals, policies, scheduling, state transitions (FastAPI)
config/                        model routes, tool policies, connector strategy (data, not code)
infra/                         Postgres schema, local docker-compose, env template
```

## Quick start

Dashboard (mock mode — driven by a simulated event stream until the control-plane APIs land):

```sh
cd apps/dashboard
npm install
npm run dev        # http://localhost:3000
```

Control plane (API + inert worker + Postgres + Redis):

```sh
cd infra
docker compose up  # API on :8000, schema auto-applied
```

Tests:

```sh
cd services/control_plane
PYTHONPATH=src python3 -m unittest discover -s tests
```

## Status

- Control plane: domain model, state machines, policy engine, and schema scaffolded; repository
  layer and worker execution deliberately disabled until approvals and leases exist.
- Dashboard: mock platform in active build. Every panel is driven by a deterministic simulated
  `agent_events` stream, clearly labeled MOCK, so the UX can be perfected before the backend wires in.
- Model routes and tool policies are config-as-data; IDs verified against provider catalogs 2026-07-10.
