"use client";

import { useEngine } from "@/lib/useEngine";
import type { Goal, GoalStatus } from "@/lib/types";

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

export function MissionRail() {
  const { goals } = useEngine();
  const sorted = [...goals].sort(
    (a, b) => ORDER.indexOf(a.status) - ORDER.indexOf(b.status),
  );

  return (
    <div className="panel area-missions">
      <div className="panel-title">
        <span className="dot" />
        Missions
        <span className="count">{goals.filter((g) => g.status === "active" || g.status === "waiting_approval").length} live</span>
      </div>
      <div className="rail">
        {sorted.length === 0 && (
          <p className="empty">No goals yet — the day is quiet.</p>
        )}
        {sorted.map((g) => (
          <MissionCard key={g.id} goal={g} />
        ))}
      </div>
    </div>
  );
}
