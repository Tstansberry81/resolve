# RESOLVE direction — agent roster, storage, and UI v2

Captured 2026-07-10 from Trav's spec. This is the build target for the next dashboard iteration and
the agent hierarchy. Supersedes the placeholder roster in the mock where they conflict.

## Agent hierarchy

Every input the user sends goes through **the assistant** — she is the front door and the voice of
the command core. She delegates upward for anything big and handles everything menial herself.

```
user ──▶ Assistant (Sonnet)  ── all input/output, the command core's voice
              │
              ├─ menial work she does herself: Notion tasks, GCal events,
              │  sending an email the user asked for, small agentic steps
              │
              ├──▶ Planner "Sol" (gpt-5.6-sol) — the mastermind: the assistant
              │    tells Sol what to work on; Sol designs the plan + architecture
              │
              ├──▶ Executor (Opus 4.8) — complex agentic work beyond the
              │    assistant's scope: email triage/blasts, advertisement runs,
              │    multi-step campaigns
              │
              ├──▶ Coder (Opus 4.8) + Reviewer (Opus 4.8)
              │
              └──▶ Router "Luna" (gpt-5.6-luna) — cheap classification/routing
```

Rules of thumb:
- Unless the user is designing a plan or a large-scale project, the assistant handles it.
- Complexity above the assistant's level escalates to the Executor; planning escalates to Sol.
- **Assistant model test path:** start Sonnet (config currently pins `claude-sonnet-4-6`, the direct
  successor to 4.5 at the same price — swap to `claude-sonnet-4-5` if specifically wanted); once the
  workload is understood, trial `claude-haiku-4-5` for the assistant and compare.
- Note (flagged, not decided): coder and reviewer are both Opus 4.8 per spec. The system plan's
  independent-review principle prefers a different family for review; `gpt-5.6-sol` is the natural
  reviewer alternative if same-model review proves too agreeable.
- Fable 5 considered and rejected for the assistant role: $10/$50 per MTok vs Sonnet's $3/$15 —
  premium tier reserved for build-time work, not the always-on loop.

## Storage split

- **Supabase = everything.** Full event/audit trail, goals, tasks, runs, approvals — the control-plane
  schema (`infra/postgres/001_control_plane.sql`). Nothing is lost.
- **Obsidian vault (via GitHub commits, same mechanism as the vault1 bot) = distilled knowledge:**
  summaries, personal-life notes, and project/business-level knowledge. The vault stays the
  human-readable memory; Supabase is the machine's ledger.

## UI v2 spec

- **Command core: center-top, the center of everything.** Every message flows through it (the
  assistant). Windows of importance live in the corners of the screen.
- **Constellation: directly under the command core.** It must represent the *actual agentic
  workflow* — real delegation edges (user → assistant → Sol/executor/coder → connectors), driven by
  real events, hierarchy visible — not just a cool visual.
- **Background:** transparent feel with blue sparkles/stars drifting effortlessly, glimmering in
  varying patterns.
- **Missions:** left-side dropdown sidebar.
- **Event logs:** a dropdown *under* the missions sidebar — fully hidden until clicked.
- **Approvals:** small, iOS-banner-style notifications — not a large panel.
- **System vitals:** top-left dropdown showing status at a glance; expanding reveals per-agent and
  system detail.

## Connector decisions (2026-07-26)

Recorded because in each case the obvious path was rejected for a specific reason.

- **Canvas — ICS calendar feed, not the API.** UVA doesn't issue students Canvas API
  tokens, so `/api/v1/courses/:id/assignments` is closed to us. Every Canvas user can
  generate a personal calendar feed (Calendar → "Calendar Feed"), a secret ICS URL
  carrying assignments and due dates across all courses, needing no institutional
  approval. That covers due dates — the 90% that drives the week. Grades, submission
  status, and announcements genuinely need a session, so they route through the laptop
  worker's already-logged-in browser instead of being faked.
- **Weather and travel — Open-Meteo and OSRM, not Google Maps.** Both are keyless and
  free: one less secret in Render, no billing account, no per-call cost. Google buys
  turn-by-turn navigation and live traffic, neither of which the "when do I leave"
  question needs. The traffic gap is stated in the tool's own output rather than
  hidden, so travel estimates aren't quietly optimistic at rush hour.
- **GitHub — direct REST, not Composio.** `GITHUB_TOKEN` already exists for the vault;
  going direct is one hop instead of two and sidesteps connected-account ambiguity.
- **Coding sandbox — the laptop worker, not E2B/Daytona.** The worker already executes
  shell in a sandboxed workspace behind an approval gate. Paying for a second execution
  environment buys one thing we don't have: running code while the laptop is offline.
  `code_task` currently refuses in that case rather than pretending. Revisit if that
  refusal turns out to bite often; until then it's a paid dependency for capability
  that already exists.
- **Vault recall complements grep, it does not replace it.** The laptop's exact grep
  stays the first stop: free, instant, and exact. Embeddings are for when Trav doesn't
  remember the words he used.

## Open items (waiting on Trav)

- Further UI instructions and AI lineup details promised ("more instructions later").
- Haiku-as-assistant trial after Sonnet baseline exists.
- **Microsoft Graph** — still unbuilt. It needs an Azure app registration plus an OAuth
  consent flow that only Trav can complete in the portal; writing the connector before
  that exists would ship dead code that looks finished. Worth doing if school Outlook
  and Teams matter day to day.
- **Duplex voice** — voice INPUT is done both ways (Telegram notes are transcribed;
  the dashboard has wake word + STT + TTS). A true realtime conversation loop on
  `gpt-realtime-1.5` is a substantial frontend build and hasn't started.
- **Autopilot mode** — the policy engine has supported it since the beginning and
  nothing runs in it. Phase 6 remains untouched.
