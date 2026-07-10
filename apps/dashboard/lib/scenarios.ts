import type {
  Approval,
  Artifact,
  EventLevel,
  Goal,
  NodeId,
  OrbState,
  Vitals,
} from "./types";

// Scripted, deterministic scenarios modeled on the "first production goals"
// in docs/JARVIS_SYSTEM_PLAN.md §14.

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

// ── helpers ────────────────────────────────────────────────────────────────────

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

// ── scenario 1: morning briefing (read-only) ─────────────────────────

function briefing(id = "g-briefing"): Scenario {
  return {
    goal: {
      id,
      objective: "Morning briefing: agenda, inbox triage, market snapshot",
      category: "personal",
      status: "planning",
      autonomyMode: "observe",
      progress: 0.02,
      budgetUsd: 0.5,
      spentUsd: 0,
      deadline: null,
      nextAction: "Compile plan",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("thinking", "Planning the morning briefing") },
      { at: 0.2, action: nodes("planner") },
      {
        at: 0.4,
        action: ev(id, "planner", "plan.created", "Plan v1: 4 read-only tasks", {
          detail: "calendar.read → gmail.triage → markets.read → synthesize",
        }),
      },
      { at: 1.5, action: goal(id, { status: "active", progress: 0.1, nextAction: "Read calendar" }) },
      { at: 1.6, action: orb("executing", "Reading today's calendar") },
      { at: 1.7, action: nodes("planner", "calendar") },
      {
        at: 2,
        action: ev(id, "calendar", "tool.call", "calendar.read — 4 events today", {
          edge: { from: "planner", to: "calendar" },
          detail: "ECON 2010 lecture 10:00 · gym 17:30 · 2 more",
        }),
      },
      { at: 5, action: nodes("planner", "gmail") },
      {
        at: 5.2,
        action: ev(id, "gmail", "tool.call", "gmail.triage — 23 unread, 3 need action", {
          edge: { from: "planner", to: "gmail" },
          detail: "flagged: advisor reply, Canvas due-date change, Render invoice",
        }),
      },
      { at: 7.5, action: goal(id, { progress: 0.55, nextAction: "Market snapshot" }) },
      { at: 8, action: nodes("planner", "web") },
      {
        at: 8.2,
        action: ev(id, "web", "tool.call", "markets.read — SPY +0.4%, BTC flat", {
          edge: { from: "planner", to: "web" },
        }),
      },
      { at: 10.5, action: nodes("planner", "evaluator") },
      {
        at: 10.8,
        action: ev(id, "evaluator", "verify.passed", "Coverage check: all 3 sources present", {
          level: "success",
          edge: { from: "planner", to: "evaluator" },
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
      { at: 11.8, action: goal(id, { status: "completed", progress: 1, nextAction: "—", spentUsd: 0.07 }) },
      {
        at: 12,
        action: ev(id, "core", "goal.completed", "Briefing delivered — $0.07 of $0.50 budget", {
          level: "success",
        }),
      },
      { at: 12.2, action: orb("idle", "Standing by") },
      { at: 12.3, action: nodes() },
    ],
  };
}

// ── scenario 2: study guide ─────────────────────────────────────────

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
      nextAction: "Collect sources",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("thinking", "Decomposing the study-guide goal") },
      { at: 0.1, action: nodes("planner") },
      {
        at: 0.5,
        action: ev(id, "planner", "plan.created", "Plan v1: 7-task DAG with citation gate", {
          detail: "collect → extract → outline → synthesize → cite-check → quiz → coverage eval",
        }),
      },
      { at: 2, action: goal(id, { status: "active", progress: 0.08 }) },
      { at: 2.1, action: orb("executing", "Collecting course sources") },
      { at: 2.2, action: nodes("researcher", "canvas") },
      {
        at: 2.5,
        action: ev(id, "researcher", "tool.call", "canvas.files — 3 lecture decks, 2 PDFs", {
          edge: { from: "researcher", to: "canvas" },
        }),
      },
      {
        at: 6,
        action: ev(id, "researcher", "extract.done", "Extracted 148 passages with provenance", {
          detail: "model: gemini-3.1-flash-lite · $0.11",
        }),
      },
      { at: 6.2, action: goal(id, { progress: 0.35, nextAction: "Synthesize outline", spentUsd: 0.11 }) },
      { at: 8.5, action: nodes("researcher", "planner") },
      {
        at: 9,
        action: ev(id, "planner", "synthesis.done", "Outline synthesized across 3 chapters", {
          detail: "model: gpt-5.6-sol · high effort",
          edge: { from: "planner", to: "researcher" },
        }),
      },
      { at: 12, action: nodes("evaluator") },
      {
        at: 12.5,
        action: ev(id, "evaluator", "verify.failed", "Citation check: 2 claims missing sources", {
          level: "warn",
          detail: "elasticity example (ch.4), tax incidence figure (ch.5)",
          edge: { from: "evaluator", to: "researcher" },
        }),
      },
      { at: 13, action: goal(id, { progress: 0.55, nextAction: "Repair citations", blocker: null }) },
      { at: 15.5, action: nodes("researcher", "canvas") },
      {
        at: 16,
        action: ev(id, "researcher", "repair.done", "Both claims re-sourced from lecture 9", {
          level: "success",
          edge: { from: "researcher", to: "canvas" },
        }),
      },
      { at: 18.5, action: nodes("evaluator") },
      {
        at: 19,
        action: ev(id, "evaluator", "verify.passed", "Citation + coverage checks green · quiz validates", {
          level: "success",
          edge: { from: "evaluator", to: "planner" },
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
      { at: 20.4, action: goal(id, { status: "completed", progress: 1, spentUsd: 1.84, nextAction: "—" }) },
      {
        at: 20.6,
        action: ev(id, "core", "goal.completed", "Study guide saved to Notion — $1.84 of $3.00", {
          level: "success",
        }),
      },
      { at: 21, action: orb("idle", "Standing by") },
      { at: 21.1, action: nodes() },
    ],
  };
}

// ── scenario 3: bug-fix draft PR ──────────────────────────────────────

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
      nextAction: "Reproduce",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("thinking", "Reading the failing repo") },
      { at: 0.1, action: nodes("coder", "github") },
      {
        at: 0.4,
        action: ev(id, "coder", "tool.call", "github.checkout — isolated worktree created", {
          edge: { from: "coder", to: "github" },
        }),
      },
      {
        at: 3,
        action: ev(id, "coder", "repro.confirmed", "Reproduced: stale lock persists after SIGKILL", {
          detail: "test_sync.py::test_lock_recovery fails as expected",
        }),
      },
      { at: 3.2, action: goal(id, { status: "active", progress: 0.3, nextAction: "Implement fix" }) },
      { at: 3.3, action: orb("executing", "Implementing lock-recovery fix") },
      {
        at: 7,
        action: ev(id, "coder", "commit.created", "Fix: detect and clear stale index.lock with age guard", {
          detail: "model: gpt-5.3-codex · 2 files, +38 −6",
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
        action: ev(id, "reviewer", "review.done", "Reviewer (opus-4-8): approve with 1 nit — race window comment", {
          level: "success",
          edge: { from: "reviewer", to: "coder" },
          detail: "different model family from implementer, per policy",
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
      { at: 18.2, action: orb("waiting", "Waiting on merge approval") },
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
            goal(id, { status: "completed", progress: 1, nextAction: "—", spentUsd: 2.6 }),
            orb("idle", "Standing by"),
            nodes(),
          ],
          onReject: [
            ev(id, "core", "pr.held", "Merge rejected — PR stays in draft", { level: "warn" }),
            goal(id, { status: "completed", progress: 0.95, nextAction: "PR awaiting manual merge", spentUsd: 2.6 }),
            orb("idle", "Standing by"),
            nodes(),
          ],
        },
      },
    ],
  };
}

// ── scenario 4: email follow-ups ──────────────────────────────────────

function emailFollowups(id = "g-email"): Scenario {
  return {
    goal: {
      id,
      objective: "Draft follow-ups for 3 stale threads; send only with approval",
      category: "email",
      status: "planning",
      autonomyMode: "execute",
      progress: 0.02,
      budgetUsd: 1,
      spentUsd: 0,
      deadline: null,
      nextAction: "Scan threads",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("executing", "Scanning stale email threads") },
      { at: 0.1, action: nodes("planner", "gmail") },
      {
        at: 0.4,
        action: ev(id, "gmail", "tool.call", "gmail.threads — 3 threads stale > 5 days", {
          edge: { from: "planner", to: "gmail" },
        }),
      },
      { at: 3, action: goal(id, { status: "active", progress: 0.4, nextAction: "Draft replies" }) },
      {
        at: 5,
        action: ev(id, "planner", "drafts.created", "3 follow-up drafts written in your voice", {
          detail: "model: claude-sonnet-4-6 · tone: brief, warm",
        }),
      },
      {
        at: 5.5,
        action: {
          kind: "artifact",
          artifact: {
            id: `${id}-art1`,
            goalId: id,
            kind: "draft",
            name: "3 follow-up drafts",
            meta: "advisor · landlord · study group",
          },
        },
      },
      {
        at: 6.1,
        action: goal(id, { status: "waiting_approval", progress: 0.75, nextAction: "Awaiting send approval", blocker: "Needs your approval" }),
      },
      { at: 6.3, action: orb("waiting", "Waiting on send approval") },
      {
        at: 6.5,
        action: {
          kind: "approval",
          gate: true,
          approval: {
            id: `${id}-appr1`,
            goalId: id,
            actionSummary: "Send follow-up email to advisor",
            risk: "communication_send",
            preview: [
              "to: advisor@university.edu",
              "subject: Re: thesis direction — quick follow-up",
              "“Just circling back on the outline I sent Monday…”",
              "2 more drafts queued behind this one",
            ],
            recipient: "advisor@university.edu",
            undoWindow: "30s unsend window",
            status: "pending",
          },
          onApprove: [
            ev(id, "gmail", "email.sent", "Follow-up sent to advisor — undo for 30s", {
              level: "success",
              edge: { from: "core", to: "gmail" },
            }),
            goal(id, { status: "completed", progress: 1, nextAction: "—", spentUsd: 0.12 }),
            orb("idle", "Standing by"),
            nodes(),
          ],
          onReject: [
            ev(id, "core", "email.held", "Send rejected — drafts stay in outbox", { level: "warn" }),
            goal(id, { status: "paused", progress: 0.8, nextAction: "Drafts held", blocker: "Send rejected" }),
            orb("idle", "Standing by"),
            nodes(),
          ],
        },
      },
    ],
  };
}

// ── ad-hoc command scenario ─────────────────────────────────────────

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
      nextAction: "Intake",
      blocker: null,
    },
    steps: [
      { at: 0, action: orb("listening", "Heard you — parsing the request") },
      { at: 0.8, action: orb("thinking", "Typing the goal and compiling policy") },
      { at: 0.9, action: nodes("planner") },
      {
        at: 1.4,
        action: ev(id, "planner", "goal.typed", `Goal accepted: ${short}`, {
          detail: "autonomy: assist · budget $2.00 · policy compiled",
        }),
      },
      { at: 2.4, action: goal(id, { status: "active", progress: 0.3, nextAction: "Research" }) },
      { at: 2.5, action: orb("executing", "Working the request") },
      { at: 2.6, action: nodes("planner", "researcher", "web") },
      {
        at: 3.2,
        action: ev(id, "researcher", "tool.call", "web.search — gathering evidence", {
          edge: { from: "researcher", to: "web" },
        }),
      },
      { at: 6.5, action: nodes("evaluator") },
      {
        at: 7,
        action: ev(id, "evaluator", "verify.passed", "Result passes success criteria", {
          level: "success",
          edge: { from: "evaluator", to: "researcher" },
        }),
      },
      {
        at: 7.6,
        action: {
          kind: "artifact",
          artifact: {
            id: `${id}-art`,
            goalId: id,
            kind: "report",
            name: short,
            meta: "ad-hoc request · evidence attached",
          },
        },
      },
      { at: 7.8, action: goal(id, { status: "completed", progress: 1, nextAction: "—", spentUsd: 0.21 }) },
      { at: 8, action: ev(id, "core", "goal.completed", "Done — result in the artifacts dock", { level: "success" }) },
      { at: 8.4, action: orb("idle", "Standing by") },
      { at: 8.5, action: nodes() },
    ],
  };
}

// ── playlist ────────────────────────────────────────────────────────

let runCounter = 0;

export function buildPlaylist(): Array<{ scenario: Scenario; startAt: number }> {
  const suffix = runCounter++ === 0 ? "" : `-r${runCounter}`;
  return [
    { scenario: briefing(`g-briefing${suffix}`), startAt: 2 },
    { scenario: studyGuide(`g-econ${suffix}`), startAt: 14 },
    { scenario: bugfix(`g-bugfix${suffix}`), startAt: 40 },
    { scenario: emailFollowups(`g-email${suffix}`), startAt: 66 },
  ];
}
