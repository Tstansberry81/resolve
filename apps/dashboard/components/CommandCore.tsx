"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { engine, useEngine } from "@/lib/useEngine";
import { makeRecognition, preloadVoices, speak, type SpeechRecognitionLike } from "@/lib/speech";
import {
  getVoice,
  isSleepPhrase,
  setActive,
  subscribeVoice,
} from "@/lib/voice";

const STATE_LABEL: Record<string, string> = {
  idle: "STANDING BY",
  listening: "LISTENING",
  thinking: "THINKING",
  executing: "EXECUTING",
  waiting: "AWAITING YOU",
};

const EMPTY_VOICE = { wakeOn: false, active: false, speaking: false };

export function CommandCore() {
  const { orb, orbCaption, emergencyStopped } = useEngine();
  const voice = useSyncExternalStore(subscribeVoice, getVoice, () => EMPTY_VOICE);
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const activeRef = useRef(false);
  activeRef.current = voice.active;

  const submit = () => {
    const t = text.trim();
    if (!t || emergencyStopped) return;
    engine.submitCommand(t);
    setText("");
  };

  // Push-to-talk (one-shot) — unchanged behaviour, shared recognizer.
  const toggleMic = () => {
    if (listening) {
      recRef.current?.stop();
      return;
    }
    const rec = makeRecognition();
    if (!rec) {
      setText("Voice input needs Chrome, Edge, or Safari");
      return;
    }
    recRef.current = rec;
    rec.lang = "en-US";
    rec.continuous = false;
    rec.interimResults = false;
    rec.onresult = (e) => {
      const heard = e.results[0]?.[0]?.transcript ?? "";
      if (heard.trim()) engine.submitCommand(heard.trim());
    };
    rec.onend = () => setListening(false);
    setListening(true);
    rec.start();
  };

  useEffect(() => {
    preloadVoices();
  }, []);

  // Conversation loop — runs while voice mode is active (flipped on by the wake
  // word). Turn-based for reliability: it never opens the mic while RESOLVE is
  // speaking (so it can't hear itself), retries if the browser refuses to start
  // recognition (single-mic contention with the wake listener), and "stand
  // down" ends the session.
  useEffect(() => {
    if (!voice.active || emergencyStopped) return;
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout> | null = null;

    const arm = (delay: number) => {
      if (timer) clearTimeout(timer);
      timer = setTimeout(listenOnce, delay);
    };

    function isSpeaking() {
      return getVoice().speaking || window.speechSynthesis?.speaking === true;
    }

    function listenOnce() {
      if (cancelled || !activeRef.current) return;
      // hold the mic shut until we've finished talking
      if (isSpeaking()) {
        arm(300);
        return;
      }
      const rec = makeRecognition();
      if (!rec) return;
      recRef.current = rec;
      rec.lang = "en-US";
      rec.continuous = false;
      rec.interimResults = false;
      let got = false;
      setListening(true);
      rec.onresult = (e) => {
        const heard = (e.results[0]?.[0]?.transcript ?? "").trim();
        if (!heard) return;
        got = true;
        if (isSleepPhrase(heard)) {
          setActive(false);
          speak("Standing down.");
          return;
        }
        engine.submitCommand(heard);
      };
      rec.onend = () => {
        setListening(false);
        recRef.current = null;
        if (cancelled || !activeRef.current) return;
        // after a captured command, give the reply time to arrive and start
        // speaking; the speaking-gate above then holds until it's done.
        arm(got ? 1600 : 350);
      };
      rec.onerror = () => setListening(false); // onend follows and re-arms
      try {
        rec.start();
      } catch {
        // mic still held by the wake recognizer — back off and retry
        recRef.current = null;
        setListening(false);
        arm(450);
      }
    }

    arm(450); // let the wake recognizer release + the "Yes?" greeting play first
    return () => {
      cancelled = true;
      if (timer) clearTimeout(timer);
      const rec = recRef.current;
      recRef.current = null;
      if (rec) {
        rec.onresult = rec.onend = rec.onerror = null;
        try {
          rec.abort();
        } catch {
          /* noop */
        }
      }
      setListening(false);
    };
  }, [voice.active, emergencyStopped]);

  const micActive = listening || voice.active;

  return (
    <div className="core-v2">
      <span className="core-state" data-state={voice.active ? "listening" : orb}>
        {voice.active ? "VOICE MODE" : STATE_LABEL[orb]}
      </span>

      <div className="orb-stage" data-state={voice.active ? "listening" : orb} data-voice={voice.active}>
        <div className="orb-halo" />
        <div className="orb-ring orb-ring-a" />
        <div className="orb-ring orb-ring-b" />
        <div className="orb">
          <div className="orb-inner" />
        </div>
      </div>

      <p className="orb-caption">
        {voice.active ? (listening ? "Listening…" : "Voice mode — say “stand down” to stop") : orbCaption}
      </p>

      <div className="command-bar">
        <button
          className="mic"
          title={micActive ? "Listening — tap to stop" : "Speak a command"}
          aria-label="Voice command"
          disabled={emergencyStopped}
          style={micActive ? { color: "#35e39c" } : undefined}
          onClick={toggleMic}
        >
          <svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round">
            <rect x="9" y="3" width="6" height="11" rx="3" />
            <path d="M5 11a7 7 0 0 0 14 0" />
            <path d="M12 18v3" />
          </svg>
        </button>
        <input
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && submit()}
          placeholder={
            emergencyStopped
              ? "Execution halted — resume to issue commands"
              : "Tell Sonnet what you need…"
          }
          disabled={emergencyStopped}
          aria-label="Command input"
        />
        <button className="send" onClick={submit} disabled={emergencyStopped}>
          RUN
        </button>
      </div>
    </div>
  );
}
