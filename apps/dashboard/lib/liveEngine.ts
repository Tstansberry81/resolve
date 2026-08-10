"use client";

// The engine: control-plane state over the /api/cp proxy (snapshot + SSE),
// exposed as an immutable EngineState via subscribe/getSnapshot. When the
// backend can't be reached the state goes `mode: "offline"` and stays empty —
// the scripted mock this replaced is deleted, not disabled.

import { AGENTS } from "./roster";
import type {
  AgentEvent,
  Approval,
  Artifact,
  Attachment,
  ConnectorHealth,
  EngineState,
  Vitals,
} from "./types";

const ALL_CONNECTORS: ConnectorHealth[] = [
  { id: "vault", label: "Vault (GitHub)", status: "down", latencyMs: 0 },
  { id: "gmail", label: "Gmail", status: "down", latencyMs: 0 },
  { id: "calendar", label: "Calendar", status: "down", latencyMs: 0 },
  { id: "notion", label: "Notion", status: "down", latencyMs: 0 },
  { id: "google", label: "Google", status: "down", latencyMs: 0 },
  { id: "finance", label: "Finance", status: "down", latencyMs: 0 },
  { id: "health", label: "Health (Watch)", status: "down", latencyMs: 0 },
  { id: "local", label: "Laptop", status: "down", latencyMs: 0 },
  { id: "web", label: "Web", status: "down", latencyMs: 0 },
];

interface CostSnapshot {
  models?: { role: string; model?: string; costTodayUsd?: number; tokensToday?: number }[];
  totalCostTodayUsd?: number;
  tokensToday?: number;
}

function vitalsFrom(
  models: Record<string, string>,
  connectors: ConnectorHealth[],
  orb: string,
  pending: number,
  costs?: CostSnapshot,
  laptopOnline = false,
): Vitals {
  const byId = new Map(connectors.map((c) => [c.id, c]));
  const costByRole = new Map((costs?.models ?? []).map((m) => [m.role, m]));
  return {
    connectors: ALL_CONNECTORS.map((c) => byId.get(c.id) ?? c),
    models: AGENTS.map((a) => ({
      role: a.id,
      model: models[a.id] ?? a.model,
      p50Ms: 0,
      costTodayUsd: costByRole.get(a.id)?.costTodayUsd ?? 0,
    })),
    queueDepth: pending,
    errorRate: 0,
    tokensToday: costs?.tokensToday ?? 0,
    costTodayUsd: costs?.totalCostTodayUsd ?? 0,
    workerStatus: orb === "executing" ? "executing" : "idle",
    laptop: laptopOnline ? "online" : "offline",
  };
}

/** What the UI shows before the first snapshot lands, and whenever the control
 *  plane is unreachable. Empty and labelled OFFLINE — never invented data. */
export const OFFLINE_STATE: EngineState = {
  mode: "offline",
  orb: "idle",
  orbCaption: "Control plane unreachable",
  goals: [],
  events: [],
  approvals: [],
  artifacts: [],
  vitals: vitalsFrom({}, [], "idle", 0),
  activeNodes: [],
  activeEdge: null,
  emergencyStopped: false,
  localExec: false,
  localAvailable: false,
  modelsByRole: {},
  morningBrief: null,
};

export class LiveEngine {
  private state: EngineState = OFFLINE_STATE;

  private listeners = new Set<() => void>();
  private es: EventSource | null = null;
  private edgeTimer: ReturnType<typeof setTimeout> | null = null;
  private started = false;

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

  private start() {
    if (this.started || typeof window === "undefined") return;
    this.started = true;
    void this.loadSnapshot();
    this.connect();
    // refresh goal/approval rows periodically; events arrive via SSE
    setInterval(() => void this.loadSnapshot(), 30_000);
  }

  private async loadSnapshot() {
    try {
      const r = await fetch("/api/cp/v1/snapshot", { cache: "no-store" });
      if (!r.ok) {
        this.commit({ mode: "offline", orbCaption: "Control plane unreachable" });
        return;
      }
      const s = await r.json();
      this.commit({
        mode: "live",
        orb: s.orb,
        orbCaption: s.orbCaption,
        activeNodes: s.activeNodes ?? [],
        goals: s.goals ?? [],
        approvals: s.approvals ?? [],
        events: (s.events ?? []).slice().reverse(),
        artifacts: s.artifacts ?? [],
        vitals: vitalsFrom(s.models ?? {}, s.connectors ?? [], s.orb,
          s.pendingApprovals ?? 0, s.costs, Boolean(s.localWorker)),
        modelsByRole: s.models ?? {},
        localExec: Boolean(s.localExec),
        localAvailable: Boolean(s.localAvailable),
        morningBrief: s.morningBrief ?? null,
      });
    } catch {
      // unreachable: say so in the header rather than leaving the last-known
      // state looking current. Existing rows stay; the 30s poll reconciles.
      this.commit({ mode: "offline", orbCaption: "Control plane unreachable" });
    }
  }

  private connect() {
    this.es = new EventSource("/api/cp/v1/events");
    this.es.onmessage = (m) => {
      let msg: { kind: string; [k: string]: unknown };
      try {
        msg = JSON.parse(m.data);
      } catch {
        return;
      }
      if (msg.kind === "event") {
        const ev = msg.event as AgentEvent;
        const patch: Partial<EngineState> = {
          events: [ev, ...this.state.events].slice(0, 140),
        };
        if (ev.edge) {
          patch.activeEdge = ev.edge;
          if (this.edgeTimer) clearTimeout(this.edgeTimer);
          this.edgeTimer = setTimeout(() => this.commit({ activeEdge: null }), 2600);
        }
        this.commit(patch);
      } else if (msg.kind === "orb") {
        const orb = msg.orb as { state: EngineState["orb"]; caption: string };
        this.commit({
          orb: orb.state,
          orbCaption: orb.caption,
          activeNodes: (msg.activeNodes as EngineState["activeNodes"]) ?? [],
          vitals: {
            ...this.state.vitals,
            workerStatus: orb.state === "executing" ? "executing" : "idle",
          },
        });
      } else if (msg.kind === "approval") {
        const a = msg.approval as Approval;
        const rest = this.state.approvals.filter((x) => x.id !== a.id);
        this.commit({ approvals: [a, ...rest] });
        // A decided approval is authoritative — pull fresh goal/orb state so the
        // sidebar mission clears without waiting on the guessed post-decide delay.
        if (a.status && a.status !== "pending") void this.loadSnapshot();
      } else if (msg.kind === "artifact") {
        const art = msg.artifact as Artifact;
        const rest = this.state.artifacts.filter((x) => x.id !== art.id);
        this.commit({ artifacts: [art, ...rest].slice(0, 40) });
      }
    };
    this.es.onopen = () => this.commit({ mode: "live" });
    this.es.onerror = () => {
      // EventSource auto-reconnects on its own; flag the gap so the header
      // reads OFFLINE while the stream is down instead of a stale LIVE
      this.commit({ mode: "offline" });
    };
  }

  decideApproval = (id: string, decision: "approved" | "rejected") => {
    void fetch(`/api/cp/v1/approvals/${id}/decide`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ decision }),
      // pull fresh goal/orb state so the sidebar mission clears out of
      // "awaiting you" instead of waiting for the 30s poll (backstop to the
      // authoritative approval event on the SSE stream)
    })
      .then(() => setTimeout(() => void this.loadSnapshot(), 1200))
      .catch(() => {
        /* decide POST failed — the 30s poll and SSE stream still reconcile */
      });
    // optimistic local update; authoritative events follow on the stream
    this.commit({
      approvals: this.state.approvals.map((a) => (a.id === id ? { ...a, status: decision } : a)),
    });
  };

  dismissGoal = (id: string) => {
    void fetch(`/api/cp/v1/goals/${id}/dismiss`, { method: "POST" })
      .then(() => setTimeout(() => void this.loadSnapshot(), 800))
      .catch(() => {
        /* the 30s poll reconciles if the POST failed */
      });
    // optimistic: drop the card immediately
    this.commit({ goals: this.state.goals.filter((g) => g.id !== id) });
  };

  submitCommand = (text: string, attachments: Attachment[] = []) => {
    void fetch("/api/cp/v1/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      // `attachments` omitted entirely when empty — the control plane defaults
      // it, and an empty array on every turn is noise in the request log.
      body: JSON.stringify(attachments.length ? { text, attachments } : { text }),
    }).then(() => setTimeout(() => void this.loadSnapshot(), 1500));
  };

  emergencyStop = () => {
    // real backend halt: the executor drops queued steps until resume
    void fetch("/api/cp/v1/stop", { method: "POST" });
    this.commit({
      emergencyStopped: true,
      orb: "idle",
      orbCaption: "EMERGENCY STOP — executor halted",
    });
  };

  resume = () => {
    void fetch("/api/cp/v1/resume", { method: "POST" });
    this.commit({ emergencyStopped: false, orbCaption: "Sonnet standing by" });
    void this.loadSnapshot();
  };

  setLocalExec = (on: boolean) => {
    void fetch("/api/cp/v1/settings/local_exec", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ on }),
    });
    this.commit({ localExec: on }); // optimistic; snapshot confirms
  };
}
