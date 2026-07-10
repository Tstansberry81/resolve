"use client";

import { useState } from "react";
import { engine, useEngine } from "@/lib/useEngine";
import type { Approval } from "@/lib/types";

// iOS-style banner notifications, top center. Small by default; tap the text
// to expand the exact action preview. Decided banners linger briefly via the
// engine's approval list ordering, then simply stop rendering.

function Banner({ a }: { a: Approval }) {
  const [expanded, setExpanded] = useState(false);
  return (
    <div className="banner" data-status={a.status}>
      <div className="banner-row">
        <span className="banner-risk">{a.risk.replace(/_/g, " ")}</span>
        <button
          className="banner-text"
          onClick={() => setExpanded((e) => !e)}
          title="Show exact action preview"
        >
          {a.actionSummary}
        </button>
        {a.status === "pending" ? (
          <div className="banner-actions">
            <button
              className="banner-ok"
              onClick={() => engine.decideApproval(a.id, "approved")}
            >
              ✓
            </button>
            <button
              className="banner-no"
              onClick={() => engine.decideApproval(a.id, "rejected")}
            >
              ✕
            </button>
          </div>
        ) : (
          <span className={`banner-decided banner-${a.status}`}>
            {a.status === "approved" ? "✓ approved" : "✕ rejected"}
          </span>
        )}
      </div>
      {expanded && (
        <div className="banner-preview">
          {a.preview.map((line, i) => (
            <p key={i}>{line}</p>
          ))}
          {a.undoWindow && <p className="banner-undo">undo: {a.undoWindow}</p>}
        </div>
      )}
    </div>
  );
}

export function ApprovalBanners() {
  const { approvals } = useEngine();
  const pending = approvals.filter((a) => a.status === "pending").slice(0, 3);

  if (pending.length === 0) return null;

  return (
    <div className="banner-stack" role="alert">
      {pending.map((a) => (
        <Banner key={a.id} a={a} />
      ))}
    </div>
  );
}
