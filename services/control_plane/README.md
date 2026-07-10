# RESOLVE control plane

This sidecar is the migration target for durable goals. It intentionally does not import
`telegram_agent.py`; the deployed bot remains stable while capabilities are moved behind connector
interfaces one at a time.

The first implementation milestones are:

1. Apply `infra/postgres/001_control_plane.sql`.
2. Implement the repository layer for goals, tasks, approvals, and events.
3. Claim ready tasks with a database lease and `FOR UPDATE SKIP LOCKED`.
4. Route each task through `config/model_routes.json`.
5. Check every tool call through `config/tool_policies.json`.
6. Wrap existing `telegram_agent.py` capabilities as connector calls.

The API currently exposes health and configuration metadata. It does not execute autonomous goals
until the persistence and connector milestones above are complete.
