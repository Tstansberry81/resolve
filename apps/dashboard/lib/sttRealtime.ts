"use client";

// Realtime speech-to-text via ElevenLabs Scribe v2 (150ms WebSocket streaming),
// exposed through the SAME SpeechRecognitionLike interface as everything else so
// WakeWord/CommandCore don't change. Unlike the batch recognizer (record whole
// utterance → upload → wait for transcript), this streams mic audio to the socket
// and gets partial + committed transcripts live, with server-side VAD deciding
// when an utterance ends. That removes the upload round-trip that made capture
// feel laggy.
//
// Safety: this can NEVER break voice. If the token mint or the socket fails, the
// instance transparently hands off to the batch recognizer mid-call (so the
// current utterance still works) and flips a module flag so later calls skip
// straight to batch. Auth stays server-side via /api/scribe-token (single-use).

import type { RealtimeConnection } from "@elevenlabs/client";
import type { SpeechRecognitionLike } from "./speech";
import { makeSttRecognition } from "./sttRecognition";

// Seconds of trailing silence before the server commits an utterance. Matches
// the batch recognizer's snappy 550ms turn-end. Env-tunable at build time.
const VAD_SILENCE_SECS = Math.min(
  3,
  Math.max(0.3, Number(process.env.NEXT_PUBLIC_STT_VAD_SILENCE_SECS || "0.55")),
);

// Set once realtime has proven unavailable this session, so we stop paying the
// token round-trip and go straight to batch.
let realtimeDisabled = false;
export function realtimeUnavailable(): boolean {
  return realtimeDisabled;
}

async function fetchToken(): Promise<string | null> {
  try {
    const r = await fetch("/api/scribe-token", { method: "POST" });
    if (!r.ok) return null;
    const d = (await r.json().catch(() => ({}))) as { token?: string };
    return d.token ?? null;
  } catch {
    return null;
  }
}

export function makeRealtimeSttRecognition(): SpeechRecognitionLike {
  let connection: RealtimeConnection | null = null;
  let delegate: SpeechRecognitionLike | null = null; // batch fallback, if used
  let disposed = false;
  let started = false;
  let sawFinal = false;

  const rec: SpeechRecognitionLike = {
    lang: "en-US",
    continuous: false,
    interimResults: false,
    onresult: null,
    onend: null,
    onerror: null,
    start: () => void begin(),
    stop: () => {
      if (delegate) return delegate.stop();
      commitAndEnd();
    },
    abort: () => {
      if (delegate) return delegate.abort();
      teardown(false);
    },
  };

  function emit(text: string, isFinal: boolean) {
    const t = text.trim();
    if (!t || !rec.onresult) return;
    rec.onresult({ results: [Object.assign([{ transcript: t }], { isFinal })] });
  }

  // Hand this utterance to the batch recognizer and remember to prefer batch
  // from now on. Copies the caller's handlers so it's seamless.
  function useBatchFallback() {
    realtimeDisabled = true;
    if (disposed || delegate) return;
    closeConn();
    const b = makeSttRecognition();
    b.lang = rec.lang;
    b.continuous = rec.continuous;
    b.interimResults = rec.interimResults;
    b.onresult = rec.onresult;
    b.onend = rec.onend;
    b.onerror = rec.onerror;
    delegate = b;
    b.start();
  }

  async function begin() {
    if (disposed || started) return;
    started = true;
    const token = await fetchToken();
    if (disposed) return;
    if (!token) {
      useBatchFallback();
      return;
    }
    try {
      const { Scribe, RealtimeEvents, CommitStrategy } = await import("@elevenlabs/client");
      if (disposed) return;
      const conn = Scribe.connect({
        token,
        modelId: "scribe_v2_realtime",
        commitStrategy: CommitStrategy.VAD,
        vadSilenceThresholdSecs: VAD_SILENCE_SECS,
        languageCode: "en",
        microphone: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
        },
      });
      connection = conn;

      conn.on(RealtimeEvents.PARTIAL_TRANSCRIPT, (d) => {
        if (disposed || !rec.interimResults) return;
        emit(d?.text ?? "", false);
      });
      conn.on(RealtimeEvents.COMMITTED_TRANSCRIPT, (d) => {
        if (disposed) return;
        if ((d?.text ?? "").trim()) {
          sawFinal = true;
          emit(d.text, true);
        }
        // one-shot capture ends after the first committed utterance; continuous
        // (wake word / barge-in) keeps the socket open for the next one.
        if (!rec.continuous) teardown(true);
      });

      // Any failure before we've produced a result → fall back to batch so the
      // turn still works. After a success, just end (caller re-arms if needed).
      const onFail = () => {
        if (disposed) return;
        if (!sawFinal) useBatchFallback();
        else teardown(true);
      };
      conn.on(RealtimeEvents.AUTH_ERROR, onFail);
      conn.on(RealtimeEvents.ERROR, onFail);
      conn.on(RealtimeEvents.QUOTA_EXCEEDED, onFail);
      conn.on(RealtimeEvents.RATE_LIMITED, onFail);
      conn.on(RealtimeEvents.CLOSE, () => {
        if (!disposed && !delegate) teardown(true);
      });
    } catch {
      useBatchFallback();
    }
  }

  function commitAndEnd() {
    try {
      connection?.commit();
    } catch {
      /* noop */
    }
    teardown(true);
  }

  function closeConn() {
    try {
      connection?.close();
    } catch {
      /* noop */
    }
    connection = null;
  }

  function teardown(fireEnd: boolean) {
    if (disposed) return;
    disposed = true;
    closeConn();
    if (fireEnd) rec.onend?.();
  }

  return rec;
}
