"use client";

// A speech recognizer that implements the SAME shape as the Web Speech API
// (SpeechRecognitionLike), but transcribes server-side via ElevenLabs Scribe
// (/api/stt). This is what makes voice work inside the Electron desktop app,
// where webkitSpeechRecognition can't reach Google's backend.
//
// It's VAD-gated: while you're silent it sends nothing (no cost/latency). When
// it detects speech it records one utterance, waits for you to stop, then makes
// a single /api/stt call and fires onresult — exactly like a Web Speech "final"
// result. In continuous mode it re-arms and repeats.

import type { SpeechRecognitionLike } from "./speech";

// energy thresholds (0..1 RMS on the analyser); tuned for a laptop mic
const SPEECH_ON = 0.045; // rises above this → speech started
const SPEECH_OFF = 0.03; // falls below this for SILENCE_MS → utterance ended
const SILENCE_MS = 900; // trailing silence that ends an utterance
const MAX_UTTER_MS = 15000; // hard cap on one utterance
const NO_SPEECH_MS = 8000; // give up waiting for speech onset (one-shot)
const POLL_MS = 100;

function pickMime(): string {
  const cands = ["audio/webm;codecs=opus", "audio/webm", "audio/mp4", "audio/ogg;codecs=opus"];
  for (const m of cands) {
    if (typeof MediaRecorder !== "undefined" && MediaRecorder.isTypeSupported(m)) return m;
  }
  return "";
}

async function transcribe(blob: Blob): Promise<string> {
  const fd = new FormData();
  fd.append("audio", blob, "speech.webm");
  const r = await fetch("/api/stt", { method: "POST", body: fd });
  if (!r.ok) return "";
  const data = (await r.json().catch(() => ({}))) as { text?: string };
  return (data.text ?? "").trim();
}

export function makeSttRecognition(): SpeechRecognitionLike {
  let stream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;
  let analyser: AnalyserNode | null = null;
  let recorder: MediaRecorder | null = null;
  let chunks: BlobPart[] = [];
  let poll: ReturnType<typeof setInterval> | null = null;
  let running = false; // start() called, not yet ended
  let disposed = false;
  let mime = "";

  // per-utterance VAD state
  let speaking = false;
  let lastLoud = 0;
  let utterStart = 0;
  let armedAt = 0;

  const rec: SpeechRecognitionLike = {
    lang: "en-US",
    continuous: false,
    interimResults: false,
    onresult: null,
    onend: null,
    onerror: null,
    start: () => void begin(),
    stop: () => finalizeUtterance(true),
    abort: () => teardown(true),
  };

  function rms(): number {
    if (!analyser) return 0;
    const buf = new Uint8Array(analyser.fftSize);
    analyser.getByteTimeDomainData(buf);
    let sum = 0;
    for (let i = 0; i < buf.length; i++) {
      const v = (buf[i] - 128) / 128;
      sum += v * v;
    }
    return Math.sqrt(sum / buf.length);
  }

  async function begin() {
    if (disposed) return;
    try {
      stream = await navigator.mediaDevices.getUserMedia({ audio: true });
    } catch {
      rec.onerror?.();
      rec.onend?.();
      return;
    }
    mime = pickMime();
    const AC = window.AudioContext || (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
    audioCtx = new AC();
    const src = audioCtx.createMediaStreamSource(stream);
    analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    src.connect(analyser);

    running = true;
    armedAt = Date.now();
    armUtterance();
    poll = setInterval(tick, POLL_MS);
  }

  function armUtterance() {
    speaking = false;
    utterStart = 0;
    chunks = [];
    if (stream && (mime !== undefined)) {
      try {
        recorder = mime ? new MediaRecorder(stream, { mimeType: mime }) : new MediaRecorder(stream);
      } catch {
        recorder = new MediaRecorder(stream);
      }
      recorder.ondataavailable = (e) => {
        if (e.data && e.data.size > 0) chunks.push(e.data);
      };
      recorder.start(200); // gather in small slices
    }
  }

  function tick() {
    if (!running) return;
    const level = rms();
    const now = Date.now();

    if (!speaking) {
      if (level > SPEECH_ON) {
        speaking = true;
        utterStart = now;
        lastLoud = now;
      } else if (!rec.continuous && now - armedAt > NO_SPEECH_MS) {
        // one-shot: heard nothing in time → end quietly (mimics Web Speech no-speech)
        teardown(false);
        rec.onend?.();
      }
      return;
    }

    if (level > SPEECH_OFF) lastLoud = now;
    const longEnough = now - utterStart > 400;
    const trailingSilence = now - lastLoud > SILENCE_MS;
    const tooLong = now - utterStart > MAX_UTTER_MS;
    if ((longEnough && trailingSilence) || tooLong) {
      finalizeUtterance(false);
    }
  }

  function finalizeUtterance(force: boolean) {
    if (!running) return;
    if (!speaking && !force) return;
    const r = recorder;
    recorder = null;
    if (!r) return;
    r.onstop = async () => {
      const blob = new Blob(chunks, { type: mime || "audio/webm" });
      chunks = [];
      let text = "";
      if (blob.size > 1200) {
        try {
          text = await transcribe(blob);
        } catch {
          text = "";
        }
      }
      if (text && rec.onresult) {
        const results = [Object.assign([{ transcript: text }], { isFinal: true })];
        rec.onresult({ results });
      }
      if (rec.continuous && running && !disposed) {
        armUtterance(); // re-arm for the next utterance
        armedAt = Date.now();
      } else {
        teardown(false);
        rec.onend?.();
      }
    };
    try {
      r.stop();
    } catch {
      /* noop */
    }
  }

  function teardown(fireEnd: boolean) {
    running = false;
    disposed = true;
    if (poll) {
      clearInterval(poll);
      poll = null;
    }
    if (recorder) {
      try {
        recorder.onstop = null;
        recorder.stop();
      } catch {
        /* noop */
      }
      recorder = null;
    }
    if (stream) {
      stream.getTracks().forEach((t) => t.stop());
      stream = null;
    }
    if (audioCtx) {
      audioCtx.close().catch(() => {});
      audioCtx = null;
    }
    analyser = null;
    if (fireEnd) rec.onend?.();
  }

  return rec;
}
