"use client";

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
          <p className="empty">Deliverables land here as goals complete.</p>
        )}
        {artifacts.map((a) => (
          <div key={a.id} className="artifact">
            <span className="artifact-glyph">{KIND_GLYPH[a.kind]}</span>
            <div className="artifact-body">
              <p className="artifact-name">{a.name}</p>
              <p className="artifact-meta">{a.meta}</p>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
