"use client";

import { useEffect, useRef } from "react";
import { engine, useEngine } from "@/lib/useEngine";
import { AGENTS, AGENT_META, CONNECTORS, HIERARCHY_EDGES } from "@/lib/roster";
import type { NodeId } from "@/lib/types";

// The real delegation tree, not decoration. Layout mirrors docs/DIRECTION.md:
// you (the orb above) → assistant → [luna · sol · executor · coder · reviewer]
// → connectors. Static edges show the hierarchy; they only light up when the
// engine emits an actual handoff, and pulses travel in the delegation
// direction. An input beam drops from the orb into the assistant while she's
// listening/working.

const AGENT_ROW: NodeId[] = ["luna", "sol", "executor", "coder", "reviewer"];

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

    const positions = () => {
      const pos = new Map<NodeId, { x: number; y: number }>();
      pos.set("assistant", { x: w / 2, y: h * 0.16 });
      const span = Math.min(w * 0.86, 760);
      const left = (w - span) / 2;
      AGENT_ROW.forEach((id, i) => {
        pos.set(id, { x: left + (span / (AGENT_ROW.length - 1)) * i, y: h * 0.52 });
      });
      const cspan = Math.min(w * 0.7, 600);
      const cleft = (w - cspan) / 2;
      CONNECTORS.forEach((c, i) => {
        pos.set(c.id, { x: cleft + (cspan / (CONNECTORS.length - 1)) * i, y: h * 0.86 });
      });
      return pos;
    };

    const curve = (
      p1: { x: number; y: number },
      p2: { x: number; y: number },
    ) => {
      ctx.beginPath();
      ctx.moveTo(p1.x, p1.y);
      const midY = (p1.y + p2.y) / 2;
      ctx.bezierCurveTo(p1.x, midY, p2.x, midY, p2.x, p2.y);
      ctx.stroke();
    };

    const pointOnCurve = (
      p1: { x: number; y: number },
      p2: { x: number; y: number },
      k: number,
    ) => {
      const midY = (p1.y + p2.y) / 2;
      const c1 = { x: p1.x, y: midY };
      const c2 = { x: p2.x, y: midY };
      const u = 1 - k;
      return {
        x: u * u * u * p1.x + 3 * u * u * k * c1.x + 3 * u * k * k * c2.x + k * k * k * p2.x,
        y: u * u * u * p1.y + 3 * u * u * k * c1.y + 3 * u * k * k * c2.y + k * k * k * p2.y,
      };
    };

    const draw = (t: number) => {
      const state = engine.getSnapshot();
      const active = new Set(state.activeNodes);
      const hot = state.activeEdge;
      const pos = positions();
      ctx.clearRect(0, 0, w, h);

      // input beam: the orb (above this canvas) feeding the assistant
      const a = pos.get("assistant")!;
      const beamOn = state.orb !== "idle" && !state.emergencyStopped;
      ctx.strokeStyle = beamOn ? "rgba(62,224,255,0.35)" : "rgba(148,163,184,0.08)";
      ctx.lineWidth = 1.2;
      ctx.beginPath();
      ctx.moveTo(a.x, 0);
      ctx.lineTo(a.x, a.y - 14);
      ctx.stroke();
      if (beamOn && !reduced) {
        const k = (t % 900) / 900;
        ctx.fillStyle = "#3ee0ff";
        ctx.shadowColor = "#3ee0ff";
        ctx.shadowBlur = 8;
        ctx.beginPath();
        ctx.arc(a.x, (a.y - 14) * k, 2, 0, Math.PI * 2);
        ctx.fill();
        ctx.shadowBlur = 0;
      }

      // static hierarchy edges (the real reporting lines)
      ctx.strokeStyle = "rgba(148,163,184,0.10)";
      ctx.lineWidth = 1;
      for (const [from, to] of HIERARCHY_EDGES) {
        const p1 = pos.get(from);
        const p2 = pos.get(to);
        if (p1 && p2) curve(p1, p2);
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
          curve(p1, p2);
          if (!reduced) {
            const k = (t % 1100) / 1100;
            const p = pointOnCurve(p1, p2, k);
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
        if (ag.id === "assistant") continue;
        drawNode(ag.id, ag.label, ag.model, "agent");
      }
      drawNode("assistant", "Assistant", AGENT_META.assistant.model, "assistant");
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
