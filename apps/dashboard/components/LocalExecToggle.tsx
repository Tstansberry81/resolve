"use client";

// Header toggle: run executor steps on the local model (Qwen on Trav's box)
// instead of the cloud executor. The planner always stays on its own model. Only
// shown in live mode (it drives the real control plane). When the local box is
// off, the backend silently falls back to the cloud model per step.
//
// The cloud model is READ FROM state.modelsByRole, never named here — this pill
// hardcoded "opus" and went on saying it after the executor moved to Sonnet 5.

import { engine, useEngine } from "@/lib/useEngine";
import { modelLabel } from "@/lib/roster";

export function LocalExecToggle() {
  const { localExec, localAvailable, mode, modelsByRole } = useEngine();
  if (mode !== "live") return null;

  const cloud = modelLabel(modelsByRole.executor);
  const title = localAvailable
    ? `Executor model — tap to switch between ${cloud} and your local Qwen (planner stays on ${modelLabel(modelsByRole.planner)})`
    : `Local model not configured (LOCAL_MODEL_URL). You can still toggle; steps fall back to ${cloud} until your box is reachable.`;

  return (
    <button
      className="exec-toggle"
      data-local={localExec}
      data-available={localAvailable}
      title={title}
      onClick={() => engine.setLocalExec(!localExec)}
    >
      <span className="exec-dot" />
      exec: {localExec ? "local" : cloud.toLowerCase()}
    </button>
  );
}
