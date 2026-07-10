# RESOLVE command center

The Jarvis dashboard from `docs/JARVIS_SYSTEM_PLAN.md` §11 — command core, mission rail, agent
constellation, live timeline, approval inbox, vitals, and artifacts dock.

**Mock mode:** every panel is driven by a deterministic simulated `agent_events` stream in
`lib/engine.ts`, and the UI carries a persistent MOCK badge. The real control-plane SSE feed replaces
the engine behind the same event types when Phase 1 APIs land; the components don't change.

```sh
npm install
npm run dev   # http://localhost:3000
```
