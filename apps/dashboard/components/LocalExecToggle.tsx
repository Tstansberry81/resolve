"use client";

// Header toggle: run executor steps on the local model (Qwen on Trav's box)
// instead of Opus. The planner always stays on Opus. Only shown in live mode
// (it drives the real control plane). When the local box is off, the backend
// silently falls back to Opus per step.

import { engine, useEngine } from "@/lib/useEngine";

export function LocalExecToggle() {
  const { localExec, localAvailable, mode } = useEngine();
  if (mode !== "live") return null;

  const title = localAvailable
    ? "Executor model — tap to switch between Opus and your local Qwen (planner stays Opus)"
    : "Local model not configured (LOCAL_MODEL_URL). You can still toggle; steps fall back to Opus until your box is reachable.";

  return (
    <button
      className="exec-toggle"
      data-local={localExec}
      data-available={localAvailable}
      title={title}
      onClick={() => engine.setLocalExec(!localExec)}
    >
      <span className="exec-dot" />
      exec: {localExec ? "local" : "opus"}
    </button>
  );
}
