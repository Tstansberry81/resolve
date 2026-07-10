"use client";

import { useEffect, useRef } from "react";
import { engine, useEngine } from "@/lib/useEngine";
import type { NodeId } from "@/lib/types";

// Node layout: agents on an inner orbit, connectors on an outer orbit,
// the core at center. Edges only light up when the engine emits them.

const AGENTS: { id: NodeId; label: string }[] = [
  { id: "planner", label: "Planner" },
  { id: "researcher", label: "Researcher" },
  { id: "coder", label: "Coder" },
  { id: "reviewer", label: "Reviewer" },
  { id: "evaluator", label: "Evaluator" },
];

const CONNECTORS: { id: NodeId; label: string }[] = [
  { id: "gmail", label: "Gmail" },
  { id: "calendar", label: "Calendar" },
  { id: "notion", label: "Notion" },
  { id: "github", label: "GitHub" },
  { id: "canvas", label: "Canvas" },
  { id: "web", label: "Web" },
];

const ACCENT: Record<string, string> = {
  planner: "#5a83ff",
  researcher: "#a78bff",
  coder: "#3ee0ff",
  reviewer: "#ffb01f",
  evaluator: "#35e39c",
  core: "#3ee0ff",
};

export function Constellation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  // subscribe so React keeps this mounted fresh, but the RAF loop reads
  // straight from the engine to avoid re-render-per-frame
  useEngine();

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    let raf = 0;
    let w = 0;
    let h = 0;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

    const resize = () => {
      const rect = canvas.getBoundingClientRect();
      w = rect.width;
      h = rect.height;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    const positions = (t: number) => {
      const cx = w / 2;
      const cy = h / 2 + 6;
      const r1 = Math.min(w, h) * 0.24;
      const r2 = Math.min(w, h) * 0.42;
      const drift = reduced ? 0 : t * 0.00004;
      const pos = new Map<NodeId, { x: number; y: number }>();
      pos.set("core", { x: cx, y: cy });
      AGENTS.forEach((a, i) => {
        const ang = drift + (i / AGENTS.length) * Math.PI * 2 - Math.PI / 2;
        pos.set(a.id, { x: cx + Math.cos(ang) * r1, y: cy + Math.sin(ang) * r1 });
      });
      CONNECTORS.forEach((c, i) => {
        const ang = -drift * 0.7 + (i / CONNECTORS.length) * Math.PI * 2 - Math.PI / 3;
        pos.set(c.id, { x: cx + Math.cos(ang) * r2, y: cy + Math.sin(ang) * r2 });
      });
      return pos;
    };

    const draw = (t: number) => {
      const state = engine.getSnapshot();
      const active = new Set(state.activeNodes);
      const edge = state.activeEdge;
      const pos = positions(t);
      ctx.clearRect(0, 0, w, h);

      // faint structural edges: core→agents
      ctx.lineWidth = 1;
      for (const a of AGENTS) {
        const p1 = pos.get("core")!;
        const p2 = pos.get(a.id)!;
        ctx.strokeStyle = "rgba(148,163,184,0.07)";
        ctx.beginPath();
        ctx.moveTo(p1.x, p1.y);
        ctx.lineTo(p2.x, p2.y);
        ctx.stroke();
      }

      // hot edge with traveling pulse
      if (edge) {
        const p1 = pos.get(edge.from);
        const p2 = pos.get(edge.to);
        if (p1 && p2) {
          const grad = ctx.createLinearGradient(p1.x, p1.y, p2.x, p2.y);
          grad.addColorStop(0, "rgba(62,224,255,0.05)");
          grad.addColorStop(1, "rgba(62,224,255,0.65)");
          ctx.strokeStyle = grad;
          ctx.lineWidth = 1.4;
          ctx.beginPath();
          ctx.moveTo(p1.x, p1.y);
          ctx.lineTo(p2.x, p2.y);
          ctx.stroke();

          if (!reduced) {
            const k = (t % 1200) / 1200;
            const px = p1.x + (p2.x - p1.x) * k;
            const py = p1.y + (p2.y - p1.y) * k;
            ctx.fillStyle = "#3ee0ff";
            ctx.shadowColor = "#3ee0ff";
            ctx.shadowBlur = 10;
            ctx.beginPath();
            ctx.arc(px, py, 2.4, 0, Math.PI * 2);
            ctx.fill();
            ctx.shadowBlur = 0;
          }
        }
      }

      const drawNode = (
        id: NodeId,
        label: string,
        kind: "core" | "agent" | "connector",
      ) => {
        const p = pos.get(id)!;
        const isActive = kind === "core" ? active.size > 0 : active.has(id);
        const color = ACCENT[id] ?? "#97a5bd";
        const r = kind === "core" ? 9 : kind === "agent" ? 6.5 : 4.5;
        const pulse =
          isActive && !reduced ? 1 + Math.sin(t * 0.006) * 0.18 : 1;

        if (isActive) {
          ctx.shadowColor = color;
          ctx.shadowBlur = 16;
        }
        ctx.fillStyle = isActive ? color : "rgba(93,107,132,0.55)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * pulse, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;

        // orbit ring on active
        if (isActive) {
          ctx.strokeStyle = `${color}44`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r * pulse + 5, 0, Math.PI * 2);
          ctx.stroke();
        }

        ctx.fillStyle = isActive ? "#e8eefa" : "#5d6b84";
        ctx.font = `500 ${kind === "connector" ? 9.5 : 10.5}px var(--font-ui), sans-serif`;
        ctx.textAlign = "center";
        ctx.fillText(label, p.x, p.y + r + 14);
      };

      drawNode("core", "CORE", "core");
      AGENTS.forEach((a) => drawNode(a.id, a.label, "agent"));
      CONNECTORS.forEach((c) => drawNode(c.id, c.label, "connector"));

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  return (
    <div className="panel area-constellation constellation">
      <div className="panel-title">
        <span className="dot" />
        Agent constellation
      </div>
      <canvas ref={canvasRef} className="constellation-canvas" />
    </div>
  );
}
