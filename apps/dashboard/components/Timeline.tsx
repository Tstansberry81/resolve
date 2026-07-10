"use client";

import { useState } from "react";
import { useEngine } from "@/lib/useEngine";
import type { AgentEvent } from "@/lib/types";

const LEVEL_GLYPH: Record<AgentEvent["level"], string> = {
  info: "•",
  success: "✓",
  warn: "▲",
  error: "✕",
  approval: "⛨",
};

function ago(ts: number, now: number): string {
  const s = Math.max(0, Math.round((now - ts) / 1000));
  if (s < 5) return "now";
  if (s < 60) return `${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `${m}m`;
  return `${Math.floor(m / 60)}h`;
}

function Row({ ev, now }: { ev: AgentEvent; now: number }) {
  const [open, setOpen] = useState(false);
  return (
    <li
      className={`tl-row tl-${ev.level} ${ev.detail ? "tl-expandable" : ""}`}
      onClick={() => ev.detail && setOpen((o) => !o)}
    >
      <span className="tl-glyph">{LEVEL_GLYPH[ev.level]}</span>
      <div className="tl-body">
        <div className="tl-line">
          <span className="tl-actor">{ev.actor}</span>
          <span className="tl-type">{ev.type}</span>
          <span className="tl-time">{ago(ev.ts, now)}</span>
        </div>
        <p className="tl-summary">{ev.summary}</p>
        {open && ev.detail && <p className="tl-detail">{ev.detail}</p>}
      </div>
    </li>
  );
}

export function Timeline() {
  const { events } = useEngine();
  const now = Date.now();

  return (
    <div className="panel area-timeline timeline">
      <div className="panel-title">
        <span className="dot" />
        Live execution
        <span className="count">{events.length} events</span>
      </div>
      <ul className="tl">
        {events.length === 0 && <p className="empty">Waiting for first event…</p>}
        {events.map((ev) => (
          <Row key={ev.id} ev={ev} now={now} />
        ))}
      </ul>
    </div>
  );
}
