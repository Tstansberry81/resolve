"use client";

// On-device wake-word detection via openWakeWord (Apache/MIT models) running in
// the browser with onnxruntime-web + an AudioWorklet — fully local, no network,
// no per-use cost, and NO licensing gate. This replaces Picovoice Porcupine,
// whose free tier turned out to require a paid/enterprise plan for a custom
// production wake word.
//
// It listens for the pretrained "hey_jarvis" phrase (fitting for RESOLVE's
// Jarvis-style assistant; a custom "hey resolve" model can be trained later and
// dropped in as another .onnx). Models are self-hosted from /public; the ONNX
// Runtime WASM loads from its CDN by default (the dashboard is served online).
//
// Env (all NEXT_PUBLIC_*, inlined at build time):
//   NEXT_PUBLIC_WAKE_ENGINE      — set to "off" to disable on-device wake
//   NEXT_PUBLIC_WAKE_KEYWORD     — openWakeWord keyword (default "hey_jarvis")
//   NEXT_PUBLIC_WAKE_THRESHOLD   — detection score 0..1 (default 0.5)
//   NEXT_PUBLIC_WAKE_MODELS_URL  — base URL for the model files

const MODELS_URL = process.env.NEXT_PUBLIC_WAKE_MODELS_URL || "/openwakeword/models";
// Default is our custom-trained "hey resolve" head; swap via env to a pretrained
// keyword (hey_jarvis, alexa, …) or another custom model.
const KEYWORD = process.env.NEXT_PUBLIC_WAKE_KEYWORD || "hey_resolve";
// Filename for the keyword head. Pretrained keywords resolve via the package's
// MODEL_FILE_MAP; a custom keyword defaults to "<keyword>.onnx".
const MODEL_FILE = process.env.NEXT_PUBLIC_WAKE_MODEL_FILE || `${KEYWORD}.onnx`;
const THRESHOLD = Math.min(
  0.95,
  Math.max(0.2, Number(process.env.NEXT_PUBLIC_WAKE_THRESHOLD || "0.5")),
);

/** On-device wake is the default; opt out with NEXT_PUBLIC_WAKE_ENGINE=off. */
export function openWakeConfigured(): boolean {
  return process.env.NEXT_PUBLIC_WAKE_ENGINE !== "off";
}

/** Human-readable phrase for the UI, derived from the keyword id. */
export function wakePhraseLabel(): string {
  return KEYWORD.replace(/_/g, " ");
}

/** Start listening for the wake word. Resolves to a teardown fn. Rejects if it
 *  can't initialise (caller falls back to another engine). */
export async function startOpenWakeWord(onWake: () => void): Promise<() => void> {
  const { WakeWordEngine, MODEL_FILE_MAP } = await import("openwakeword-wasm-browser");

  // Known keywords resolve via the package map; a custom keyword (or an explicit
  // NEXT_PUBLIC_WAKE_MODEL_FILE) maps to its own .onnx file.
  const modelFiles: Record<string, string> = { ...MODEL_FILE_MAP };
  if (process.env.NEXT_PUBLIC_WAKE_MODEL_FILE || !(KEYWORD in MODEL_FILE_MAP)) {
    modelFiles[KEYWORD] = MODEL_FILE;
  }

  const engine = new WakeWordEngine({
    keywords: [KEYWORD],
    modelFiles,
    baseAssetUrl: MODELS_URL,
    detectionThreshold: THRESHOLD,
    cooldownMs: 2500, // ignore repeat fires for 2.5s after a wake
  });

  let fired = false;
  engine.on("detect", () => {
    if (fired) return; // one wake per session; WakeWord tears us down on activate
    fired = true;
    onWake();
  });
  // Non-fatal: surface pipeline hiccups but don't crash the listener.
  engine.on("error", (err: unknown) => {
    // eslint-disable-next-line no-console
    console.warn("openWakeWord:", err);
  });

  await engine.load(); // download + init the ONNX models (throws → caller falls back)
  await engine.start(); // begin mic streaming

  return () => {
    try {
      void engine.stop();
    } catch {
      /* noop */
    }
  };
}
