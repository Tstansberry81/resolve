"use client";

// Live engine: same store contract as the mock, fed by the control plane
// through the /api/cp proxy (snapshot + SSE). Components can't tell the
// difference — that was the whole design bet.

import { AGENTS } from "./roster";
import type {
  AgentEvent,
  Approval,
  Artifact,
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
  { id: "local", label: "Laptop", status: "down", latencyMs: 0 },
  { id: "web", label: "Web", status: "down", latencyMs: 0 },
];

interface CostSnapshot {
  models?: { role: string; model?: string; costTodayUsd?: number; tokensToday?: number }[];
  totalCostTodayUsd?: number;
  tokensToday?: number;
}

function vitalsFrom(
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
      model: a.model,
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

export class LiveEngine {
  private state: EngineState = {
    mode: "live",
    orb: "idle",
    orbCaption: "Sonnet standing by",
    goals: [],
    events: [],
    approvals: [],
    artifacts: [],
    vitals: vitalsFrom([], "idle", 0),
    activeNodes: [],
    activeEdge: null,
    emergencyStopped: false,
    localExec: false,
    localAvailable: false,
    morningBrief: null,
  };

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
      if (!r.ok) return;
      const s = await r.json();
      this.commit({
        orb: s.orb,
        orbCaption: s.orbCaption,
        activeNodes: s.activeNodes ?? [],
        goals: s.goals ?? [],
        approvals: s.approvals ?? [],
        events: (s.events ?? []).slice().reverse(),
        artifacts: s.artifacts ?? [],
        vitals: vitalsFrom(s.connectors ?? [], s.orb, s.pendingApprovals ?? 0, s.costs,
          Boolean(s.localWorker)),
        localExec: Boolean(s.localExec),
        localAvailable: Boolean(s.localAvailable),
        morningBrief: s.morningBrief ?? null,
      });
    } catch {
      // snapshot refresh is best-effort; SSE keeps flowing
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
    this.es.onerror = () => {
      // EventSource auto-reconnects; nothing to do
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

  submitCommand = (text: string) => {
    void fetch("/api/cp/v1/command", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
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
