"use client";

import { useState } from "react";
import { useEngine } from "@/lib/useEngine";
import { AGENTS } from "@/lib/roster";

// Top-left status pill; click to expand full system + per-agent detail.

export function VitalsDropdown() {
  const { vitals, activeNodes, emergencyStopped } = useEngine();
  const [open, setOpen] = useState(false);

  const degraded =
    vitals.connectors.some((c) => c.status !== "healthy") ||
    vitals.laptop === "offline";
  const status = emergencyStopped
    ? { label: "STOPPED", tone: "red" }
    : degraded
      ? { label: "DEGRADED", tone: "amber" }
      : { label: "NOMINAL", tone: "green" };

  return (
    <div className="vitals-drop">
      <button
        className="vitals-pill"
        data-tone={status.tone}
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
      >
        <span className="vitals-dot" />
        {status.label}
        <span className="vitals-sub">worker {vitals.workerStatus}</span>
        <span className="vitals-sub" data-tone={vitals.laptop === "online" ? "green" : "amber"}>
          laptop {vitals.laptop}
        </span>
        <span className={`chev ${open ? "chev-open" : ""}`}>▸</span>
      </button>

      {open && (
        <div className="vitals-pop panel">
          <div className="vital-stats">
            <div className="stat">
              <span className="stat-value">{vitals.queueDepth}</span>
              <span className="stat-label">queue</span>
            </div>
            <div className="stat">
              <span className="stat-value">{(vitals.errorRate * 100).toFixed(1)}%</span>
              <span className="stat-label">errors</span>
            </div>
            <div className="stat">
              <span className="stat-value">{(vitals.tokensToday / 1000).toFixed(0)}k</span>
              <span className="stat-label">tokens</span>
            </div>
            <div className="stat">
              <span className="stat-value">${vitals.costTodayUsd.toFixed(2)}</span>
              <span className="stat-label">cost today</span>
            </div>
          </div>

          <p className="pop-title">Agents</p>
          <div className="agent-list">
            {AGENTS.map((ag) => {
              const busy = activeNodes.includes(ag.id);
              const lane = vitals.models.find(
                (m) => m.role === ag.id || (ag.id === "planner" && m.role === "planner"),
              );
              return (
                <div key={ag.id} className="agent-row" data-busy={busy}>
                  <span className="agent-dot" style={{ background: busy ? ag.color : undefined }} />
                  <span className="agent-name">{ag.label}</span>
                  <span className="agent-model">{ag.model}</span>
                  <span className="agent-state">
                    {emergencyStopped ? "stopped" : busy ? "busy" : "idle"}
                  </span>
                  {lane && <span className="agent-cost">${lane.costTodayUsd.toFixed(2)}</span>}
                </div>
              );
            })}
          </div>

          <p className="pop-title">Connectors</p>
          <div className="vital-connectors">
            {vitals.connectors.map((c) => (
              <div key={c.id} className="conn" data-status={c.status}>
                <span className="conn-dot" />
                <span className="conn-label">{c.label}</span>
                <span className="conn-lat">{c.latencyMs}ms</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
