"use client";

// Deterministic mock event engine.
//
// Plays scripted scenarios (lib/scenarios.ts) on real timers and exposes an
// immutable snapshot via subscribe/getSnapshot for useSyncExternalStore.
// The control-plane SSE feed will replace this class behind the same
// EngineState contract — components never know the difference.

import type {
  Action,
  Scenario,
} from "./scenarios";
import { buildPlaylist, makeCommandScenario } from "./scenarios";
import type {
  AgentEvent,
  Approval,
  EngineState,
  Goal,
  NodeId,
  Vitals,
} from "./types";

const MAX_EVENTS = 140;

// deterministic jitter for vitals
function lcg(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

const INITIAL_VITALS: Vitals = {
  connectors: [
    { id: "vault", label: "Vault (GitHub)", status: "healthy", latencyMs: 350 },
    { id: "gmail", label: "Gmail", status: "healthy", latencyMs: 210 },
    { id: "calendar", label: "Calendar", status: "healthy", latencyMs: 160 },
    { id: "notion", label: "Notion", status: "healthy", latencyMs: 240 },
    { id: "github", label: "GitHub", status: "healthy", latencyMs: 180 },
    { id: "canvas", label: "Canvas", status: "degraded", latencyMs: 640 },
    { id: "web", label: "Web Search", status: "healthy", latencyMs: 300 },
  ],
  models: [
    { role: "assistant", model: "claude-sonnet-4-6", p50Ms: 1400, costTodayUsd: 0.31 },
    { role: "router", model: "gpt-5.6-luna", p50Ms: 320, costTodayUsd: 0.04 },
    { role: "planner", model: "gpt-5.6-sol", p50Ms: 3800, costTodayUsd: 0.22 },
    { role: "executor", model: "claude-opus-4-8", p50Ms: 4600, costTodayUsd: 0.29 },
    { role: "coder", model: "claude-opus-4-8", p50Ms: 5200, costTodayUsd: 0.47 },
    { role: "reviewer", model: "claude-opus-4-8", p50Ms: 4100, costTodayUsd: 0.18 },
  ],
  queueDepth: 0,
  errorRate: 0.006,
  tokensToday: 182_400,
  costTodayUsd: 1.22,
  workerStatus: "idle",
};

class MockEngine {
  private state: EngineState = {
    orb: "idle",
    orbCaption: "Sonnet standing by",
    goals: [],
    events: [],
    approvals: [],
    artifacts: [],
    vitals: INITIAL_VITALS,
    activeNodes: [],
    activeEdge: null,
    emergencyStopped: false,
  };

  private listeners = new Set<() => void>();
  private timers = new Set<ReturnType<typeof setTimeout>>();
  private vitalsTimer: ReturnType<typeof setInterval> | null = null;
  private edgeTimer: ReturnType<typeof setTimeout> | null = null;
  private eventSeq = 1;
  private rand = lcg(42);
  private started = false;
  /** approvals whose scenario is blocked, keyed by approval id */
  private gates = new Map<
    string,
    { onApprove: Action[]; onReject: Action[]; resume: () => void }
  >();

  // ── store contract ────────────────────────────────────────────

  subscribe = (fn: () => void) => {
    this.listeners.add(fn);
    this.start();
    return () => this.listeners.delete(fn);
  };

  getSnapshot = (): EngineState => this.state;

  private commit(patch: Partial<EngineState>) {
    this.state = { ...this.state, ...patch };
    this.listeners.forEach((fn) => fn());
  }

  // ── lifecycle ─────────────────────────────────────────────────

  private start() {
    if (this.started || typeof window === "undefined") return;
    this.started = true;
    this.runPlaylist();
    this.vitalsTimer = setInterval(() => this.tickVitals(), 2500);
  }

  private runPlaylist() {
    for (const { scenario, startAt } of buildPlaylist()) {
      this.schedule(startAt * 1000, () => this.runScenario(scenario));
    }
    // restart the whole show after a quiet stretch, clearing finished goals
    // so the rail doesn't fill with duplicates across loops
    this.schedule(150_000, () => {
      if (this.state.emergencyStopped) return;
      this.commit({
        goals: this.state.goals.filter(
          (g) => g.status !== "completed" && g.status !== "failed",
        ),
      });
      this.runPlaylist();
    });
  }

  private schedule(ms: number, fn: () => void) {
    const t = setTimeout(() => {
      this.timers.delete(t);
      if (!this.state.emergencyStopped) fn();
    }, ms);
    this.timers.add(t);
  }

  private runScenario(sc: Scenario) {
    if (this.state.goals.some((g) => g.id === sc.goal.id)) return;
    this.commit({ goals: [...this.state.goals, { ...sc.goal }] });
    this.playSteps(sc.steps, 0);
  }

  private playSteps(steps: Array<{ at: number; action: Action }>, from: number) {
    if (from >= steps.length) return;
    const prevAt = from === 0 ? 0 : steps[from - 1].at;
    const step = steps[from];
    this.schedule((step.at - prevAt) * 1000, () => {
      const blocked = this.apply(step.action, () =>
        this.playSteps(steps, from + 1),
      );
      if (!blocked) this.playSteps(steps, from + 1);
    });
  }

  /** returns true when the action gates the scenario until an approval decision */
  private apply(action: Action, resume: () => void): boolean {
    switch (action.kind) {
      case "orb":
        this.commit({ orb: action.state, orbCaption: action.caption });
        return false;
      case "nodes":
        this.commit({ activeNodes: action.ids });
        return false;
      case "event": {
        this.pushEvent(action);
        return false;
      }
      case "goal":
        this.patchGoal(action.id, action.patch);
        return false;
      case "artifact":
        this.commit({
          artifacts: [
            { ...action.artifact, ts: Date.now() },
            ...this.state.artifacts,
          ].slice(0, 24),
        });
        return false;
      case "vitals":
        this.commit({ vitals: { ...this.state.vitals, ...action.patch } });
        return false;
      case "approval": {
        this.commit({
          approvals: [action.approval, ...this.state.approvals],
        });
        this.pushEvent({
          actor: "core",
          type: "approval.requested",
          level: "approval",
          summary: action.approval.actionSummary,
          detail: `risk: ${action.approval.risk} — waiting on you`,
          goalId: action.approval.goalId,
        });
        if (action.gate) {
          this.gates.set(action.approval.id, {
            onApprove: action.onApprove ?? [],
            onReject: action.onReject ?? [],
            resume,
          });
          return true;
        }
        return false;
      }
    }
  }

  private pushEvent(a: {
    actor: NodeId;
    type: string;
    level: AgentEvent["level"];
    summary: string;
    detail?: string | null;
    edge?: AgentEvent["edge"];
    goalId?: string | null;
  }) {
    const ev: AgentEvent = {
      id: this.eventSeq++,
      ts: Date.now(),
      goalId: a.goalId ?? null,
      type: a.type,
      actor: a.actor,
      summary: a.summary,
      detail: a.detail ?? null,
      level: a.level,
      edge: a.edge ?? null,
    };
    const patch: Partial<EngineState> = {
      events: [ev, ...this.state.events].slice(0, MAX_EVENTS),
    };
    if (ev.edge) {
      patch.activeEdge = ev.edge;
      if (this.edgeTimer) clearTimeout(this.edgeTimer);
      this.edgeTimer = setTimeout(() => this.commit({ activeEdge: null }), 2600);
    }
    this.commit(patch);
  }

  private patchGoal(id: string, patch: Partial<Goal>) {
    this.commit({
      goals: this.state.goals.map((g) => (g.id === id ? { ...g, ...patch } : g)),
    });
  }

  private tickVitals() {
    if (this.state.emergencyStopped) return;
    const r = this.rand;
    const v = this.state.vitals;
    const executing = this.state.orb === "executing";
    this.commit({
      vitals: {
        ...v,
        connectors: v.connectors.map((c) => ({
          ...c,
          latencyMs: Math.max(
            60,
            Math.round(c.latencyMs + (r() - 0.5) * (c.status === "degraded" ? 220 : 60)),
          ),
        })),
        models: v.models.map((m) => ({
          ...m,
          p50Ms: Math.max(120, Math.round(m.p50Ms + (r() - 0.5) * 400)),
          costTodayUsd: +(m.costTodayUsd + (executing ? r() * 0.012 : 0)).toFixed(3),
        })),
        queueDepth: Math.max(
          0,
          this.state.goals.filter((g) => g.status === "active").length +
            Math.round(r() * 2) - 1,
        ),
        errorRate: +Math.max(0, v.errorRate + (r() - 0.52) * 0.002).toFixed(4),
        tokensToday: v.tokensToday + (executing ? Math.round(r() * 4200) : Math.round(r() * 300)),
        costTodayUsd: +(v.costTodayUsd + (executing ? r() * 0.02 : 0)).toFixed(3),
        workerStatus: this.state.emergencyStopped
          ? "stopped"
          : executing
            ? "executing"
            : "idle",
      },
    });
  }

  // ── user actions ──────────────────────────────────────────────

  decideApproval = (id: string, decision: "approved" | "rejected") => {
    const gate = this.gates.get(id);
    this.commit({
      approvals: this.state.approvals.map((a) =>
        a.id === id ? { ...a, status: decision } : a,
      ),
    });
    this.pushEvent({
      actor: "core",
      type: `approval.${decision}`,
      level: decision === "approved" ? "success" : "warn",
      summary:
        decision === "approved"
          ? "You approved the pending action"
          : "You rejected the pending action",
    });
    if (gate) {
      this.gates.delete(id);
      const branch = decision === "approved" ? gate.onApprove : gate.onReject;
      branch.forEach((action) => this.apply(action, () => {}));
      gate.resume();
    }
  };

  submitCommand = (text: string) => {
    const sc = makeCommandScenario(text, `cmd-${Date.now()}`);
    this.runScenario(sc);
  };

  emergencyStop = () => {
    this.timers.forEach((t) => clearTimeout(t));
    this.timers.clear();
    this.gates.clear();
    this.commit({
      emergencyStopped: true,
      orb: "idle",
      orbCaption: "EMERGENCY STOP — all execution halted",
      activeNodes: [],
      activeEdge: null,
      goals: this.state.goals.map((g) =>
        g.status === "active" || g.status === "planning"
          ? { ...g, status: "paused", blocker: "Emergency stop" }
          : g,
      ),
      vitals: { ...this.state.vitals, workerStatus: "stopped", queueDepth: 0 },
    });
    this.pushEvent({
      actor: "core",
      type: "system.emergency_stop",
      level: "error",
      summary: "Emergency stop engaged — workers halted, leases released",
    });
  };

  resume = () => {
    this.commit({
      emergencyStopped: false,
      orbCaption: "Sonnet standing by",
      vitals: { ...this.state.vitals, workerStatus: "idle" },
    });
    this.pushEvent({
      actor: "core",
      type: "system.resumed",
      level: "success",
      summary: "Execution re-enabled",
    });
    this.runPlaylist();
  };
}

export const engine = new MockEngine();
