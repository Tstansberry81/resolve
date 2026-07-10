"use client";

import { useEngine, engine } from "@/lib/useEngine";

function Clock() {
  return (
    <span className="clock" suppressHydrationWarning>
      {new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
    </span>
  );
}

export default function CommandCenter() {
  const state = useEngine();

  return (
    <main className="shell">
      <header className="shell-header">
        <div className="brand">
          <span className="brand-sigil" aria-hidden />
          <span className="brand-name">RESOLVE</span>
          <span className="badge badge-mock">MOCK DATA</span>
        </div>
        <div className="header-right">
          <span className="badge">autonomy · execute</span>
          <Clock />
          {state.emergencyStopped ? (
            <button className="btn btn-resume" onClick={() => engine.resume()}>
              RESUME
            </button>
          ) : (
            <button className="btn btn-stop" onClick={() => engine.emergencyStop()}>
              EMERGENCY STOP
            </button>
          )}
        </div>
      </header>

      <section className="grid">
        <div className="panel area-missions">
          <div className="panel-title"><span className="dot" />Missions</div>
          <p className="placeholder">{state.goals.length} goals tracked</p>
        </div>
        <div className="panel area-core">
          <div className="panel-title"><span className="dot" />Command core</div>
          <p className="placeholder">{state.orb} — {state.orbCaption}</p>
        </div>
        <div className="panel area-constellation">
          <div className="panel-title"><span className="dot" />Agent constellation</div>
          <p className="placeholder">{state.activeNodes.length} nodes active</p>
        </div>
        <div className="panel area-approvals">
          <div className="panel-title"><span className="dot" />Approvals</div>
          <p className="placeholder">
            {state.approvals.filter((a) => a.status === "pending").length} pending
          </p>
        </div>
        <div className="panel area-timeline">
          <div className="panel-title"><span className="dot" />Live execution</div>
          <p className="placeholder">{state.events.length} events</p>
        </div>
        <div className="vitals-stack">
          <div className="panel area-vitals">
            <div className="panel-title"><span className="dot" />System vitals</div>
            <p className="placeholder">worker: {state.vitals.workerStatus}</p>
          </div>
          <div className="panel area-artifacts">
            <div className="panel-title"><span className="dot" />Artifacts</div>
            <p className="placeholder">{state.artifacts.length} produced</p>
          </div>
        </div>
      </section>
    </main>
  );
}
