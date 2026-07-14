"use client";

// Always-on wake-word listener. Engines, picked automatically in priority order:
//  • openWakeWord (onnxruntime-web, on-device) — the default. Free, fully local,
//    no key, stays armed indefinitely. Listens for "hey jarvis".
//  • Porcupine (Picovoice) ONLY if NEXT_PUBLIC_PICOVOICE_ACCESS_KEY is set —
//    kept as an option, but its free tier gates custom production wake words, so
//    it's no longer the default.
//  • Web Speech API — last-resort fallback (browser-flaky; dead in Electron).
// On the wake word it flips voice conversation mode on: CommandCore then listens
// for your command and ChatStrip speaks the replies. The mic is single-instance,
// so while a conversation is active this listener steps aside and re-arms when it
// ends.

import { useEffect, useRef, useSyncExternalStore } from "react";
import {
  getVoice,
  hydrateWake,
  isWakePhrase,
  setActive,
  setWakeOn,
  subscribeVoice,
} from "@/lib/voice";
import { makeRecognition, speak, speechSupported, type SpeechRecognitionLike } from "@/lib/speech";
import { porcupineConfigured, startPorcupine } from "@/lib/porcupineWake";
import { openWakeConfigured, startOpenWakeWord, wakePhraseLabel } from "@/lib/openWakeWord";

const EMPTY = { wakeOn: false, active: false, speaking: false };

export function WakeWord() {
  const voice = useSyncExternalStore(subscribeVoice, getVoice, () => EMPTY);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const restartRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    hydrateWake();
  }, []);

  // Run a wake-word engine only while armed AND not already in a conversation.
  useEffect(() => {
    const shouldListen = voice.wakeOn && !voice.active;
    if (!shouldListen) return;

    let stopped = false;
    let teardownEngine: (() => void) | null = null;

    const onWake = () => {
      if (stopped) return;
      setActive(true);
      speak("Yes?");
    };

    // ── Web Speech fallback ───────────────────────────────────────────────
    const stopWebSpeech = () => {
      if (restartRef.current) {
        clearTimeout(restartRef.current);
        restartRef.current = null;
      }
      const rec = recRef.current;
      recRef.current = null;
      if (rec) {
        rec.onresult = rec.onend = rec.onerror = null;
        try {
          rec.abort();
        } catch {
          /* already stopped */
        }
      }
    };

    const startWebSpeech = () => {
      if (stopped) return;
      const rec = makeRecognition();
      if (!rec) return;
      recRef.current = rec;
      rec.lang = "en-US";
      rec.continuous = true;
      rec.interimResults = true;
      rec.onresult = (e) => {
        let heard = "";
        for (let i = 0; i < e.results.length; i++) heard += e.results[i]?.[0]?.transcript ?? "";
        if (isWakePhrase(heard)) {
          rec.onresult = rec.onend = rec.onerror = null;
          try {
            rec.abort();
          } catch {
            /* noop */
          }
          onWake();
        }
      };
      rec.onend = () => {
        if (!stopped) restartRef.current = setTimeout(startWebSpeech, 400);
      };
      rec.onerror = () => {
        if (!stopped) restartRef.current = setTimeout(startWebSpeech, 800);
      };
      try {
        rec.start();
      } catch {
        /* start races an in-flight session; onend re-arms */
      }
    };

    // Start an async on-device engine; on init failure, run the fallback.
    const startEngine = (
      start: (cb: () => void) => Promise<() => void>,
      fallback: () => void,
    ) => {
      start(onWake)
        .then((teardown) => {
          if (stopped) {
            teardown();
            return;
          }
          teardownEngine = teardown;
        })
        .catch(() => {
          if (!stopped) fallback();
        });
    };

    // ── engine selection (priority: openWakeWord → Porcupine → Web Speech) ──
    if (openWakeConfigured()) {
      startEngine(startOpenWakeWord, () => {
        // on-device wake failed to load — try Porcupine if keyed, else Web Speech
        if (porcupineConfigured()) startEngine(startPorcupine, startWebSpeech);
        else startWebSpeech();
      });
    } else if (porcupineConfigured()) {
      startEngine(startPorcupine, startWebSpeech);
    } else {
      startWebSpeech();
    }

    return () => {
      stopped = true;
      if (teardownEngine) teardownEngine();
      stopWebSpeech();
    };
  }, [voice.wakeOn, voice.active]);

  if (!speechSupported() && !porcupineConfigured() && !openWakeConfigured()) return null;

  // On-device wake matches a fixed phrase ("hey jarvis"); the Web Speech
  // fallback is more forgiving. Show the on-device phrase when it's the engine.
  const phrase = openWakeConfigured() ? wakePhraseLabel() : "hey resolve";
  const label = voice.active
    ? "listening…"
    : voice.wakeOn
      ? `say "${phrase}"`
      : "wake word";

  return (
    <button
      className="wake-toggle"
      data-on={voice.wakeOn}
      data-active={voice.active}
      title={
        voice.wakeOn
          ? `Wake word armed — say "${phrase}". Tap to disarm.`
          : "Arm the wake word so you can start RESOLVE by voice"
      }
      onClick={() => {
        const next = !voice.wakeOn;
        setWakeOn(next);
        if (!next) setActive(false);
      }}
    >
      <span className="wake-dot" />
      {label}
    </button>
  );
}
