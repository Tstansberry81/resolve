"use client";

// Conversation surface: renders the command/reply exchange as chat bubbles so
// Sonnet's answers (and her clarifying questions) are impossible to miss.
// Pure view over the event feed — works identically in mock and live mode.

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useEngine } from "@/lib/useEngine";
import type { AgentEvent } from "@/lib/types";
import { speak } from "@/lib/speech";
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
  const spokenRef = useRef<number>(0);
  const voice = useSyncExternalStore(subscribeVoice, getVoice, () => EMPTY_VOICE);
  const [voiceOn, setVoiceOn] = useState(false);

  useEffect(() => {
    setVoiceOn(localStorage.getItem("resolve_voice") === "on");
  }, []);

  // Speak replies when the manual toggle is on OR voice conversation mode is live.
  const speakOn = voiceOn || voice.active;

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    const last = bubbles[bubbles.length - 1];
    if (speakOn && last && last.who === "sonnet" && last.id > spokenRef.current) {
      spokenRef.current = last.id;
      speak(last.text);
    }
  }, [bubbles, speakOn]);

  const toggleVoice = () => {
    const next = !voiceOn;
    setVoiceOn(next);
    localStorage.setItem("resolve_voice", next ? "on" : "off");
    if (!next) window.speechSynthesis?.cancel();
    else speak("Voice on.");
  };

  // While the wake word is armed, collapse the subtitles for a clean voice-only
  // interface. The reply-speaking effect above still runs (component stays
  // mounted), so voice output is unaffected.
  if (bubbles.length === 0 || voice.wakeOn) return null;

  return (
    <div className={styles.strip} aria-label="Conversation">
      <button
        className={styles.voiceToggle}
        onClick={toggleVoice}
        title={voiceOn ? "Sonnet speaks replies — tap to mute" : "Tap to have Sonnet speak replies"}
      >
        {voiceOn ? "🔊" : "🔇"}
      </button>
      {bubbles.map((b) => (
        <div key={b.id} className={b.who === "you" ? styles.rowYou : styles.rowSonnet}>
          <div className={b.who === "you" ? styles.bubbleYou : styles.bubbleSonnet}>
            {b.who === "sonnet" && <span className={styles.tag}>SONNET</span>}
            {b.text}
          </div>
        </div>
      ))}
      <div ref={endRef} />
    </div>
  );
}
