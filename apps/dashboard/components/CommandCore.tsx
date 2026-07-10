"use client";

import { useState } from "react";
import { engine, useEngine } from "@/lib/useEngine";

const STATE_LABEL: Record<string, string> = {
  idle: "STANDING BY",
  listening: "LISTENING",
  thinking: "THINKING",
  executing: "EXECUTING",
  waiting: "AWAITING YOU",
};

export function CommandCore() {
  const { orb, orbCaption, emergencyStopped } = useEngine();
  const [text, setText] = useState("");

  const submit = () => {
    const t = text.trim();
    if (!t || emergencyStopped) return;
    engine.submitCommand(t);
    setText("");
  };

  return (
    <div className="panel area-core core">
      <div className="panel-title">
        <span className="dot" />
        Command core
        <span className="core-state" data-state={orb}>
          {STATE_LABEL[orb]}
        </span>
      </div>

      <div className="orb-stage" data-state={orb}>
        <div className="orb-halo" />
        <div className="orb-ring orb-ring-a" />
        <div className="orb-ring orb-ring-b" />
        <div className="orb">
          <div className="orb-inner" />
        </div>
      </div>

      <p className="orb-caption">{orbCaption}</p>

      <div className="command-bar">
        <button
          className="mic"
          title="Voice (mock): asks about tomorrow's calendar"
          aria-label="Voice command"
          disabled={emergencyStopped}
          onClick={() =>
            engine.submitCommand("What's on my calendar tomorrow?")
          }
        >
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="9" y="3" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0" />
            <path d="M12 18v3" />
          </svg>
        </button>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={
            emergencyStopped
              ? "Execution halted — resume to issue commands"
              : "Give RESOLVE a goal…"
          }
          disabled={emergencyStopped}
          aria-label="Command input"
        />
        <button className="send" onClick={submit} disabled={emergencyStopped}>
          RUN
        </button>
      </div>
    </div>
  );
}
