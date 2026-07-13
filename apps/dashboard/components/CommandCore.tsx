"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { engine, useEngine } from "@/lib/useEngine";
import {
  cancelSpeech,
  isMobile,
  makeRecognition,
  preloadVoices,
  speak,
  usesSttEngine,
  type SpeechRecognitionLike,
} from "@/lib/speech";
import {
  getVoice,
  isSleepPhrase,
  setActive,
  subscribeVoice,
} from "@/lib/voice";
import { listenForInterrupt } from "@/lib/sttRecognition";

const STATE_LABEL: Record<string, string> = {
  idle: "STANDING BY",
  listening: "LISTENING",
  thinking: "THINKING",
  executing: "EXECUTING",
  waiting: "AWAITING YOU",
};

const EMPTY_VOICE = { wakeOn: false, active: false, speaking: false };

export function CommandCore() {
  const { orb, orbCaption, emergencyStopped, events } = useEngine();
  const voice = useSyncExternalStore(subscribeVoice, getVoice, () => EMPTY_VOICE);
  const [text, setText] = useState("");
  const [listening, setListening] = useState(false);
  const [flare, setFlare] = useState(false);
  const recRef = useRef<SpeechRecognitionLike | null>(null);
  const activeRef = useRef(false);
  activeRef.current = voice.active;
  const flareSeenRef = useRef<number | null>(null);

  // Green flare when a mission/step completes. Event ids are monotonic, so we
  // track the newest completion we've flared for (order-independent) and skip
  // whatever was already in the feed at mount.
  useEffect(() => {
    let newest = -1;
    for (const e of events) {
      if ((e.type === "goal.completed" || e.type === "task.completed") && e.id > newest) {
        newest = e.id;
      }
    }
    if (flareSeenRef.current === null) {
      flareSeenRef.current = newest; // first pass: don't flare for history
      return;
    }
    if (newest > flareSeenRef.current) {
      flareSeenRef.current = newest;
      setFlare(true);
      const t = setTimeout(() => setFlare(false), 1600);
      return () => clearTimeout(t);
    }
  }, [events]);

  const submit = () => {
    const t = text.trim();
    if (!t || emergencyStopped) return;
    engine.submitCommand(t);
    setText("");
  };

  // Push-to-talk (one-shot) — and, in voice-conversation mode, a guaranteed
  // manual interrupt: tap while RESOLVE is talking to cut it off and listen.
  const toggleMic = () => {
    if (voice.active) {
      stopBargeIn(); // also stops the STT interrupt listener
      cancelSpeech(); // kill the reply immediately
      phaseRef.current = "listening";
      openMic();
      return;
    }
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

  // ── Voice conversation loop (strictly turn-based) ────────────────────────
  // Phases: listening → awaiting (mic shut, waiting on the reply) → speaking
  // (reply plays, mic shut) → listening. The mic is NEVER open while RESOLVE is
  // talking, so its own voice can't leak back in. CommandCore speaks the reply
  // itself (ChatStrip stays quiet in voice mode) so it controls the hand-back.
  const phaseRef = useRef<"off" | "listening" | "awaiting" | "speaking">("off");
  const pendingIdRef = useRef<number>(-1);
  const awaitTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const bargeRef = useRef<SpeechRecognitionLike | null>(null);
  const spokenTextRef = useRef<string>("");
  const eventsRef = useRef(events);
  eventsRef.current = events;

  const maxEventId = () => {
    let m = -1;
    for (const e of eventsRef.current) if (e.id > m) m = e.id;
    return m;
  };
  const speakingNow = () =>
    getVoice().speaking || window.speechSynthesis?.speaking === true;

  const stopConvMic = () => {
    const r = recRef.current;
    recRef.current = null;
    if (r) {
      r.onresult = r.onend = r.onerror = null;
      try {
        r.abort();
      } catch {
        /* noop */
      }
    }
  };

  // Is `heard` just our own TTS leaking back through the mic? If most of its
  // words are in what we're currently saying, it's echo — ignore it.
  const isEcho = (heard: string): boolean => {
    const norm = (s: string) =>
      s.toLowerCase().replace(/[^a-z0-9 ]/g, " ").split(/\s+/).filter(Boolean);
    const h = norm(heard);
    if (h.length < 2) return true; // too short to trust as a real interruption
    const said = new Set(norm(spokenTextRef.current));
    const overlap = h.filter((w) => said.has(w)).length / h.length;
    return overlap > 0.5;
  };

  const stopBargeIn = () => {
    const r = bargeRef.current;
    bargeRef.current = null;
    if (r) {
      r.onresult = r.onend = r.onerror = null;
      try {
        r.abort();
      } catch {
        /* noop */
      }
    }
    stopSttBargeIn();
  };

  // STT barge-in: energy-only interrupt detection (no transcription of our own
  // TTS). When Trav talks over the reply, cut it and capture his command.
  const sttBargeStopRef = useRef<(() => void) | null>(null);
  const stopSttBargeIn = () => {
    const stop = sttBargeStopRef.current;
    sttBargeStopRef.current = null;
    stop?.();
  };
  function startSttBargeIn() {
    if (!activeRef.current || phaseRef.current !== "speaking") return;
    sttBargeStopRef.current = listenForInterrupt(() => {
      sttBargeStopRef.current = null;
      cancelSpeech(); // cut the reply the instant he talks over it
      if (activeRef.current) {
        phaseRef.current = "listening";
        openMic();
      }
    });
  }

  // Listen WHILE RESOLVE is speaking so Trav can cut it off. The mic hears the
  // TTS too, so we filter that echo; a genuine interruption cancels the reply
  // and is handled as the next turn. Best-effort — works best with headphones.
  function startBargeIn() {
    if (!activeRef.current || phaseRef.current !== "speaking") return;
    const rec = makeRecognition();
    if (!rec) return;
    bargeRef.current = rec;
    rec.lang = "en-US";
    rec.continuous = true;
    rec.interimResults = true;
    rec.onresult = (e) => {
      const last = e.results[e.results.length - 1];
      const heard = (last?.[0]?.transcript ?? "").trim();
      if (!heard || isEcho(heard)) return;
      stopBargeIn();
      cancelSpeech(); // cut the reply off mid-sentence
      onHeard(heard); // treat the interruption as the next command
    };
    rec.onend = () => {
      if (phaseRef.current === "speaking" && activeRef.current) {
        window.setTimeout(startBargeIn, 200); // stay armed until the reply ends
      }
    };
    rec.onerror = () => {};
    try {
      rec.start();
    } catch {
      /* barge-in is best-effort */
    }
  }

  const onHeard = (heard: string) => {
    setListening(false);
    if (isSleepPhrase(heard)) {
      phaseRef.current = "off";
      setActive(false);
      speak("Standing down.");
      return;
    }
    phaseRef.current = "awaiting";
    pendingIdRef.current = maxEventId();
    engine.submitCommand(heard);
    // safety: if no reply ever comes back, reopen the mic rather than hang
    if (awaitTimerRef.current) clearTimeout(awaitTimerRef.current);
    awaitTimerRef.current = setTimeout(() => {
      if (phaseRef.current === "awaiting" && activeRef.current) {
        phaseRef.current = "listening";
        openMic();
      }
    }, 20000);
  };

  function openMic() {
    if (!activeRef.current || phaseRef.current === "off") return;
    if (speakingNow()) {
      window.setTimeout(openMic, 250); // wait until we're done talking
      return;
    }
    const rec = makeRecognition();
    if (!rec) return;
    recRef.current = rec;
    rec.lang = "en-US";
    rec.continuous = false;
    rec.interimResults = false;
    phaseRef.current = "listening";
    setListening(true);
    let got = false;
    rec.onresult = (e) => {
      const heard = (e.results[0]?.[0]?.transcript ?? "").trim();
      if (!heard) return;
      got = true;
      recRef.current = null;
      try {
        rec.abort();
      } catch {
        /* noop */
      }
      onHeard(heard);
    };
    rec.onend = () => {
      setListening(false);
      if (recRef.current === rec) recRef.current = null;
      // silence/timeout with nothing captured — reopen the mic
      if (!got && activeRef.current && phaseRef.current === "listening") {
        window.setTimeout(openMic, 300);
      }
    };
    rec.onerror = () => setListening(false);
    try {
      rec.start();
    } catch {
      window.setTimeout(openMic, 400);
    }
  }

  // start/stop the loop with voice mode
  useEffect(() => {
    if (!voice.active || emergencyStopped) {
      phaseRef.current = "off";
      if (awaitTimerRef.current) clearTimeout(awaitTimerRef.current);
      stopConvMic();
      stopBargeIn();
      cancelSpeech(); // go quiet the instant voice mode turns off
      setListening(false);
      return;
    }
    phaseRef.current = "listening";
    const t = setTimeout(openMic, 500); // let the "Yes?" greeting play first
    return () => {
      phaseRef.current = "off";
      clearTimeout(t);
      if (awaitTimerRef.current) clearTimeout(awaitTimerRef.current);
      stopConvMic();
      stopBargeIn();
      setListening(false);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [voice.active, emergencyStopped]);

  // while awaiting, watch for RESOLVE's reply, speak it, then reopen the mic
  useEffect(() => {
    if (phaseRef.current !== "awaiting") return;
    let reply: { id: number; text: string } | null = null;
    for (const e of events) {
      if (e.type === "assistant.reply" && e.id > pendingIdRef.current) {
        if (!reply || e.id > reply.id) reply = { id: e.id, text: e.detail ?? e.summary };
      }
    }
    if (!reply) return;
    if (awaitTimerRef.current) clearTimeout(awaitTimerRef.current);
    phaseRef.current = "speaking";
    spokenTextRef.current = reply.text;
    speak(reply.text, {
      onend: () => {
        stopBargeIn();
        if (activeRef.current && phaseRef.current === "speaking") {
          phaseRef.current = "listening";
          openMic();
        } else if (!activeRef.current) {
          phaseRef.current = "off";
        }
      },
    });
    // talk-over (desktop only — iOS mutes replies when the mic is live). Under
    // server-STT we use energy-only interrupt detection; browsers use the Web
    // Speech recognizer with echo filtering.
    if (!isMobile()) {
      if (usesSttEngine()) startSttBargeIn();
      else startBargeIn();
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [events]);

  const micActive = listening || voice.active;

  return (
    <div className="core-v2">
      <span className="core-state" data-state={voice.active ? "listening" : orb}>
        {voice.active ? "VOICE MODE" : STATE_LABEL[orb]}
      </span>

      <div
        className="orb-stage"
        data-state={voice.active ? "listening" : orb}
        data-voice={voice.active}
        data-flare={flare}
      >
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
