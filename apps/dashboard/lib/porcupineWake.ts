"use client";

// Dedicated always-on wake-word detection via Picovoice Porcupine (a WASM
// engine running in a Web Worker off the main thread). This is the reliable,
// hands-free path — unlike the Web Speech fallback it truly stays armed and
// doesn't drop the phrase on silence timeouts.
//
// Enabled when NEXT_PUBLIC_PICOVOICE_ACCESS_KEY is set (free key from
// console.picovoice.ai; NEXT_PUBLIC_* is inlined at build time, so it must be
// present when the dashboard is built/deployed). Keyword selection, in order:
//   1. NEXT_PUBLIC_WAKE_KEYWORD_PATH  — a custom .ppn served from /public
//      (train "resolve" / "hey resolve" in the Picovoice console, drop the file
//      in public/wake/, set this to e.g. /wake/resolve.ppn).
//   2. NEXT_PUBLIC_WAKE_PHRASE        — trained in-browser from this phrase
//      (default "hey resolve"); no console trip needed, just the access key.
//   3. built-in "Jarvis"             — fallback if phrase training fails.
//
// The English model is bundled at /models/porcupine_params.pv.

const MODEL_PATH = "/models/porcupine_params.pv";

export function porcupineConfigured(): boolean {
  return Boolean(process.env.NEXT_PUBLIC_PICOVOICE_ACCESS_KEY);
}

/** Starts Porcupine listening for the wake word. Resolves to a teardown fn.
 *  Throws if it can't initialise (caller falls back to Web Speech). */
export async function startPorcupine(onWake: () => void): Promise<() => void> {
  const accessKey = process.env.NEXT_PUBLIC_PICOVOICE_ACCESS_KEY;
  if (!accessKey) throw new Error("Porcupine: no access key");

  const { PorcupineWorker, Porcupine, BuiltInKeyword } = await import(
    "@picovoice/porcupine-web"
  );
  const { WebVoiceProcessor } = await import("@picovoice/web-voice-processor");

  const model = { publicPath: MODEL_PATH, customWritePath: "porcupine_params_v4.pv" };

  // Resolve the keyword per the precedence above.
  const keywordPath = process.env.NEXT_PUBLIC_WAKE_KEYWORD_PATH;
  const phrase = process.env.NEXT_PUBLIC_WAKE_PHRASE ?? "hey resolve";
  let keyword: unknown;
  if (keywordPath) {
    keyword = { label: "resolve", publicPath: keywordPath, sensitivity: 0.6 };
  } else {
    try {
      keyword = await Porcupine.trainWakeWordFromPhrase(accessKey, "wake.ppn", "en", phrase);
    } catch {
      keyword = BuiltInKeyword.Jarvis; // graceful fallback: no training needed
    }
  }

  const worker = await PorcupineWorker.create(
    accessKey,
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    keyword as any,
    () => onWake(),
    model,
  );
  await WebVoiceProcessor.subscribe(worker);

  return async () => {
    try {
      await WebVoiceProcessor.unsubscribe(worker);
    } catch {
      /* noop */
    }
    try {
      await worker.release();
      worker.terminate();
    } catch {
      /* noop */
    }
  };
}
