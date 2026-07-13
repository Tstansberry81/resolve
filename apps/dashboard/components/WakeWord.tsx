"use client";

// Always-on wake-word listener. When armed (👂), it keeps a continuous
// SpeechRecognition running purely to catch "resolve" / "hey resolve" /
// "yo resolve" / "what's up resolve". On a hit it flips voice conversation
// mode on (CommandCore then listens for your command; ChatStrip speaks replies).
// The mic is single-instance, so while conversation mode is active this listener
// steps aside and re-arms itself when the conversation ends.

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

const EMPTY = { wakeOn: false, active: false, speaking: false };

export function WakeWord() {
  const voice = useSyncExternalStore(subscribeVoice, getVoice, () => EMPTY);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const restartRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    hydrateWake();
  }, []);

  // Run the wake recognizer only while armed AND not already in a conversation.
  useEffect(() => {
    const shouldListen = voice.wakeOn && !voice.active;

    const stop = () => {
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

    if (!shouldListen) {
      stop();
      return stop;
    }

    let stopped = false;
    const start = () => {
      if (stopped) return;
      const rec = makeRecognition();
      if (!rec) return;
      recRef.current = rec;
      rec.lang = "en-US";
      rec.continuous = true;
      rec.interimResults = true;
      rec.onresult = (e) => {
        let heard = "";
        for (let i = 0; i < e.results.length; i++) {
          heard += e.results[i]?.[0]?.transcript ?? "";
        }
        if (isWakePhrase(heard)) {
          // Hand the mic over to the conversation loop.
          rec.onresult = rec.onend = rec.onerror = null;
          try {
            rec.abort();
          } catch {
            /* noop */
          }
          setActive(true);
          speak("Yes?");
        }
      };
      // Chrome ends continuous recognition after silence — re-arm shortly.
      rec.onend = () => {
        if (!stopped) restartRef.current = setTimeout(start, 400);
      };
      rec.onerror = () => {
        if (!stopped) restartRef.current = setTimeout(start, 800);
      };
      try {
        rec.start();
      } catch {
        /* start races an in-flight session; onend will re-arm */
      }
    };

    start();
    return () => {
      stopped = true;
      stop();
    };
  }, [voice.wakeOn, voice.active]);

  if (!speechSupported()) return null;

  const label = voice.active
    ? "listening…"
    : voice.wakeOn
      ? 'say "hey resolve"'
      : "wake word";

  return (
    <button
      className="wake-toggle"
      data-on={voice.wakeOn}
      data-active={voice.active}
      title={
        voice.wakeOn
          ? 'Wake word armed — say "resolve", "hey resolve", "yo resolve", or "what\'s up resolve". Tap to disarm.'
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
