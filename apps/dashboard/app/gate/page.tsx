"use client";

import { useState } from "react";
import { Starfield } from "@/components/Starfield";
import s from "./gate.module.css";

export default function Gate() {
  const [password, setPassword] = useState("");
  const [error, setError] = useState(false);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    if (!password || busy) return;
    setBusy(true);
    setError(false);
    const res = await fetch("/api/gate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    }).catch(() => null);
    if (res?.ok) {
      window.location.href = "/";
      return;
    }
    setError(true);
    setBusy(false);
  };

  return (
    <>
      <Starfield />
      <main className={s.wrap}>
        <div className={`${s.card} ${error ? s.shake : ""}`}>
          <span className={s.sigil} aria-hidden />
          <h1 className={s.title}>RESOLVE</h1>
          <p className={s.sub}>This command center is private.</p>
          <input
            className={s.input}
            type="password"
            value={password}
            autoFocus
            placeholder="Password"
            aria-label="Password"
            onChange={(e) => {
              setPassword(e.target.value);
              setError(false);
            }}
            onKeyDown={(e) => e.key === "Enter" && submit()}
          />
          <button className={s.btn} onClick={submit} disabled={busy}>
            {busy ? "…" : "UNLOCK"}
          </button>
          {error && <p className={s.error}>Wrong password.</p>}
        </div>
      </main>
    </>
  );
}
