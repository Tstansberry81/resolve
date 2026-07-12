"use client";

import { useRef, useState } from "react";
import { engine, useEngine } from "@/lib/useEngine";

type SpeechRecognitionLike = {
  lang: string;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }>> }) => void) | null;
  onend: (() => void) | null;
};

function makeRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, new () => SpeechRecognitionLike>;
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

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
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);

  const submit = () => {
    const t = text.trim();
    if (!t || emergencyStopped) return;
    engine.submitCommand(t);
    setText("");
  };

  const toggleMic = () => {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = makeRecognition();
    if (!rec) {
      setText("Voice input needs Chrome, Edge, or Safari");
      return;
    }
    recRef.current = rec;
    rec.lang = "en-US";
    rec.interimResults = false;
    rec.onresult = (e) => {
      const heard = e.results[0]?.[0]?.transcript ?? "";
      if (heard.trim()) engine.submitCommand(heard.trim());
    };
    rec.onend = () => setListening(false);
    setListening(true);
    rec.start();
  };

  return (
    <div className="core-v2">
      <span className="core-state" data-state={orb}>
        {STATE_LABEL[orb]}
      </span>

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
          title={listening ? "Listening — tap to stop" : "Speak a command"}
          aria-label="Voice command"
          disabled={emergencyStopped}
          style={listening ? { color: "#35e39c" } : undefined}
          onClick={toggleMic}
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
              : "Tell Sonnet what you need…"
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
