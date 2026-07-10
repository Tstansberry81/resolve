"use client";

import { useEffect, useRef } from "react";

// Full-screen background: blue stars drifting slowly, glimmering in varied
// patterns (three twinkle modes at different frequencies + occasional flare).
// Deterministic seed so the sky is the same on every load.

interface Star {
  x: number;
  y: number;
  r: number;
  vx: number;
  vy: number;
  phase: number;
  freq: number;
  mode: 0 | 1 | 2;
  color: string;
  flareAt: number;
}

function lcg(seed: number) {
  let s = seed >>> 0;
  return () => {
    s = (s * 1664525 + 1013904223) >>> 0;
    return s / 0xffffffff;
  };
}

const COLORS = ["#e8eefa", "#9fc8ff", "#3ee0ff", "#5a83ff"];

export function Starfield() {
  const ref = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = ref.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const dpr = Math.min(window.devicePixelRatio || 1, 2);
    let w = 0;
    let h = 0;
    let raf = 0;

    const rand = lcg(7);
    const stars: Star[] = Array.from({ length: 150 }, () => {
      const drift = 0.008 + rand() * 0.02;
      const ang = rand() * Math.PI * 2;
      return {
        x: rand(),
        y: rand(),
        r: 0.4 + rand() * 1.3,
        vx: Math.cos(ang) * drift,
        vy: Math.sin(ang) * drift,
        phase: rand() * Math.PI * 2,
        freq: 0.4 + rand() * 1.6,
        mode: Math.floor(rand() * 3) as 0 | 1 | 2,
        color: COLORS[Math.floor(rand() * COLORS.length)],
        flareAt: rand() * 20,
      };
    });

    const resize = () => {
      w = window.innerWidth;
      h = window.innerHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };
    resize();
    window.addEventListener("resize", resize);

    const draw = (ms: number) => {
      const t = ms / 1000;
      ctx.clearRect(0, 0, w, h);

      for (const s of stars) {
        // slow drift, wrapping at the edges
        const px = (((s.x + s.vx * t * 0.01) % 1) + 1) % 1;
        const py = (((s.y + s.vy * t * 0.01) % 1) + 1) % 1;

        // three glimmer patterns: smooth sine, double-beat, slow-breathe
        let tw: number;
        if (s.mode === 0) tw = 0.5 + 0.5 * Math.sin(t * s.freq + s.phase);
        else if (s.mode === 1)
          tw = 0.5 + 0.5 * Math.sin(t * s.freq + s.phase) * Math.sin(t * s.freq * 2.7);
        else tw = 0.6 + 0.4 * Math.sin(t * s.freq * 0.35 + s.phase);

        // occasional flare: a brief bright pulse every ~20s, staggered per star
        const flare = Math.max(0, 1 - Math.abs(((t + s.flareAt) % 21) - 0.35) * 6);
        const alpha = reduced ? 0.5 : Math.min(1, 0.18 + tw * 0.55 + flare * 0.8);

        ctx.globalAlpha = alpha;
        ctx.fillStyle = s.color;
        ctx.beginPath();
        ctx.arc(px * w, py * h, s.r + flare * 1.2, 0, Math.PI * 2);
        ctx.fill();

        if (flare > 0.25) {
          ctx.globalAlpha = flare * 0.35;
          ctx.beginPath();
          ctx.arc(px * w, py * h, (s.r + 2.5) * (1 + flare), 0, Math.PI * 2);
          ctx.fill();
        }
      }
      ctx.globalAlpha = 1;
      if (!reduced) raf = requestAnimationFrame(draw);
    };

    raf = requestAnimationFrame(draw);
    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", resize);
    };
  }, []);

  return <canvas ref={ref} className="starfield" aria-hidden />;
}
