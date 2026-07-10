import type {
  Approval,
  Artifact,
  EventLevel,
  Goal,
  NodeId,
  OrbState,
  Vitals,
} from "./types";

// Scripted, deterministic scenarios. Flow per docs/DIRECTION.md:
// every input goes through the assistant (Sonnet); she handles menial work
// herself and delegates planning to Sol, heavy agentic work to the Executor,
// and code to the Coder + Reviewer. Luna routes/classifies up front.

export type Action =
  | { kind: "orb"; state: OrbState; caption: string }
  | { kind: "nodes"; ids: NodeId[] }
  | {
      kind: "event";
      actor: NodeId;
      type: string;
      level: EventLevel;
      summary: string;
      detail?: string | null;
      edge?: { from: NodeId; to: NodeId } | null;
      goalId?: string | null;
    }
  | { kind: "goal"; id: string; patch: Partial<Goal> }
  | { kind: "artifact"; artifact: Omit<Artifact, "ts"> }
  | { kind: "vitals"; patch: Partial<Vitals> }
  | {
      kind: "approval";
      approval: Approval;
      gate: boolean;
      onApprove?: Action[];
      onReject?: Action[];
    };

export interface Scenario {
  goal: Goal;
  steps: Array<{ at: number; action: Action }>;
}

// ── helpers ───────────────────────────────────────────────────────────────

const ev = (
  goalId: string,
  actor: NodeId,
  type: string,
  summary: string,
  opts: {
    level?: EventLevel;
    detail?: string;
    edge?: { from: NodeId; to: NodeId };
  } = {},
): Action => ({
  kind: "event",
  actor,
  type,
  level: opts.level ?? "info",
  summary,
  detail: opts.detail ?? null,
  edge: opts.edge ?? null,
  goalId,
});

const goal = (id: string, patch: Partial<Goal>): Action => ({
  kind: "goal",
  id,
  patch,
});

const orb = (state: OrbState, caption: string): Action => ({
  kind: "orb",
  state,
  caption,
});

const nodes = (...ids: NodeId[]): Action => ({ kind: "nodes", ids });

// ── scenario 1: morning briefing — menial, the assistant handles it alone ─

function briefing(id = "g-briefing"): Scenario {
  return {
    goal: {
      id,
      objective: "Morning briefing: agenda, inbox scan, market snapshot",
      category: "personal",
      status: "planning",
      autonomyMode: "observe",
      progress: 0.02,
      budgetUsd: 0.5,
      spentUsd: 0,
      deadline: null,
      nextAction: "Route request",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("thinking", "Sonnet is sizing up the morning") },
      { at: 0.2, action: nodes("assistant", "luna") },
      {
        at: 0.4,
        action: ev(id, "luna", "route.classified", "Routed: menial · assistant handles it directly", {
          edge: { from: "assistant", to: "luna" },
          detail: "gpt-5.6-luna · no plan needed, read-only",
        }),
      },
      { at: 1.5, action: goal(id, { status: "active", progress: 0.1, nextAction: "Read calendar" }) },
      { at: 1.6, action: orb("executing", "Sonnet is reading today's calendar") },
      { at: 1.7, action: nodes("assistant", "calendar") },
      {
        at: 2,
        action: ev(id, "assistant", "tool.call", "calendar.read — 4 events today", {
          edge: { from: "assistant", to: "calendar" },
          detail: "ECON 2010 lecture 10:00 · gym 17:30 · 2 more",
        }),
      },
      { at: 5, action: nodes("assistant", "gmail") },
      {
        at: 5.2,
        action: ev(id, "assistant", "tool.call", "gmail.scan — 23 unread, 3 need action", {
          edge: { from: "assistant", to: "gmail" },
          detail: "flagged: advisor reply, Canvas due-date change, Render invoice",
        }),
      },
      { at: 7.5, action: goal(id, { progress: 0.55, nextAction: "Market snapshot" }) },
      { at: 8, action: nodes("assistant", "web") },
      {
        at: 8.2,
        action: ev(id, "assistant", "tool.call", "markets.read — SPY +0.4%, BTC flat", {
          edge: { from: "assistant", to: "web" },
        }),
      },
      {
        at: 10.8,
        action: ev(id, "assistant", "briefing.compiled", "Briefing assembled from all 3 sources", {
          level: "success",
        }),
      },
      {
        at: 11.6,
        action: {
          kind: "artifact",
          artifact: {
            id: `${id}-art1`,
            goalId: id,
            kind: "report",
            name: "Morning briefing — Jul 10",
            meta: "4 events · 3 action emails · markets calm",
          },
        },
      },
      { at: 11.8, action: goal(id, { status: "completed", progress: 1, nextAction: "—", spentUsd: 0.05 }) },
      {
        at: 12,
        action: ev(id, "core", "goal.completed", "Briefing delivered — $0.05 of $0.50 budget", {
          level: "success",
        }),
      },
      { at: 12.2, action: orb("idle", "Sonnet standing by") },
      { at: 12.3, action: nodes() },
    ],
  };
}

// ── scenario 2: study guide — large project, Sol plans, Executor works ────

function studyGuide(id = "g-econ"): Scenario {
  return {
    goal: {
      id,
      objective: "Cited study guide: ECON 2010 chapters 3–5 + 20-question quiz",
      category: "school",
      status: "planning",
      autonomyMode: "execute",
      progress: 0.02,
      budgetUsd: 3,
      spentUsd: 0,
      deadline: "Fri 18:00",
      nextAction: "Hand to Sol",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("thinking", "Sonnet is briefing Sol on the project") },
      { at: 0.1, action: nodes("assistant", "sol") },
      {
        at: 0.5,
        action: ev(id, "assistant", "delegate.plan", "Large project — handed to Sol for planning", {
          edge: { from: "assistant", to: "sol" },
        }),
      },
      {
        at: 2,
        action: ev(id, "sol", "plan.created", "Sol: 7-task DAG with citation gate", {
          detail: "collect → extract → outline → synthesize → cite-check → quiz → coverage eval",
        }),
      },
      { at: 2.2, action: goal(id, { status: "active", progress: 0.08, nextAction: "Executor collects sources" }) },
      { at: 2.3, action: orb("executing", "Executor is collecting course sources") },
      { at: 2.4, action: nodes("sol", "executor", "canvas") },
      {
        at: 2.6,
        action: ev(id, "sol", "delegate.execute", "Plan dispatched to the Executor", {
          edge: { from: "sol", to: "executor" },
        }),
      },
      {
        at: 3.2,
        action: ev(id, "executor", "tool.call", "canvas.files — 3 lecture decks, 2 PDFs", {
          edge: { from: "executor", to: "canvas" },
        }),
      },
      {
        at: 6,
        action: ev(id, "executor", "extract.done", "Extracted 148 passages with provenance", {
          detail: "claude-opus-4-8 · $0.14",
        }),
      },
      { at: 6.2, action: goal(id, { progress: 0.35, nextAction: "Synthesize outline", spentUsd: 0.14 }) },
      {
        at: 9,
        action: ev(id, "executor", "synthesis.done", "Outline synthesized across 3 chapters", {
          detail: "high effort · every claim source-linked",
        }),
      },
      { at: 12, action: nodes("executor", "reviewer") },
      {
        at: 12.5,
        action: ev(id, "reviewer", "verify.failed", "Citation check: 2 claims missing sources", {
          level: "warn",
          detail: "elasticity example (ch.4), tax incidence figure (ch.5)",
          edge: { from: "reviewer", to: "executor" },
        }),
      },
      { at: 13, action: goal(id, { progress: 0.55, nextAction: "Repair citations" }) },
      { at: 15.5, action: nodes("executor", "canvas") },
      {
        at: 16,
        action: ev(id, "executor", "repair.done", "Both claims re-sourced from lecture 9", {
          level: "success",
          edge: { from: "executor", to: "canvas" },
        }),
      },
      { at: 18.5, action: nodes("reviewer") },
      {
        at: 19,
        action: ev(id, "reviewer", "verify.passed", "Citation + coverage checks green · quiz validates", {
          level: "success",
          edge: { from: "reviewer", to: "executor" },
        }),
      },
      {
        at: 20,
        action: {
          kind: "artifact",
          artifact: {
            id: `${id}-art1`,
            goalId: id,
            kind: "study_guide",
            name: "ECON 2010 · ch. 3–5 study guide",
            meta: "31 pages · 96 citations · 20-question quiz",
          },
        },
      },
      { at: 20.4, action: goal(id, { status: "completed", progress: 1, spentUsd: 1.92, nextAction: "—" }) },
      {
        at: 20.6,
        action: ev(id, "assistant", "goal.completed", "Sonnet: study guide saved to Notion — $1.92 of $3.00", {
          level: "success",
          edge: { from: "assistant", to: "notion" },
        }),
      },
      { at: 21, action: orb("idle", "Sonnet standing by") },
      { at: 21.1, action: nodes() },
    ],
  };
}

// ── scenario 3: bug fix — Sol plans, Coder implements, Reviewer gates ─────

function bugfix(id = "g-bugfix"): Scenario {
  return {
    goal: {
      id,
      objective: "Fix stale index.lock crash in vault sync — draft PR only",
      category: "coding",
      status: "planning",
      autonomyMode: "execute",
      progress: 0.02,
      budgetUsd: 5,
      spentUsd: 0,
      deadline: null,
      nextAction: "Hand to Sol",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("thinking", "Sonnet is scoping the bug with Sol") },
      { at: 0.1, action: nodes("assistant", "sol") },
      {
        at: 0.3,
        action: ev(id, "assistant", "delegate.plan", "Coding goal — Sol architects the fix", {
          edge: { from: "assistant", to: "sol" },
        }),
      },
      {
        at: 1.4,
        action: ev(id, "sol", "plan.created", "Sol: reproduce → fix → tests → independent review → draft PR", {
          detail: "merge explicitly withheld pending your approval",
        }),
      },
      { at: 1.6, action: nodes("sol", "coder", "github") },
      {
        at: 1.8,
        action: ev(id, "coder", "tool.call", "github.checkout — isolated worktree created", {
          edge: { from: "coder", to: "github" },
        }),
      },
      {
        at: 3.4,
        action: ev(id, "coder", "repro.confirmed", "Reproduced: stale lock persists after SIGKILL", {
          detail: "test_sync.py::test_lock_recovery fails as expected",
        }),
      },
      { at: 3.6, action: goal(id, { status: "active", progress: 0.3, nextAction: "Implement fix" }) },
      { at: 3.7, action: orb("executing", "Coder is implementing the lock-recovery fix") },
      {
        at: 7,
        action: ev(id, "coder", "commit.created", "Fix: detect and clear stale index.lock with age guard", {
          detail: "claude-opus-4-8 · 2 files, +38 −6",
        }),
      },
      { at: 9.5, action: ev(id, "coder", "tests.running", "Running unit + integration suites") },
      {
        at: 12,
        action: ev(id, "coder", "tests.passed", "14/14 tests green, including new regression test", {
          level: "success",
        }),
      },
      { at: 12.2, action: goal(id, { progress: 0.7, nextAction: "Independent review", spentUsd: 1.9 }) },
      { at: 12.4, action: nodes("coder", "reviewer") },
      {
        at: 14.5,
        action: ev(id, "reviewer", "review.done", "Reviewer: approve with 1 nit — race window comment", {
          level: "success",
          edge: { from: "coder", to: "reviewer" },
        }),
      },
      { at: 17, action: nodes("coder", "github") },
      {
        at: 17.4,
        action: ev(id, "github", "pr.drafted", "Draft PR #7 opened — merge withheld", {
          edge: { from: "coder", to: "github" },
        }),
      },
      {
        at: 17.8,
        action: {
          kind: "artifact",
          artifact: {
            id: `${id}-art1`,
            goalId: id,
            kind: "pull_request",
            name: "PR #7 · fix stale index.lock recovery",
            meta: "+38 −6 · 14/14 tests · review: approve",
          },
        },
      },
      {
        at: 18,
        action: goal(id, { status: "waiting_approval", progress: 0.9, nextAction: "Awaiting merge decision", blocker: "Needs your approval" }),
      },
      { at: 18.2, action: orb("waiting", "Sonnet is waiting on your merge decision") },
      {
        at: 18.4,
        action: {
          kind: "approval",
          gate: true,
          approval: {
            id: `${id}-appr1`,
            goalId: id,
            actionSummary: "Merge PR #7 into main",
            risk: "destructive",
            preview: [
              "repo: Tstansberry81/vault1",
              "branch: fix/stale-index-lock → main",
              "+38 −6 across 2 files · tests 14/14",
              "reviewer: approve (claude-opus-4-8)",
            ],
            recipient: null,
            undoWindow: "revert commit available",
            status: "pending",
          },
          onApprove: [
            ev(id, "github", "pr.merged", "PR #7 merged to main", { level: "success" }),
            goal(id, { status: "completed", progress: 1, nextAction: "—", spentUsd: 2.6, blocker: null }),
            orb("idle", "Sonnet standing by"),
            nodes(),
          ],
          onReject: [
            ev(id, "assistant", "pr.held", "Sonnet: merge rejected — PR stays in draft", { level: "warn" }),
            goal(id, { status: "completed", progress: 0.95, nextAction: "PR awaiting manual merge", spentUsd: 2.6, blocker: null }),
            orb("idle", "Sonnet standing by"),
            nodes(),
          ],
        },
      },
    ],
  };
}

// ── scenario 4: inbox triage + outreach blast — Executor's showcase ───────

function emailBlast(id = "g-email"): Scenario {
  return {
    goal: {
      id,
      objective: "Triage the inbox and draft the outreach blast — send needs approval",
      category: "email",
      status: "planning",
      autonomyMode: "execute",
      progress: 0.02,
      budgetUsd: 1.5,
      spentUsd: 0,
      deadline: null,
      nextAction: "Escalate to Executor",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("thinking", "Sonnet is escalating triage to the Executor") },
      { at: 0.1, action: nodes("assistant", "executor") },
      {
        at: 0.3,
        action: ev(id, "assistant", "delegate.execute", "Above menial scope — Executor takes triage + blast", {
          edge: { from: "assistant", to: "executor" },
          detail: "assistant handles single sends; bulk work goes to opus",
        }),
      },
      { at: 1.2, action: orb("executing", "Executor is triaging the inbox") },
      { at: 1.3, action: nodes("executor", "gmail") },
      {
        at: 1.5,
        action: ev(id, "executor", "tool.call", "gmail.triage — 23 unread sorted, 6 archived, 3 flagged", {
          edge: { from: "executor", to: "gmail" },
          detail: "claude-opus-4-8 · labels applied, nothing deleted",
        }),
      },
      { at: 4, action: goal(id, { status: "active", progress: 0.45, nextAction: "Draft outreach blast" }) },
      {
        at: 6,
        action: ev(id, "executor", "drafts.created", "Outreach blast drafted for 12 recipients, in your voice", {
          detail: "personalized per recipient · tone: brief, warm",
        }),
      },
      {
        at: 6.4,
        action: {
          kind: "artifact",
          artifact: {
            id: `${id}-art1`,
            goalId: id,
            kind: "draft",
            name: "Outreach blast · 12 drafts",
            meta: "triage done · 3 flagged for you",
          },
        },
      },
      {
        at: 6.6,
        action: goal(id, { status: "waiting_approval", progress: 0.75, nextAction: "Awaiting send approval", blocker: "Needs your approval" }),
      },
      { at: 6.8, action: orb("waiting", "Sonnet is waiting on your send approval") },
      {
        at: 7,
        action: {
          kind: "approval",
          gate: true,
          approval: {
            id: `${id}-appr1`,
            goalId: id,
            actionSummary: "Send outreach blast to 12 recipients",
            risk: "communication_send",
            preview: [
              "from: you · 12 personalized emails",
              "subject: Quick intro — RESOLVE",
              "“Wanted to put this on your radar…”",
              "staggered send over 10 min",
            ],
            recipient: "12 recipients",
            undoWindow: "30s unsend window per email",
            status: "pending",
          },
          onApprove: [
            ev(id, "executor", "blast.sent", "Blast rolling out — staggered, undo live per email", {
              level: "success",
              edge: { from: "executor", to: "gmail" },
            }),
            goal(id, { status: "completed", progress: 1, nextAction: "—", spentUsd: 0.34, blocker: null }),
            orb("idle", "Sonnet standing by"),
            nodes(),
          ],
          onReject: [
            ev(id, "assistant", "blast.held", "Sonnet: send rejected — drafts parked in outbox", { level: "warn" }),
            goal(id, { status: "paused", progress: 0.8, nextAction: "Drafts held", blocker: "Send rejected" }),
            orb("idle", "Sonnet standing by"),
            nodes(),
          ],
        },
      },
    ],
  };
}

// ── ad-hoc command — Luna routes, Sonnet handles it herself ───────────────

export function makeCommandScenario(text: string, id: string): Scenario {
  const short = text.length > 64 ? `${text.slice(0, 61)}…` : text;
  return {
    goal: {
      id,
      objective: short,
      category: "personal",
      status: "planning",
      autonomyMode: "assist",
      progress: 0.02,
      budgetUsd: 2,
      spentUsd: 0,
      deadline: null,
      nextAction: "Route",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("listening", "Sonnet heard you — parsing the request") },
      { at: 0.7, action: nodes("assistant", "luna") },
      {
        at: 0.9,
        action: ev(id, "luna", "route.classified", "Routed: menial · assistant handles it directly", {
          edge: { from: "assistant", to: "luna" },
        }),
      },
      { at: 1.4, action: orb("thinking", "Sonnet is working your request") },
      {
        at: 1.6,
        action: ev(id, "assistant", "goal.typed", `Goal accepted: ${short}`, {
          detail: "autonomy: assist · budget $2.00 · policy compiled",
        }),
      },
      { at: 2.4, action: goal(id, { status: "active", progress: 0.3, nextAction: "Gather" }) },
      { at: 2.5, action: orb("executing", "Sonnet is on it") },
      { at: 2.6, action: nodes("assistant", "web") },
      {
        at: 3.2,
        action: ev(id, "assistant", "tool.call", "web.search — gathering what you asked for", {
          edge: { from: "assistant", to: "web" },
        }),
      },
      {
        at: 6.5,
        action: ev(id, "assistant", "check.passed", "Result checks out against your request", {
          level: "success",
        }),
      },
      {
        at: 7.2,
        action: {
          kind: "artifact",
          artifact: {
            id: `${id}-art`,
            goalId: id,
            kind: "report",
            name: short,
            meta: "handled directly by Sonnet",
          },
        },
      },
      { at: 7.4, action: goal(id, { status: "completed", progress: 1, nextAction: "—", spentUsd: 0.11 }) },
      { at: 7.6, action: ev(id, "assistant", "goal.completed", "Done — result in the artifacts dock", { level: "success" }) },
      { at: 8, action: orb("idle", "Sonnet standing by") },
      { at: 8.1, action: nodes() },
    ],
  };
}

// ── playlist ──────────────────────────────────────────────────────────────

let runCounter = 0;

export function buildPlaylist(): Array<{ scenario: Scenario; startAt: number }> {
  const suffix = runCounter++ === 0 ? "" : `-r${runCounter}`;
  return [
    { scenario: briefing(`g-briefing${suffix}`), startAt: 2 },
    { scenario: studyGuide(`g-econ${suffix}`), startAt: 14 },
    { scenario: bugfix(`g-bugfix${suffix}`), startAt: 40 },
    { scenario: emailBlast(`g-email${suffix}`), startAt: 64 },
  ];
}
