"use client";

// Separate finance page — checking, savings, and checking P/L, with a net-worth
// line chart. Powered by SimpleFIN (read-only). Behind the same gate as the app.

import { type MouseEvent, useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { Starfield } from "@/components/Starfield";
import styles from "./finance.module.css";

interface Acct {
  name: string;
  balance: number;
}
interface Summary {
  days: number;
  capped: boolean;
  checking: Acct | null;
  savings: Acct | null;
  other: (Acct | null)[];
  netWorth: number;
  checkingPL: number;
  earnings: number;
  expenses: number;
  netWorthSeries: { date: string; value: number }[];
  transactions: {
    id: string;
    account: string;
    amount: number;
    description: string;
    date: string;
    pending: boolean;
  }[];
}

const usd = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD", maximumFractionDigits: 0 });
const usd2 = (n: number) =>
  n.toLocaleString("en-US", { style: "currency", currency: "USD" });

function NetWorthChart({ series }: { series: { date: string; value: number }[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (series.length < 2) {
    return <div className={styles.muted}>Net-worth trend appears once there are a few days of history.</div>;
  }
  const W = 720;
  const H = 170;
  const pad = { l: 4, r: 4, t: 12, b: 18 };
  const vals = series.map((p) => p.value);
  const min = Math.min(...vals);
  const max = Math.max(...vals);
  const span = max - min || 1;
  const x = (i: number) => pad.l + (i / (series.length - 1)) * (W - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - min) / span) * (H - pad.t - pad.b);
  const line = series.map((p, i) => `${i === 0 ? "M" : "L"}${x(i).toFixed(1)},${y(p.value).toFixed(1)}`).join(" ");
  const area = `${line} L${x(series.length - 1).toFixed(1)},${H - pad.b} L${x(0).toFixed(1)},${H - pad.b} Z`;
  const up = series[series.length - 1].value >= series[0].value;
  const stroke = up ? "var(--green)" : "var(--red, #ff6b6b)";

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    const i = Math.max(0, Math.min(series.length - 1, Math.round(frac * (series.length - 1))));
    setHover(i);
  };

  const hp = hover != null ? series[hover] : null;
  const hxPct = hover != null ? (x(hover) / W) * 100 : 0;
  const hyPct = hp ? (y(hp.value) / H) * 100 : 0;
  const tipLeft = Math.min(92, Math.max(8, hxPct));

  return (
    <div className={styles.chartWrap} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" preserveAspectRatio="none" role="img">
        <defs>
          <linearGradient id="nwfill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor={stroke} stopOpacity="0.28" />
            <stop offset="100%" stopColor={stroke} stopOpacity="0" />
          </linearGradient>
        </defs>
        <path d={area} fill="url(#nwfill)" />
        <path d={line} fill="none" stroke={stroke} strokeWidth="2" strokeLinejoin="round" />
        <text x={pad.l} y={H - 4} className={styles.axis}>{series[0].date.slice(2)}</text>
        <text x={W - pad.r} y={H - 4} textAnchor="end" className={styles.axis}>
          {series[series.length - 1].date.slice(2)}
        </text>
      </svg>
      {hp && (
        <>
          <div className={styles.guide} style={{ left: `${hxPct}%` }} />
          <div className={styles.dot} style={{ left: `${hxPct}%`, top: `${hyPct}%`, background: stroke }} />
          <div className={styles.tip} style={{ left: `${tipLeft}%` }}>
            <div className={styles.tipVal}>{usd2(hp.value)}</div>
            <div className={styles.tipDate}>{hp.date}</div>
          </div>
        </>
      )}
    </div>
  );
}

export default function FinancePage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [days, setDays] = useState(30);
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [token, setToken] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [err, setErr] = useState("");
  const [showAllTxns, setShowAllTxns] = useState(false);

  const loadSummary = useCallback(async (d: number) => {
    setLoading(true);
    setErr("");
    try {
      const r = await fetch(`/api/cp/v1/finance/summary?days=${d}`, { cache: "no-store" });
      if (r.status === 409) {
        setConnected(false);
        return;
      }
      if (!r.ok) throw new Error(await r.text());
      setData(await r.json());
      setConnected(true);
    } catch (e) {
      setErr(String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    (async () => {
      try {
        const r = await fetch("/api/cp/v1/finance/status", { cache: "no-store" });
        const j = await r.json();
        if (j.connected) {
          setConnected(true);
          loadSummary(days);
        } else {
          setConnected(false);
        }
      } catch {
        setConnected(false);
      }
    })();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const pickPeriod = (d: number) => {
    setDays(d);
    loadSummary(d);
  };

  const connect = async () => {
    if (!token.trim()) return;
    setConnecting(true);
    setErr("");
    try {
      const r = await fetch("/api/cp/v1/finance/connect", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ setup_token: token.trim() }),
      });
      if (!r.ok) throw new Error(await r.text());
      setToken("");
      setConnected(true);
      loadSummary(days);
    } catch (e) {
      setErr(String(e));
    } finally {
      setConnecting(false);
    }
  };

  const label = (d: number) => (d === 365 ? "1y" : `${d}d`);

  return (
    <>
    <Starfield />
    <div className={styles.page}>
      <div className={styles.head}>
        <Link href="/" className={styles.back}>← Command center</Link>
        <div className={styles.title}>RESOLVE <span>· Finance</span></div>
        <div className={styles.spacer} />
        {connected && (
          <div className={styles.period}>
            {[30, 60, 365].map((d) => (
              <button key={d} data-on={days === d} onClick={() => pickPeriod(d)}>
                {label(d)}
              </button>
            ))}
          </div>
        )}
      </div>

      {connected === null && <div className={styles.muted}>Loading…</div>}

      {connected === false && (
        <div className={styles.connect}>
          <div className={styles.title} style={{ marginBottom: 8 }}>Connect your bank</div>
          <p className={styles.hint}>
            Go to{" "}
            <a href="https://beta-bridge.simplefin.org/" target="_blank" rel="noreferrer">SimpleFIN Bridge</a>
            , connect Bank of America, and paste the <b>Setup Token</b> below. Your bank login
            stays on SimpleFIN — RESOLVE only gets read-only data.
          </p>
          <input
            value={token}
            onChange={(e) => setToken(e.target.value)}
            placeholder="Paste SimpleFIN setup token…"
            spellCheck={false}
          />
          <button onClick={connect} disabled={connecting || !token.trim()}>
            {connecting ? "Connecting…" : "Connect"}
          </button>
          {err && <div className={styles.err}>{err}</div>}
        </div>
      )}

      {connected && data && (
        <>
          <div className={styles.cards3}>
            <div className={styles.card}>
              <div className={styles.label}>Checking</div>
              <div className={styles.value}>{data.checking ? usd2(data.checking.balance) : "—"}</div>
              {data.checking && <div className={styles.sub}>{data.checking.name}</div>}
            </div>
            <div className={styles.card}>
              <div className={styles.label}>Savings</div>
              <div className={styles.value}>{data.savings ? usd2(data.savings.balance) : "—"}</div>
              {data.savings && <div className={styles.sub}>{data.savings.name}</div>}
            </div>
            <div className={styles.card}>
              <div className={styles.label}>Checking {label(days)} · net</div>
              <div className={`${styles.value} ${data.checkingPL >= 0 ? styles.pos : styles.neg}`}>
                {data.checkingPL >= 0 ? "+" : "−"}{usd2(Math.abs(data.checkingPL))}
              </div>
              <div className={styles.sub}>profit / loss</div>
            </div>
          </div>

          <div className={styles.panel}>
            <div className={styles.panelTitle}>Net worth · {usd(data.netWorth)}</div>
            <NetWorthChart series={data.netWorthSeries} />
            {data.capped && (
              <div className={styles.note}>
                SimpleFIN provides 90 days of history — the 1-year view fills in from here as
                daily snapshots accumulate.
              </div>
            )}
          </div>

          <div className={styles.panel}>
            <div className={styles.panelTitle}>Recent transactions</div>
            {(showAllTxns ? data.transactions : data.transactions.slice(0, 3)).map((t) => (
              <div key={t.id} className={`${styles.txn} ${t.pending ? styles.pending : ""}`}>
                <span className={styles.txnDate}>{t.date}</span>
                <span>
                  <span className={styles.txnDesc}>{t.description || "—"}</span>
                  <span className={styles.txnAcct}> · {t.account}</span>
                </span>
                <span className={`${styles.txnAmt} ${t.amount >= 0 ? styles.pos : styles.neg}`}>
                  {t.amount >= 0 ? "+" : "−"}{usd2(Math.abs(t.amount))}
                </span>
              </div>
            ))}
            {data.transactions.length === 0 && (
              <div className={styles.muted}>No transactions in this period.</div>
            )}
            {data.transactions.length > 3 && (
              <button className={styles.moreBtn} onClick={() => setShowAllTxns((v) => !v)}>
                {showAllTxns ? "Show fewer ▴" : `Show all ${data.transactions.length} ▾`}
              </button>
            )}
          </div>
        </>
      )}

      {loading && connected && <div className={styles.muted}>Refreshing…</div>}
    </div>
    </>
  );
}
