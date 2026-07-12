"use client";

// Conversation surface: renders the command/reply exchange as chat bubbles so
// Sonnet's answers (and her clarifying questions) are impossible to miss.
// Pure view over the event feed — works identically in mock and live mode.

import { useEffect, useRef, useState } from "react";
import { useEngine } from "@/lib/useEngine";
import type { AgentEvent } from "@/lib/types";
import styles from "./chatstrip.module.css";

// British male voice for Sonnet's replies; picks the best en-GB voice around
// (Daniel on macOS/iOS, Google UK English Male on Chrome).
function pickVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis?.getVoices() ?? [];
  return (
    voices.find((v) => v.name === "Daniel") ??
    voices.find((v) => v.name.includes("UK English Male")) ??
    voices.find((v) => v.lang === "en-GB") ??
    null
  );
}

function speak(text: string) {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  const clean = text.replace(/[*_#`]/g, "").slice(0, 600);
  const u = new SpeechSynthesisUtterance(clean);
  const voice = pickVoice();
  if (voice) u.voice = voice;
  u.lang = "en-GB";
  u.rate = 1.02;
  window.speechSynthesis.cancel();
  window.speechSynthesis.speak(u);
}

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
  const [voiceOn, setVoiceOn] = useState(false);

  useEffect(() => {
    setVoiceOn(localStorage.getItem("resolve_voice") === "on");
  }, []);

  useEffect(() => {
    endRef.current?.scrollIntoView({ behavior: "smooth", block: "nearest" });
    const last = bubbles[bubbles.length - 1];
    if (voiceOn && last && last.who === "sonnet" && last.id > spokenRef.current) {
      spokenRef.current = last.id;
      speak(last.text);
    }
  }, [bubbles, voiceOn]);

  const toggleVoice = () => {
    const next = !voiceOn;
    setVoiceOn(next);
    localStorage.setItem("resolve_voice", next ? "on" : "off");
    if (!next) window.speechSynthesis?.cancel();
    else speak("Voice on.");
  };

  if (bubbles.length === 0) return null;

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
