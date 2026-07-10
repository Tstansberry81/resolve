"use client";

import { useState } from "react";
import { useEngine } from "@/lib/useEngine";
import type { AgentEvent, Goal, GoalStatus } from "@/lib/types";

// Left rail: Missions as a dropdown section (open by default), and beneath it
// the Event log dropdown — fully hidden until clicked, per spec.

const STATUS_META: Record<GoalStatus, { label: string; tone: string }> = {
  planning: { label: "planning", tone: "blue" },
  active: { label: "active", tone: "cyan" },
  waiting_approval: { label: "needs you", tone: "amber" },
  paused: { label: "paused", tone: "red" },
  completed: { label: "done", tone: "green" },
  failed: { label: "failed", tone: "red" },
};

const ORDER: GoalStatus[] = [
  "waiting_approval",
  "active",
  "planning",
  "paused",
  "completed",
  "failed",
];

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

function MissionCard({ goal }: { goal: Goal }) {
  const meta = STATUS_META[goal.status];
  const pct = Math.round(goal.progress * 100);
  return (
    <article className="mission" data-status={goal.status}>
      <header>
        <span className="mission-cat">{goal.category}</span>
        <span className={`chip chip-${meta.tone}`}>{meta.label}</span>
      </header>
      <h3>{goal.objective}</h3>
      <div className="mission-bar">
        <div className="mission-bar-fill" style={{ width: `${pct}%` }} />
      </div>
      <dl className="mission-facts">
        <div>
          <dt>progress</dt>
          <dd>{pct}%</dd>
        </div>
        <div>
          <dt>budget</dt>
          <dd>
            ${goal.spentUsd.toFixed(2)}
            <span className="of"> / ${goal.budgetUsd.toFixed(2)}</span>
          </dd>
        </div>
        {goal.deadline && (
          <div>
            <dt>deadline</dt>
            <dd>{goal.deadline}</dd>
          </div>
        )}
      </dl>
      <p className="mission-next">
        {goal.blocker ? (
          <span className="mission-blocker">⚠ {goal.blocker}</span>
        ) : (
          <>
            <span className="arrow">▸</span> {goal.nextAction}
          </>
        )}
      </p>
    </article>
  );
}

function EventRow({ ev, now }: { ev: AgentEvent; now: number }) {
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
          <span className="tl-time">{ago(ev.ts, now)}</span>
        </div>
        <p className="tl-summary">{ev.summary}</p>
        {open && ev.detail && <p className="tl-detail">{ev.detail}</p>}
      </div>
    </li>
  );
}

export function Sidebar() {
  const { goals, events } = useEngine();
  const [missionsOpen, setMissionsOpen] = useState(true);
  const [logOpen, setLogOpen] = useState(false);
  const now = Date.now();

  const sorted = [...goals].sort(
    (a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status),
  );
  const live = goals.filter(
    (g) => g.status === "active" || g.status === "waiting_approval",
  ).length;

  return (
    <aside className="sidebar">
      <section className="drop">
        <button
          className="drop-head"
          onClick={() => setMissionsOpen((o) => !o)}
          aria-expanded={missionsOpen}
        >
          <span className={`chev ${missionsOpen ? "chev-open" : ""}`}>▸</span>
          Missions
          <span className="count">{live} live</span>
        </button>
        {missionsOpen && (
          <div className="drop-body">
            {sorted.length === 0 && (
              <p className="empty">No goals yet — the day is quiet.</p>
            )}
            {sorted.map((g) => (
              <MissionCard key={g.id} goal={g} />
            ))}
          </div>
        )}
      </section>

      <section className="drop">
        <button
          className="drop-head"
          onClick={() => setLogOpen((o) => !o)}
          aria-expanded={logOpen}
        >
          <span className={`chev ${logOpen ? "chev-open" : ""}`}>▸</span>
          Event log
          <span className="count">{events.length}</span>
        </button>
        {logOpen && (
          <ul className="drop-body tl">
            {events.length === 0 && <p className="empty">No events yet.</p>}
            {events.map((ev) => (
              <EventRow key={ev.id} ev={ev} now={now} />
            ))}
          </ul>
        )}
      </section>
    </aside>
  );
}
