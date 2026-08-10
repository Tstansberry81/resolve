"use client";

// Engine facade. There is exactly one engine now: the live control plane.
//
// This used to probe /healthz and fall back to a scripted mock (lib/engine.ts +
// lib/scenarios.ts, ~1k lines of demo) whenever the backend didn't answer. That
// shipped a fake RESOLVE to production and made "is it broken?" ambiguous — a
// dead backend looked like a working system playing a canned scenario. The
// mock is gone; an unreachable control plane now reads OFFLINE and shows
// nothing rather than something invented.

import { useSyncExternalStore } from "react";
import { LiveEngine, OFFLINE_STATE } from "./liveEngine";
import type { Attachment, EngineState } from "./types";

const listeners = new Set<() => void>();
let live: LiveEngine | null = null;
let detach: (() => void) | null = null;

function ensure(): LiveEngine {
  if (!live) {
    live = new LiveEngine();
    detach = live.subscribe(() => listeners.forEach((fn) => fn()));
  }
  return live;
}

export const engine = {
  decideApproval: (id: string, d: "approved" | "rejected") => live?.decideApproval(id, d),
  submitCommand: (t: string, attachments: Attachment[] = []) =>
    live?.submitCommand(t, attachments),
  dismissGoal: (id: string) => live?.dismissGoal(id),
  emergencyStop: () => live?.emergencyStop(),
  resume: () => live?.resume(),
  setLocalExec: (on: boolean) => live?.setLocalExec(on),
  getSnapshot: (): EngineState => live?.getSnapshot() ?? OFFLINE_STATE,
  subscribe: (fn: () => void) => {
    listeners.add(fn);
    ensure();
    return () => {
      listeners.delete(fn);
      if (listeners.size === 0) {
        detach?.();
        detach = null;
      }
    };
  },
};

export function useEngine(): EngineState {
  // server render has no control plane in reach — start from OFFLINE and let
  // the first snapshot flip it to live
  return useSyncExternalStore(engine.subscribe, engine.getSnapshot, () => OFFLINE_STATE);
}
