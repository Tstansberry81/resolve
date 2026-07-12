"use client";

import { useEngine, engine } from "@/lib/useEngine";
import { Starfield } from "@/components/Starfield";
import { ChatStrip } from "@/components/ChatStrip";
import { CommandCore } from "@/components/CommandCore";
import { Constellation } from "@/components/Constellation";
import { Sidebar } from "@/components/Sidebar";
import { ApprovalBanners } from "@/components/ApprovalBanners";
import { VitalsDropdown } from "@/components/VitalsDropdown";
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
    <>
      <Starfield />
      <ApprovalBanners />

      <main className="v2-app">
        <header className="v2-header">
          <VitalsDropdown />
          <div className="brand">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img src="/icon.svg" alt="" width={22} height={22} style={{ borderRadius: 6 }} />
            <span className="brand-name">RESOLVE</span>
            {state.mode === "live" ? (
            <span className="badge badge-live">LIVE</span>
          ) : (
            <span className="badge badge-mock">MOCK DATA</span>
          )}
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

        <div className="v2-main">
          <Sidebar />
          <section className="v2-center">
            <CommandCore />
            <ChatStrip />
            <Constellation />
          </section>
        </div>
      </main>

      <ArtifactsDock />
    </>
  );
}
