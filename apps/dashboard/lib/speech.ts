"use client";

// Thin wrappers over the Web Speech API, shared by the wake-word listener, the
// command mic, and the reply speaker so they behave identically across surfaces.

import { setSpeaking } from "./voice";

// Chrome loads voices asynchronously; kick a load so pickVoice() isn't empty
// on the first utterance.
export function preloadVoices(): void {
  if (typeof window === "undefined" || !window.speechSynthesis) return;
  window.speechSynthesis.getVoices();
}

export type SpeechRecognitionLike = {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  start: () => void;
  stop: () => void;
  abort: () => void;
  onresult:
    | ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal?: boolean }> }) => void)
    | null;
  onend: (() => void) | null;
  onerror: (() => void) | null;
};

export function makeRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  const w = window as unknown as Record<string, new () => SpeechRecognitionLike>;
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

export function speechSupported(): boolean {
  if (typeof window === "undefined") return false;
  const w = window as unknown as Record<string, unknown>;
  return Boolean(w.SpeechRecognition ?? w.webkitSpeechRecognition);
}

// British male voice for RESOLVE's replies (Daniel on macOS/iOS,
// "Google UK English Male" on Chrome), falling back to any en-GB voice.
export function pickVoice(): SpeechSynthesisVoice | null {
  const voices = window.speechSynthesis?.getVoices() ?? [];
  return (
    voices.find((v) => v.name === "Daniel") ??
    voices.find((v) => v.name.includes("UK English Male")) ??
    voices.find((v) => v.lang === "en-GB") ??
    null
  );
}

export function speak(text: string, opts: { onend?: () => void } = {}): void {
  if (typeof window === "undefined" || !window.speechSynthesis) {
    opts.onend?.();
    return;
  }
  const synth = window.speechSynthesis;
  const clean = text.replace(/[*_#`]/g, "").slice(0, 600).trim();
  if (!clean) {
    opts.onend?.();
    return;
  }
  const u = new SpeechSynthesisUtterance(clean);
  const voice = pickVoice();
  if (voice) u.voice = voice;
  u.lang = "en-GB";
  u.rate = 1.02;
  let finished = false;
  const done = () => {
    if (finished) return;
    finished = true;
    setSpeaking(false);
    opts.onend?.();
  };
  u.onend = done;
  u.onerror = done;
  synth.cancel(); // drop anything queued/stuck
  setSpeaking(true);
  // Chrome quirk: the queue can be left "paused" after cancel(), silently
  // dropping the next utterance. resume() clears that state before speaking.
  synth.resume();
  synth.speak(u);
  // Watchdog: if the utterance is silently dropped (onend never fires), don't
  // leave `speaking` stuck true — that would deadlock the conversation mic.
  const maxMs = 2500 + clean.length * 90;
  setTimeout(done, maxMs);
}
