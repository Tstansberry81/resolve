"use client";

// Shared voice state, deliberately decoupled from the engine so the wake-word
// listener (WakeWord), the mic (CommandCore), and the speaker (ChatStrip) can
// coordinate without prop-drilling. Tiny pub/sub read via useSyncExternalStore.
//
//   wakeOn  — the background wake-word listener is armed (mic always sampling
//             for the trigger phrase). Persisted so it survives reloads.
//   active  — voice conversation mode is live: replies are spoken and the mic
//             listens for the next command. Flipped on by the wake word.

export interface VoiceState {
  wakeOn: boolean;
  active: boolean;
  speaking: boolean;
}

let state: VoiceState = { wakeOn: false, active: false, speaking: false };
const listeners = new Set<() => void>();

function emit() {
  for (const l of listeners) l();
}

export function subscribeVoice(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getVoice(): VoiceState {
  return state;
}

export function hydrateWake(): void {
  if (typeof window === "undefined") return;
  const on = window.localStorage.getItem("resolve_wake") === "on";
  if (on !== state.wakeOn) {
    state = { ...state, wakeOn: on };
    emit();
  }
}

export function setWakeOn(on: boolean): void {
  state = { ...state, wakeOn: on };
  if (typeof window !== "undefined") {
    window.localStorage.setItem("resolve_wake", on ? "on" : "off");
  }
  // turning the wake listener off also drops any live conversation
  if (!on && state.active) state.active = false;
  emit();
}

export function setActive(on: boolean): void {
  if (state.active === on) return;
  state = { ...state, active: on };
  emit();
}

export function setSpeaking(on: boolean): void {
  if (state.speaking === on) return;
  state = { ...state, speaking: on };
  emit();
}

// Wake phrases: "resolve", "hey resolve", "yo resolve", "what's up resolve",
// plus forgiving variants ("ok/okay/yo/hey resolve", "sup resolve"). We match a
// trailing "resolve" so any of the listed lead-ins (or none) trigger it.
const WAKE_RE = /\b(?:hey|yo|ok|okay|sup|what'?s up|whats up)?\s*resolve\b/i;
// A spoken "stand down" / "stop listening" ends the conversation by voice.
const SLEEP_RE = /\b(?:stand down|stop listening|go to sleep|that'?s all|nevermind|never mind)\b/i;

export function isWakePhrase(text: string): boolean {
  return WAKE_RE.test(text);
}

export function isSleepPhrase(text: string): boolean {
  return SLEEP_RE.test(text);
}
