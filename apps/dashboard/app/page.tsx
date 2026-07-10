"use client";

import { useEngine, engine } from "@/lib/useEngine";
import { CommandCore } from "@/components/CommandCore";
import { MissionRail } from "@/components/MissionRail";
import { Constellation } from "@/components/Constellation";
import { Timeline } from "@/components/Timeline";
import { ApprovalInbox } from "@/components/ApprovalInbox";
import { Vitals } from "@/components/Vitals";
import { ArtifactsDock } from "@/components/ArtifactsDock";

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
        <MissionRail />
        <CommandCore />
        <Constellation />
        <ApprovalInbox />
        <Timeline />
        <div className="vitals-stack">
          <Vitals />
          <ArtifactsDock />
        </div>
      </section>
    </main>
  );
}
