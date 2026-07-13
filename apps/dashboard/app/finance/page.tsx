"use client";

// Separate finance page — expenses vs. earnings, powered by SimpleFIN (read-only
// bank data). Reached at /finance, behind the same gate as the dashboard. Bank
// login happens on SimpleFIN's site; we only ever hold a read-only access token.

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import styles from "./finance.module.css";

interface Summary {
  days: number;
  netWorth: number;
  earnings: number;
  expenses: number;
  net: number;
  accounts: { id: string; name: string; org?: string; balance: number; currency: string }[];
  byMonth: { month: string; earnings: number; expenses: number }[];
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

export default function FinancePage() {
  const [connected, setConnected] = useState<boolean | null>(null);
  const [days, setDays] = useState(90);
  const [data, setData] = useState<Summary | null>(null);
  const [loading, setLoading] = useState(false);
  const [token, setToken] = useState("");
  const [connecting, setConnecting] = useState(false);
  const [err, setErr] = useState("");

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

  const maxBar = data
    ? Math.max(1, ...data.byMonth.flatMap((m) => [m.earnings, m.expenses]))
    : 1;

  return (
    <div className={styles.page}>
      <div className={styles.head}>
        <Link href="/" className={styles.back}>
          ← Command center
        </Link>
        <div className={styles.title}>
          RESOLVE <span>· Finance</span>
        </div>
        <div className={styles.spacer} />
        {connected && (
          <div className={styles.period}>
            {[30, 90, 365].map((d) => (
              <button key={d} data-on={days === d} onClick={() => pickPeriod(d)}>
                {d === 365 ? "1y" : `${d}d`}
              </button>
            ))}
          </div>
        )}
      </div>

      {connected === null && <div className={styles.muted}>Loading…</div>}

      {connected === false && (
        <div className={styles.connect}>
          <div className={styles.title} style={{ marginBottom: 8 }}>
            Connect your bank
          </div>
          <p className={styles.hint}>
            Go to{" "}
            <a href="https://beta-bridge.simplefin.org/" target="_blank" rel="noreferrer">
              SimpleFIN Bridge
            </a>
            , connect Bank of America, and paste the <b>Setup Token</b> it gives you below. Your
            bank login stays on SimpleFIN — RESOLVE only gets read-only data.
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
          <div className={styles.cards}>
            <div className={styles.card}>
              <div className={styles.label}>Net worth</div>
              <div className={styles.value}>{usd(data.netWorth)}</div>
            </div>
            <div className={styles.card}>
              <div className={styles.label}>Earnings · {days}d</div>
              <div className={`${styles.value} ${styles.pos}`}>{usd(data.earnings)}</div>
            </div>
            <div className={styles.card}>
              <div className={styles.label}>Expenses · {days}d</div>
              <div className={`${styles.value} ${styles.neg}`}>{usd(data.expenses)}</div>
            </div>
            <div className={styles.card}>
              <div className={styles.label}>Net · {days}d</div>
              <div className={`${styles.value} ${data.net >= 0 ? styles.pos : styles.neg}`}>
                {usd(data.net)}
              </div>
            </div>
          </div>

          {data.byMonth.length > 0 && (
            <div className={styles.panel}>
              <div className={styles.panelTitle}>Earnings vs. expenses by month</div>
              <div className={styles.bars}>
                {data.byMonth.map((m) => (
                  <div key={m.month} className={styles.barCol}>
                    <div className={styles.barPair}>
                      <div
                        className={styles.barIn}
                        style={{ height: `${(m.earnings / maxBar) * 100}%` }}
                        title={`In: ${usd2(m.earnings)}`}
                      />
                      <div
                        className={styles.barOut}
                        style={{ height: `${(m.expenses / maxBar) * 100}%` }}
                        title={`Out: ${usd2(m.expenses)}`}
                      />
                    </div>
                    <div className={styles.barLabel}>{m.month.slice(2)}</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className={styles.panel}>
            <div className={styles.panelTitle}>Accounts</div>
            {data.accounts.map((a) => (
              <div key={a.id} className={styles.acct}>
                <span>
                  <span className={styles.acctName}>{a.name}</span>
                  {a.org && <span className={styles.acctOrg}>{a.org}</span>}
                </span>
                <span>{usd2(a.balance)}</span>
              </div>
            ))}
          </div>

          <div className={styles.panel}>
            <div className={styles.panelTitle}>Recent transactions</div>
            {data.transactions.map((t) => (
              <div key={t.id} className={`${styles.txn} ${t.pending ? styles.pending : ""}`}>
                <span className={styles.txnDate}>{t.date}</span>
                <span>
                  <span className={styles.txnDesc}>{t.description || "—"}</span>
                  <span className={styles.txnAcct}> · {t.account}</span>
                </span>
                <span className={`${styles.txnAmt} ${t.amount >= 0 ? styles.pos : styles.neg}`}>
                  {t.amount >= 0 ? "+" : "−"}
                  {usd2(Math.abs(t.amount))}
                </span>
              </div>
            ))}
            {data.transactions.length === 0 && (
              <div className={styles.muted}>No transactions in this period.</div>
            )}
          </div>
        </>
      )}

      {loading && connected && <div className={styles.muted}>Refreshing…</div>}
    </div>
  );
}
