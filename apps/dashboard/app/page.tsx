"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useEngine, engine } from "@/lib/useEngine";
import { Starfield } from "@/components/Starfield";
import { ChatStrip } from "@/components/ChatStrip";
import { CommandCore } from "@/components/CommandCore";
import { Constellation } from "@/components/Constellation";
import { Sidebar } from "@/components/Sidebar";
import { ApprovalBanners } from "@/components/ApprovalBanners";
import { VitalsDropdown } from "@/components/VitalsDropdown";
import { ArtifactsDock } from "@/components/ArtifactsDock";
import { WakeWord } from "@/components/WakeWord";
import { LocalExecToggle } from "@/components/LocalExecToggle";

function Clock() {
  // This used to be a bare `new Date()` in the JSX, which is not a clock -- it's
  // the time of the last React render. It only advanced when something else in
  // the page re-rendered, so it sat a few minutes behind and drifted further the
  // longer the tab stayed open.
  const [now, setNow] = useState<Date | null>(null);

  useEffect(() => {
    setNow(new Date());
    // Align to the next minute boundary before starting the interval. A plain
    // 60s tick started mid-minute is always up to 59s stale -- which is the same
    // "a bit off" as before, just less of it.
    let tick: ReturnType<typeof setInterval> | undefined;
    const align = setTimeout(
      () => {
        setNow(new Date());
        tick = setInterval(() => setNow(new Date()), 60_000);
      },
      60_000 - (Date.now() % 60_000),
    );
    return () => {
      clearTimeout(align);
      if (tick) clearInterval(tick);
    };
  }, []);

  // Blank until mounted: the server's clock isn't Trav's, so rendering a time
  // during SSR guarantees a hydration mismatch.
  return (
    <span className="clock" suppressHydrationWarning>
      {now ? now.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }) : ""}
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
            <span className="badge badge-offline">OFFLINE</span>
          )}
          </div>
          <div className="header-right">
            <span className="badge">autonomy · execute</span>
            <Clock />
            <Link href="/finance" className="nav-link" title="Expenses & earnings">
              $ Finance
            </Link>
            <LocalExecToggle />
            <WakeWord />
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
            <Constellation />
          </section>
          <aside className="v2-chat">
            <ChatStrip />
          </aside>
        </div>
      </main>

      <ArtifactsDock />
    </>
  );
}
