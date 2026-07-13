"use client";

// Engine facade: probes the control plane once and picks LIVE when it
// answers, otherwise falls back to the deterministic mock. Components only
// ever see the shared EngineState contract.

import { useSyncExternalStore } from "react";
import { engine as mockEngine } from "./engine";
import { LiveEngine } from "./liveEngine";
import type { EngineState } from "./types";

type EngineLike = {
  subscribe: (fn: () => void) => () => void;
  getSnapshot: () => EngineState;
  decideApproval: (id: string, decision: "approved" | "rejected") => void;
  submitCommand: (text: string) => void;
  emergencyStop: () => void;
  resume: () => void;
  setLocalExec: (on: boolean) => void;
};

const listeners = new Set<() => void>();
let current: EngineLike | null = null;
let detach: (() => void) | null = null;
let probing = false;

const IDLE_STATE: EngineState = mockEngine.getSnapshot();

function attach(target: EngineLike) {
  detach?.();
  current = target;
  detach = target.subscribe(() => listeners.forEach((fn) => fn()));
  listeners.forEach((fn) => fn());
}

async function probe() {
  if (probing || current) return;
  probing = true;
  try {
    const r = await fetch("/api/cp/healthz", { signal: AbortSignal.timeout(2000) });
    if (r.ok) {
      attach(new LiveEngine() as EngineLike);
      return;
    }
  } catch {
    // no control plane reachable — mock it is
  }
  attach(mockEngine as EngineLike);
}

export const engine = {
  decideApproval: (id: string, d: "approved" | "rejected") => current?.decideApproval(id, d),
  submitCommand: (t: string) => current?.submitCommand(t),
  emergencyStop: () => current?.emergencyStop(),
  resume: () => current?.resume(),
  setLocalExec: (on: boolean) => current?.setLocalExec(on),
  getSnapshot: (): EngineState => current?.getSnapshot() ?? IDLE_STATE,
  subscribe: (fn: () => void) => {
    listeners.add(fn);
    void probe();
    return () => listeners.delete(fn);
  },
};

export function useEngine(): EngineState {
  return useSyncExternalStore(engine.subscribe, engine.getSnapshot, () => IDLE_STATE);
}
