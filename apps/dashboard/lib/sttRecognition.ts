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
const SILENCE_MS = 550; // trailing silence that ends an utterance (snappier turns)
const MAX_UTTER_MS = 15000; // hard cap on one utterance
const NO_SPEECH_MS = 8000; // give up waiting for speech onset (one-shot)
const POLL_MS = 100;

// mic constraints: echo cancellation is what makes talk-over possible — it
// subtracts RESOLVE's own TTS (played through the speakers) from the mic signal
// so the barge-in detector mostly sees your voice, not the reply.
const MIC_CONSTRAINTS: MediaStreamConstraints = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

function makeAudioContext(): AudioContext {
  const AC =
    window.AudioContext ||
    (window as unknown as { webkitAudioContext: typeof AudioContext }).webkitAudioContext;
  return new AC();
}

function rmsOf(analyser: AnalyserNode): number {
  const buf = new Uint8Array(analyser.fftSize);
  analyser.getByteTimeDomainData(buf);
  let sum = 0;
  for (let i = 0; i < buf.length; i++) {
    const v = (buf[i] - 128) / 128;
    sum += v * v;
  }
  return Math.sqrt(sum / buf.length);
}

// Barge-in: while RESOLVE is speaking, listen ONLY for your voice energy (no
// transcription, no API calls). Once you talk over it for BARGE_SUSTAIN_MS, fire
// onInterrupt so the caller can cut the reply and capture your command. Returns
// a teardown you call when the reply ends. Best-effort; works best with the AEC
// (or headphones).
//
// Threshold sits just above the main VAD's speech-onset level (SPEECH_ON=0.045)
// so a genuine talk-over triggers it, but residual (echo-cancelled) TTS doesn't.
const BARGE_ON = 0.05;
const BARGE_SUSTAIN_MS = 240;

// For detection we keep echo cancellation (kills the TTS) but drop auto-gain so
// your real loudness shows through instead of being normalised flat.
const INTERRUPT_CONSTRAINTS: MediaStreamConstraints = {
  audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: false },
};

export function listenForInterrupt(onInterrupt: () => void): () => void {
  let stream: MediaStream | null = null;
  let audioCtx: AudioContext | null = null;
  let poll: ReturnType<typeof setInterval> | null = null;
  let disposed = false;
  let loudStart = 0;

  const cleanup = () => {
    if (disposed) return;
    disposed = true;
    if (poll) clearInterval(poll);
    poll = null;
    if (stream) stream.getTracks().forEach((t) => t.stop());
    stream = null;
    if (audioCtx) audioCtx.close().catch(() => {});
    audioCtx = null;
  };

  (async () => {
    let s: MediaStream;
    try {
      s = await navigator.mediaDevices.getUserMedia(INTERRUPT_CONSTRAINTS);
    } catch {
      return;
    }
    if (disposed) {
      s.getTracks().forEach((t) => t.stop());
      return;
    }
    stream = s;
    audioCtx = makeAudioContext();
    if (audioCtx.state === "suspended") audioCtx.resume().catch(() => {});
    const analyser = audioCtx.createAnalyser();
    analyser.fftSize = 2048;
    audioCtx.createMediaStreamSource(stream).connect(analyser);
    poll = setInterval(() => {
      const now = Date.now();
      if (rmsOf(analyser) > BARGE_ON) {
        if (!loudStart) loudStart = now;
        else if (now - loudStart > BARGE_SUSTAIN_MS) {
          cleanup();
          onInterrupt();
        }
      } else {
        loudStart = 0;
      }
    }, POLL_MS);
  })();

  return cleanup;
}

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
    return analyser ? rmsOf(analyser) : 0;
  }

  async function begin() {
    if (disposed) return;
    try {
      stream = await navigator.mediaDevices.getUserMedia(MIC_CONSTRAINTS);
    } catch {
      rec.onerror?.();
      rec.onend?.();
      return;
    }
    mime = pickMime();
    audioCtx = makeAudioContext();
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
