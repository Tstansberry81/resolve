# RESOLVE command center

The Jarvis dashboard from `docs/JARVIS_SYSTEM_PLAN.md` §11 — command core, mission rail, agent
constellation, live timeline, approval inbox, vitals, and artifacts dock.

Every panel is fed by the control plane: `GET /v1/snapshot` on load plus the `/v1/events` SSE
stream, both through the `/api/cp` proxy (`app/api/cp/[...path]/route.ts`), normalized into one
`EngineState` by `lib/liveEngine.ts`. There is no mock mode — the scripted simulator that used to
back these panels is gone. When the control plane can't be reached the header reads **OFFLINE** and
panels stay empty rather than showing invented data.

```sh
npm install
npm run dev   # http://localhost:3000
```

Point it at a control plane with `CONTROL_PLANE_URL` and `CP_TOKEN` in `.env.local` (see
`.env.example`); the proxy attaches the bearer token server-side so it never reaches the browser.
