"use client";

// Thin wrappers over the Web Speech API, shared by the wake-word listener, the
// command mic, and the reply speaker so they behave identically across surfaces.

import { setSpeaking } from "./voice";
import { makeSttRecognition } from "./sttRecognition";
import { makeRealtimeSttRecognition, realtimeUnavailable } from "./sttRealtime";

// Realtime STT (Scribe v2) is on by default in the desktop app; set
// NEXT_PUBLIC_REALTIME_STT=0 at build time to force the batch recognizer.
function realtimeSttEnabled(): boolean {
  return process.env.NEXT_PUBLIC_REALTIME_STT !== "0" && !realtimeUnavailable();
}

declare global {
  interface Window {
    resolveDesktop?: boolean;
  }
}

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

// The Web Speech API's recognizer doesn't work inside the Electron desktop app
// (no Google speech backend). There we fall back to server-side STT (ElevenLabs
// Scribe) via a recognizer with the same interface. window.resolveDesktop is
// set by the Electron shell.
export function usesSttEngine(): boolean {
  if (typeof window === "undefined") return false;
  return window.resolveDesktop === true;
}

export function makeRecognition(): SpeechRecognitionLike | null {
  if (typeof window === "undefined") return null;
  if (usesSttEngine()) {
    // Realtime Scribe v2 (streaming, ~150ms) when enabled; it self-heals to the
    // batch recognizer if the socket/token ever fails, so this is always safe.
    if (realtimeSttEnabled()) return makeRealtimeSttRecognition();
    return makeSttRecognition();
  }
  const w = window as unknown as Record<string, new () => SpeechRecognitionLike>;
  const Ctor = w.SpeechRecognition ?? w.webkitSpeechRecognition;
  return Ctor ? new Ctor() : null;
}

export function speechSupported(): boolean {
  if (typeof window === "undefined") return false;
  if (usesSttEngine()) return true; // STT engine handles it in the desktop app
  const w = window as unknown as Record<string, unknown>;
  return Boolean(w.SpeechRecognition ?? w.webkitSpeechRecognition);
}

// iOS/Android: a live recognizer and audio playback fight over the audio session,
// so barge-in (listening while speaking) mutes replies. Detect mobile to disable it.
export function isMobile(): boolean {
  if (typeof navigator === "undefined") return false;
  return (
    /iP(hone|ad|od)|Android/i.test(navigator.userAgent) ||
    (navigator.maxTouchPoints || 0) > 1
  );
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

let currentAudio: HTMLAudioElement | null = null;
// Aborts the in-flight TTS fetch/stream so a barge-in stops audio mid-download,
// not just mid-playback.
let currentAbort: AbortController | null = null;
// Bumped every time speech is (re)started or cancelled; late callbacks from a
// superseded/interrupted utterance check their token and no-op, so a barge-in
// can't have the old reply's onend reopen the mic or flip the speaking flag.
let speakSeq = 0;

// Stop whatever's currently talking, in either lane.
function stopSpeaking(): void {
  speakSeq++;
  if (currentAbort) {
    try {
      currentAbort.abort();
    } catch {
      /* noop */
    }
    currentAbort = null;
  }
  if (currentAudio) {
    try {
      currentAudio.pause();
    } catch {
      /* noop */
    }
    currentAudio = null;
  }
  if (typeof window !== "undefined") window.speechSynthesis?.cancel();
}

// Play a chunked audio Response as it arrives via MediaSource Extensions, so the
// first audio starts before the whole clip has downloaded. Returns true if it
// took ownership of playback; false if MSE/codec isn't available (caller then
// falls back to buffered blob playback). Rejects on a mid-stream failure.
async function playStreaming(
  resp: Response,
  onEnded: () => void,
  onError: () => void,
): Promise<boolean> {
  if (
    typeof MediaSource === "undefined" ||
    !MediaSource.isTypeSupported("audio/mpeg") ||
    !resp.body
  ) {
    return false;
  }
  const media = new MediaSource();
  const url = URL.createObjectURL(media);
  const audio = new Audio();
  audio.src = url;
  currentAudio = audio;
  audio.onended = () => {
    URL.revokeObjectURL(url);
    if (currentAudio === audio) currentAudio = null;
    onEnded();
  };
  audio.onerror = () => {
    URL.revokeObjectURL(url);
    if (currentAudio === audio) currentAudio = null;
    onError();
  };

  await new Promise<void>((res, rej) => {
    media.addEventListener("sourceopen", () => res(), { once: true });
    media.addEventListener("error", () => rej(new Error("MediaSource error")), { once: true });
  });

  const sb = media.addSourceBuffer("audio/mpeg");
  const reader = resp.body.getReader();
  const queue: Uint8Array[] = [];
  let streamDone = false;
  let started = false;

  const flush = () => {
    if (sb.updating || queue.length === 0) return;
    try {
      sb.appendBuffer(queue.shift()! as unknown as BufferSource);
    } catch {
      /* QuotaExceeded etc. — let playback drain, retry on updateend */
    }
  };
  sb.addEventListener("updateend", () => {
    flush();
    if (streamDone && !sb.updating && queue.length === 0) {
      try {
        media.endOfStream();
      } catch {
        /* already ended */
      }
    }
    // begin playback as soon as the first chunk is buffered
    if (!started) {
      started = true;
      void audio.play().catch(onError);
    }
  });

  for (;;) {
    const { done, value } = await reader.read();
    if (done) {
      streamDone = true;
      if (!sb.updating && queue.length === 0) {
        try {
          media.endOfStream();
        } catch {
          /* noop */
        }
      }
      break;
    }
    if (value) queue.push(value);
    flush();
  }
  return true;
}

// Hard-stop any speech in progress (both lanes) and clear the speaking flag.
// Called when voice mode is turned off so it goes quiet immediately.
export function cancelSpeech(): void {
  stopSpeaking();
  setSpeaking(false);
}

// Browser Web Speech fallback (used when ElevenLabs isn't configured or fails).
function browserSpeak(clean: string, done: () => void): void {
  const synth = typeof window !== "undefined" ? window.speechSynthesis : null;
  if (!synth) {
    done();
    return;
  }
  const u = new SpeechSynthesisUtterance(clean);
  const voice = pickVoice();
  if (voice) u.voice = voice;
  u.lang = "en-GB";
  u.rate = 1.14;
  u.onend = done;
  u.onerror = done;
  // Chrome quirk: the queue can be left "paused" after cancel(), silently
  // dropping the next utterance. resume() clears that state before speaking.
  synth.resume();
  synth.speak(u);
}

// Never read a URL aloud: markdown links speak their label, bare links vanish,
// and one "the link's in the chat" tail replaces them (the visible reply still
// carries the actual links).
function stripSpokenLinks(text: string): string {
  let n = 0;
  let out = text.replace(/\[([^\]]+)\]\(\s*[^)]*\)/g, (_m, label: string) => {
    n += 1;
    return label;
  });
  out = out
    .replace(/\bhttps?:\/\/[^\s)>\]]+/gi, () => {
      n += 1;
      return "";
    })
    .replace(/\bwww\.[^\s)>\]]+/gi, () => {
      n += 1;
      return "";
    })
    .replace(/\(\s*\)/g, "")
    .replace(/[ \t]{2,}/g, " ")
    .replace(/ ([,.;!?])/g, "$1");
  if (n > 0 && !/link/i.test(out)) {
    out = `${out.trim()} ${n > 1 ? "The links are in the chat." : "The link's in the chat."}`;
  }
  return out;
}

export function speak(text: string, opts: { onend?: () => void } = {}): void {
  if (typeof window === "undefined") {
    opts.onend?.();
    return;
  }
  const clean = stripSpokenLinks(text).replace(/[*_#`]/g, "").slice(0, 600).trim();
  if (!clean) {
    opts.onend?.();
    return;
  }

  stopSpeaking();
  const mySeq = speakSeq;
  setSpeaking(true);

  let finished = false;
  // Watchdog: if a completion event is ever missed, don't leave `speaking`
  // stuck true — that would deadlock the conversation mic.
  const maxMs = 4000 + clean.length * 90;
  const watchdog = window.setTimeout(() => finish(), maxMs);
  function finish() {
    // superseded by a newer speak()/cancelSpeech()? then do nothing — the new
    // turn owns the speaking flag and the mic hand-back.
    if (finished || mySeq !== speakSeq) return;
    finished = true;
    window.clearTimeout(watchdog);
    setSpeaking(false);
    opts.onend?.();
  }

  // Prefer ElevenLabs (real Jarvis voice, proxied server-side); fall back to the
  // browser voice on any failure or when no key is configured (501).
  const abort = new AbortController();
  currentAbort = abort;
  // Browser-voice fallback runs at most once, and never for a superseded turn.
  let fellBack = false;
  const fallback = () => {
    if (fellBack || finished || mySeq !== speakSeq) return;
    fellBack = true;
    browserSpeak(clean, finish);
  };
  void (async () => {
    try {
      const r = await fetch("/api/tts", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text: clean }),
        signal: abort.signal,
      });
      if (mySeq !== speakSeq) return; // barge-in landed while fetching
      if (r.ok && r.body) {
        // 1) stream it as it arrives (lowest latency). playStreaming only
        // returns false when MSE is unavailable — before it reads the body, so
        // the buffered path below can still consume r.
        try {
          const took = await playStreaming(r, finish, fallback);
          if (took) return;
        } catch {
          if (mySeq !== speakSeq) return; // aborted by a newer turn
          fallback(); // streaming broke mid-flight → browser voice
          return;
        }
        // 2) buffered fallback (MSE/codec unavailable): download then play
        const blob = await r.blob().catch(() => null);
        if (mySeq !== speakSeq) return;
        if (blob && blob.size > 0) {
          const url = URL.createObjectURL(blob);
          const audio = new Audio(url);
          currentAudio = audio;
          audio.onended = () => {
            URL.revokeObjectURL(url);
            if (currentAudio === audio) currentAudio = null;
            finish();
          };
          audio.onerror = () => {
            URL.revokeObjectURL(url);
            if (currentAudio === audio) currentAudio = null;
            fallback();
          };
          await audio.play();
          return;
        }
      }
      fallback(); // 501/empty → browser voice
    } catch (e) {
      if ((e as { name?: string })?.name === "AbortError") return; // superseded turn
      fallback();
    }
  })();
}
