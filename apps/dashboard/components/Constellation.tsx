"use client";

import { useEffect, useRef } from "react";
import { engine, useEngine } from "@/lib/useEngine";
import { AGENTS, AGENT_META, CONNECTORS, HIERARCHY_EDGES } from "@/lib/roster";
import type { NodeId } from "@/lib/types";

// The real delegation tree, not decoration. Layout mirrors docs/DIRECTION.md:
// you (the orb above) → assistant → [planner · executor · coder · reviewer]
// → connectors. Static edges show the hierarchy; they only light up when the
// engine emits an actual handoff, and pulses travel in the delegation
// direction. An input beam drops from the orb into the assistant while she's
// listening/working.

const AGENT_ROW: NodeId[] = ["planner", "executor", "coder", "reviewer"];

export function Constellation() {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  useEngine(); // keep mounted; RAF reads engine directly

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
      if (Math.abs(rect.width - w) < 1 && Math.abs(rect.height - h) < 1) return;
      w = rect.width;
      h = rect.height;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    const ro = new ResizeObserver(resize);
    ro.observe(canvas);

    // Radial: the assistant sits at the center; agents orbit her on an inner
    // ring, connectors on an outer ring — everything slowly revolving.
    const positions = (t: number) => {
      const pos = new Map<NodeId, { x: number; y: number }>();
      const cx = w / 2;
      const cy = h / 2;
      pos.set("assistant", { x: cx, y: cy });
      const rot = reduced ? 0 : t * 0.00004;
      const base = Math.min(w, h);
      const r1 = base * 0.28;
      AGENT_ROW.forEach((id, i) => {
        const ang = rot - Math.PI / 2 + (i / AGENT_ROW.length) * Math.PI * 2;
        pos.set(id, { x: cx + Math.cos(ang) * r1, y: cy + Math.sin(ang) * r1 });
      });
      const r2 = base * 0.45;
      CONNECTORS.forEach((c, i) => {
        // counter-rotate the outer ring a touch for depth
        const ang = -rot * 0.55 - Math.PI / 2 + (i / CONNECTORS.length) * Math.PI * 2;
        pos.set(c.id, { x: cx + Math.cos(ang) * r2, y: cy + Math.sin(ang) * r2 });
      });
      return pos;
    };

    const line = (
      p1: { x: number; y: number },
      p2: { x: number; y: number },
    ) => {
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.stroke();
    };

    const pointOnLine = (
      p1: { x: number; y: number },
      p2: { x: number; y: number },
      k: number,
    ) => ({ x: p1.x + (p2.x - p1.x) * k, y: p1.y + (p2.y - p1.y) * k });

    const draw = (t: number) => {
      const state = engine.getSnapshot();
      const active = new Set(state.activeNodes);
      const hot = state.activeEdge;
      const pos = positions(t);
      ctx.clearRect(0, 0, w, h);

      // center glow: the assistant pulses when the orb is live
      const a = pos.get("assistant")!;
      const beamOn = state.orb !== "idle" && !state.emergencyStopped;
      if (beamOn && !reduced) {
        const k = 0.5 + 0.5 * Math.sin(t * 0.004);
        ctx.strokeStyle = `rgba(62,224,255,${0.06 + k * 0.12})`;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.arc(a.x, a.y, Math.min(w, h) * 0.28, 0, Math.PI * 2);
        ctx.stroke();
      }

      // static hierarchy edges (the real reporting lines) — now radial spokes
      ctx.strokeStyle = "rgba(148,163,184,0.10)";
      ctx.lineWidth = 1;
      for (const [from, to] of HIERARCHY_EDGES) {
        const p1 = pos.get(from);
        const p2 = pos.get(to);
        if (p1 && p2) line(p1, p2);
      }

      // hot edge: an actual handoff in flight (any pair, incl. connectors)
      if (hot) {
        const p1 = pos.get(hot.from);
        const p2 = pos.get(hot.to);
        if (p1 && p2) {
          const grad = ctx.createLinearGradient(p1.x, p1.y, p2.x, p2.y);
          grad.addColorStop(0, "rgba(62,224,255,0.10)");
          grad.addColorStop(1, "rgba(62,224,255,0.70)");
          ctx.strokeStyle = grad;
          ctx.lineWidth = 1.6;
          line(p1, p2);
          if (!reduced) {
            const k = (t % 1100) / 1100;
            const p = pointOnLine(p1, p2, k);
            ctx.fillStyle = "#3ee0ff";
            ctx.shadowColor = "#3ee0ff";
            ctx.shadowBlur = 10;
            ctx.beginPath();
            ctx.arc(p.x, p.y, 2.6, 0, Math.PI * 2);
            ctx.fill();
            ctx.shadowBlur = 0;
          }
        }
      }

      const drawNode = (
        id: NodeId,
        label: string,
        sub: string | null,
        kind: "assistant" | "agent" | "connector",
      ) => {
        const p = pos.get(id)!;
        const isActive = active.has(id);
        const color = AGENT_META[id]?.color ?? "#97a5bd";
        const r = kind === "assistant" ? 10 : kind === "agent" ? 7 : 4.5;
        const pulse = isActive && !reduced ? 1 + Math.sin(t * 0.006) * 0.16 : 1;

        if (isActive) {
          ctx.shadowColor = color;
          ctx.shadowBlur = 18;
        }
        ctx.fillStyle = isActive ? color : "rgba(93,107,132,0.55)";
        ctx.beginPath();
        ctx.arc(p.x, p.y, r * pulse, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;

        if (isActive) {
          ctx.strokeStyle = `${color}44`;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.arc(p.x, p.y, r * pulse + 5, 0, Math.PI * 2);
          ctx.stroke();
        }

        ctx.textAlign = "center";
        ctx.fillStyle = isActive ? "#e8eefa" : "#5d6b84";
        ctx.font = `600 ${kind === "connector" ? 9.5 : 11}px var(--font-ui), sans-serif`;
        ctx.fillText(label, p.x, p.y + r + 15);
        if (sub) {
          ctx.fillStyle = isActive ? "#97a5bd" : "#3f4b61";
          ctx.font = "500 8.5px var(--font-mono), monospace";
          ctx.fillText(sub, p.x, p.y + r + 27);
        }
      };

      for (const ag of AGENTS) {
        if (ag.id === "assistant") continue; // the orb IS the assistant, at the center
        drawNode(ag.id, ag.label, ag.model, "agent");
      }
      CONNECTORS.forEach((c) => drawNode(c.id, c.label, null, "connector"));

      raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
    };
  }, []);

  return (
    <div className="constellation-v2">
      <canvas ref={canvasRef} className="constellation-canvas" />
    </div>
  );
}
