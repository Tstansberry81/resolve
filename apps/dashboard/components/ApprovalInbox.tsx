"use client";

import { engine, useEngine } from "@/lib/useEngine";
import type { Approval } from "@/lib/types";

const RISK_LABEL: Record<string, string> = {
  communication_send: "sends as you",
  destructive: "hard to reverse",
  financial: "moves money",
  bounded_external_write: "external write",
  reversible_write: "reversible",
};

function ApprovalCard({ a }: { a: Approval }) {
  return (
    <article className="approval" data-status={a.status}>
      <header>
        <span className="chip chip-amber">{a.risk.replace(/_/g, " ")}</span>
        <span className="approval-risk">{RISK_LABEL[a.risk] ?? a.risk}</span>
      </header>
      <h3>{a.actionSummary}</h3>
      <div className="approval-preview">
        {a.preview.map((line, i) => (
          <p key={i}>{line}</p>
        ))}
      </div>
      {a.undoWindow && <p className="approval-undo">undo: {a.undoWindow}</p>}
      {a.status === "pending" ? (
        <div className="approval-actions">
          <button
            className="btn-approve"
            onClick={() => engine.decideApproval(a.id, "approved")}
          >
            APPROVE
          </button>
          <button
            className="btn-reject"
            onClick={() => engine.decideApproval(a.id, "rejected")}
          >
            REJECT
          </button>
        </div>
      ) : (
        <p className={`approval-decided approval-${a.status}`}>
          {a.status === "approved" ? "✓ approved" : "✕ rejected"}
        </p>
      )}
    </article>
  );
}

export function ApprovalInbox() {
  const { approvals } = useEngine();
  const pending = approvals.filter((a) => a.status === "pending");
  const decided = approvals.filter((a) => a.status !== "pending").slice(0, 3);

  return (
    <div className="panel area-approvals approvals">
      <div className="panel-title">
        <span className="dot" style={{ background: "var(--amber)", boxShadow: "0 0 8px var(--amber)" }} />
        Approvals
        <span className="count">
          {pending.length > 0 ? `${pending.length} waiting` : "clear"}
        </span>
      </div>
      <div className="rail">
        {approvals.length === 0 && (
          <p className="empty">Nothing needs your judgment right now.</p>
        )}
        {pending.map((a) => (
          <ApprovalCard key={a.id} a={a} />
        ))}
        {decided.map((a) => (
          <ApprovalCard key={a.id} a={a} />
        ))}
      </div>
    </div>
  );
}
