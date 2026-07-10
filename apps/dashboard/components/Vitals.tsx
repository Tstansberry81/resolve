"use client";

import { useEngine } from "@/lib/useEngine";

export function Vitals() {
  const { vitals } = useEngine();

  return (
    <div className="panel area-vitals vitals">
      <div className="panel-title">
        <span
          className="dot"
          style={
            vitals.workerStatus === "stopped"
              ? { background: "var(--red)", boxShadow: "0 0 8px var(--red)" }
              : undefined
          }
        />
        System vitals
        <span className="count">worker {vitals.workerStatus}</span>
      </div>
      <div className="vitals-body">
        <div className="vital-stats">
          <div className="stat">
            <span className="stat-value">{vitals.queueDepth}</span>
            <span className="stat-label">queue</span>
          </div>
          <div className="stat">
            <span className="stat-value">
              {(vitals.errorRate * 100).toFixed(1)}%
            </span>
            <span className="stat-label">errors</span>
          </div>
          <div className="stat">
            <span className="stat-value">
              {(vitals.tokensToday / 1000).toFixed(0)}k
            </span>
            <span className="stat-label">tokens</span>
          </div>
          <div className="stat">
            <span className="stat-value">${vitals.costTodayUsd.toFixed(2)}</span>
            <span className="stat-label">cost today</span>
          </div>
        </div>

        <div className="vital-connectors">
          {vitals.connectors.map((c) => (
            <div key={c.id} className="conn" data-status={c.status}>
              <span className="conn-dot" />
              <span className="conn-label">{c.label}</span>
              <span className="conn-lat">{c.latencyMs}ms</span>
            </div>
          ))}
        </div>

        <div className="vital-models">
          {vitals.models.map((m) => (
            <div key={m.role} className="lane">
              <span className="lane-role">{m.role}</span>
              <span className="lane-model">{m.model}</span>
              <span className="lane-num">{(m.p50Ms / 1000).toFixed(1)}s</span>
              <span className="lane-num">${m.costTodayUsd.toFixed(2)}</span>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
