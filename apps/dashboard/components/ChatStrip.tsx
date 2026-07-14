"use client";

// Conversation surface: renders the command/reply exchange as chat bubbles.
// Pure VIEW over the event feed — no audio. All speech is handled by
// CommandCore's voice conversation loop (wake word). Collapses only while a
// voice turn is ACTIVELY in progress (clean orb-only view); it stays visible
// when the wake word is merely armed and returns the moment wake is toggled off.

import { useEffect, useRef, useSyncExternalStore } from "react";
import { useEngine } from "@/lib/useEngine";
import type { AgentEvent } from "@/lib/types";
import { getVoice, subscribeVoice } from "@/lib/voice";
import styles from "./chatstrip.module.css";

const EMPTY_VOICE = { wakeOn: false, active: false, speaking: false };

interface Bubble {
  id: number;
  who: "you" | "sonnet";
  text: string;
}

function toBubbles(events: AgentEvent[]): Bubble[] {
  const out: Bubble[] = [];
  // events arrive newest-first; walk oldest-first
  for (let i = events.length - 1; i >= 0; i--) {
    const e = events[i];
    if (e.type === "goal.accepted") {
      // prefer the full command in detail; fall back to the (truncated) summary
      const full = (e.detail && e.detail.trim()) || e.summary.replace(/^Goal accepted: /, "");
      out.push({ id: e.id, who: "you", text: full });
    } else if (e.type === "goal.queued") {
      out.push({ id: e.id, who: "sonnet", text: e.summary });
    } else if (e.type === "assistant.reply") {
      out.push({ id: e.id, who: "sonnet", text: e.detail ?? e.summary });
    }
  }
  return out.slice(-12);
}

export function ChatStrip() {
  const state = useEngine();
  const bubbles = toBubbles(state.events);
  const endRef = useRef<HTMLDivElement>(null);
  const voice = useSyncExternalStore(subscribeVoice, getVoice, () => EMPTY_VOICE);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [bubbles]);

  // Collapse only during an ACTIVE voice turn (orb-only view). Armed-but-idle
  // and wake-off both show the log — so toggling wake off brings it back.
  if (bubbles.length === 0 || voice.active) return null;

  return (
    <div className={styles.strip} aria-label="Conversation">
      {bubbles.map((b) => (
        <div key={b.id} className={b.who === "you" ? styles.rowYou : styles.rowSonnet}>
          <div className={b.who === "you" ? styles.bubbleYou : styles.bubbleSonnet}>
            {b.who === "sonnet" && <span className={styles.tag}>RESOLVE</span>}
            {renderRich(b.text)}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}

// Render chat text with clickable links ([label](url) and bare URLs) and **bold**.
const LINK_RE = /\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)|(https?:\/\/[^\s]+)/g;

function renderRich(text: string): React.ReactNode[] {
  const out: React.ReactNode[] = [];
  let last = 0;
  let m: RegExpExecArray | null;
  let key = 0;
  LINK_RE.lastIndex = 0;
  while ((m = LINK_RE.exec(text)) !== null) {
    if (m.index > last) out.push(...renderBold(text.slice(last, m.index), key++));
    const label = m[1];
    const url = (m[2] || m[3] || "").replace(/[.,);]+$/, "");
    out.push(
      <a key={`l${key++}`} href={url} target="_blank" rel="noreferrer" className={styles.link}>
        {label || url}
      </a>,
    );
    last = m.index + m[0].length;
  }
  if (last < text.length) out.push(...renderBold(text.slice(last), key++));
  return out;
}

function renderBold(text: string, baseKey: number): React.ReactNode[] {
  const parts = text.split(/\*\*([^*]+)\*\*/g);
  return parts.map((p, i) =>
    i % 2 === 1 ? <strong key={`b${baseKey}-${i}`}>{p}</strong> : p,
  );
}
