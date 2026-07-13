"use client";

// Conversation surface: renders the command/reply exchange as chat bubbles.
// Pure VIEW over the event feed — no audio. All speech is handled by
// CommandCore's voice conversation loop (wake word). Collapses entirely while
// the wake word is armed for a clean voice-only interface.

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
      out.push({ id: e.id, who: "you", text: e.summary.replace(/^Goal accepted: /, "") });
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

  // Collapse subtitles entirely while the wake word is armed (voice-only mode).
  if (bubbles.length === 0 || voice.wakeOn) return null;

  return (
    <div className={styles.strip} aria-label="Conversation">
      {bubbles.map((b) => (
        <div key={b.id} className={b.who === "you" ? styles.rowYou : styles.rowSonnet}>
          <div className={b.who === "you" ? styles.bubbleYou : styles.bubbleSonnet}>
            {b.who === "sonnet" && <span className={styles.tag}>RESOLVE</span>}
            {b.text}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
