"use client";

import { useState } from "react";
import { useEngine } from "@/lib/useEngine";
import type { Artifact } from "@/lib/types";

const KIND_GLYPH: Record<Artifact["kind"], string> = {
  report: "▤",
  study_guide: "◈",
  pull_request: "⎇",
  draft: "✉",
  audio: "♪",
  file: "▣",
};

// window.resolveDesktop is set by the Electron shell, where file:// links can
// actually reveal the file in Finder. In a plain browser they can't, so we
// copy the path instead.
declare global {
  interface Window {
    resolveDesktop?: boolean;
  }
}

function ArtifactRow({ a }: { a: Artifact }) {
  const [copied, setCopied] = useState(false);
  const href = a.href;
  const isLocal = !!href && href.startsWith("file:");
  const diskPath = a.path || (href ? href.replace(/^file:\/\//, "") : "");

  const onClick = (e: React.MouseEvent) => {
    // In a browser, file:// links are blocked — copy the path so the user can
    // paste it into Finder (⌘⇧G). In the Electron app the link opens for real.
    if (isLocal && typeof window !== "undefined" && !window.resolveDesktop) {
      e.preventDefault();
      navigator.clipboard?.writeText(diskPath).then(() => {
        setCopied(true);
        setTimeout(() => setCopied(false), 1400);
      });
    }
  };

  return (
    <div className="artifact">
      <span className="artifact-glyph">{KIND_GLYPH[a.kind]}</span>
      <div className="artifact-body">
        {href ? (
          <a
            className="artifact-name artifact-link"
            href={href}
            target={isLocal ? undefined : "_blank"}
            rel="noreferrer"
            title={diskPath || href}
            onClick={onClick}
          >
            {a.name}
          </a>
        ) : (
          <p className="artifact-name">{a.name}</p>
        )}
        <p className="artifact-meta">{copied ? "path copied — ⌘⇧G in Finder" : a.meta}</p>
      </div>
    </div>
  );
}

export function ArtifactsDock() {
  const { artifacts } = useEngine();

  return (
    <div className="panel artifacts artifacts-corner">
      <div className="panel-title">
        <span className="dot" />
        Artifacts
        <span className="count">{artifacts.length}</span>
      </div>
      <div className="rail">
        {artifacts.length === 0 && (
          <p className="empty">Files RESOLVE creates or changes land here — click to open.</p>
        )}
        {artifacts.map((a) => (
          <ArtifactRow key={a.id} a={a} />
        ))}
      </div>
    </div>
  );
}
