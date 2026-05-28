import { useEffect, useMemo, useRef } from "react";
import type {
  CanvasRendererProxy,
  RiveCanvas as RiveRuntime,
} from "@rive-app/canvas-advanced";
import type { KlaraCapabilityChip, KlaraVisualPhase } from "../../types/domain";

type Props = {
  phase?: KlaraVisualPhase;
  active?: boolean;
  variant?: "hero" | "presence" | "handoff";
  elevated?: boolean;
  pulseKey?: number;
  capabilities?: KlaraCapabilityChip[];
};

type ParticleSeed = {
  x: number;
  y: number;
  delay: number;
  radius: number;
  drift: number;
  pathBias: number;
};

let riveRuntimePromise: Promise<RiveRuntime> | null = null;

function loadRiveRuntime() {
  riveRuntimePromise ??= Promise.all([
    import("@rive-app/canvas-advanced"),
    import("@rive-app/canvas-advanced/rive.wasm?url"),
  ]).then(([runtimeModule, wasmModule]) =>
    runtimeModule.default({ locateFile: () => wasmModule.default }),
  );
  return riveRuntimePromise;
}

function argb(r: number, g: number, b: number, alpha: number) {
  const a = Math.round(Math.max(0, Math.min(1, alpha)) * 255);
  return ((a << 24) | (r << 16) | (g << 8) | b) >>> 0;
}

function makeCirclePath(runtime: RiveRuntime, cx: number, cy: number, r: number) {
  const path = runtime.renderFactory.makeRenderPath();
  const k = 0.5522847498307936;
  path.moveTo(cx + r, cy);
  path.cubicTo(cx + r, cy + k * r, cx + k * r, cy + r, cx, cy + r);
  path.cubicTo(cx - k * r, cy + r, cx - r, cy + k * r, cx - r, cy);
  path.cubicTo(cx - r, cy - k * r, cx - k * r, cy - r, cx, cy - r);
  path.cubicTo(cx + k * r, cy - r, cx + r, cy - k * r, cx + r, cy);
  path.close();
  return path;
}

function makeArcPath(
  runtime: RiveRuntime,
  cx: number,
  cy: number,
  r: number,
  start: number,
  end: number,
  steps = 22,
) {
  const path = runtime.renderFactory.makeRenderPath();
  for (let i = 0; i <= steps; i += 1) {
    const t = start + ((end - start) * i) / steps;
    const x = cx + Math.cos(t) * r;
    const y = cy + Math.sin(t) * r;
    if (i === 0) path.moveTo(x, y);
    else path.lineTo(x, y);
  }
  return path;
}

function drawRadialHalo(
  runtime: RiveRuntime,
  renderer: CanvasRendererProxy,
  cx: number,
  cy: number,
  radius: number,
  alpha: number,
  warm: boolean,
) {
  const paint = runtime.renderFactory.makeRenderPaint();
  paint.style(runtime.RenderPaintStyle.fill);
  paint.radialGradient(cx, cy, cx + radius, cy);
  if (warm) {
    paint.addStop(argb(224, 183, 103, alpha), 0);
    paint.addStop(argb(184, 129, 47, alpha * 0.38), 0.38);
  } else {
    paint.addStop(argb(163, 91, 82, alpha), 0);
    paint.addStop(argb(163, 91, 82, alpha * 0.35), 0.42);
  }
  paint.addStop(argb(184, 129, 47, 0), 1);
  paint.completeGradient();
  renderer.drawPath(makeCirclePath(runtime, cx, cy, radius), paint);
}

function drawArc(
  runtime: RiveRuntime,
  renderer: CanvasRendererProxy,
  cx: number,
  cy: number,
  radius: number,
  start: number,
  length: number,
  alpha: number,
  thickness: number,
) {
  const paint = runtime.renderFactory.makeRenderPaint();
  paint.style(runtime.RenderPaintStyle.stroke);
  paint.cap(runtime.StrokeCap.round);
  paint.thickness(thickness);
  paint.color(argb(184, 129, 47, alpha));
  renderer.drawPath(makeArcPath(runtime, cx, cy, radius, start, start + length), paint);
}

function drawDot(
  runtime: RiveRuntime,
  renderer: CanvasRendererProxy,
  x: number,
  y: number,
  radius: number,
  alpha: number,
  color: [number, number, number] = [184, 129, 47],
) {
  const paint = runtime.renderFactory.makeRenderPaint();
  paint.style(runtime.RenderPaintStyle.fill);
  paint.color(argb(color[0], color[1], color[2], alpha));
  renderer.drawPath(makeCirclePath(runtime, x, y, radius), paint);
}

function phaseStrength(phase: KlaraVisualPhase, active: boolean, elevated: boolean, variant: Props["variant"]) {
  if (variant === "hero") {
    if (phase === "listening") return elevated || active ? 0.42 : 0.34;
    if (phase === "completed") return 0.36;
    if (phase === "error") return 0.34;
    return active || elevated ? 0.34 : 0.18;
  }
  if (phase === "error") return elevated ? 0.78 : 0.58;
  if (phase === "completed") return 0.74;
  if (phase === "writing") return elevated ? 0.9 : 0.78;
  if (phase === "thinking" || phase === "acting" || phase === "saving") {
    return elevated ? 0.9 : 0.78;
  }
  if (phase === "listening") return 0.66;
  if (active) return elevated ? 0.7 : 0.58;
  return 0.2;
}

function seedParticles(count: number, variant: Props["variant"]): ParticleSeed[] {
  return Array.from({ length: count }, (_, index) => {
    const column = index / Math.max(1, count - 1);
    return {
      x: variant === "hero" ? column * 0.82 + 0.09 : column * 0.92 + 0.04,
      y: variant === "hero" ? 0.86 + ((index % 3) * 0.055) : 0.76 + ((index % 4) * 0.06),
      delay: (index % 7) * 0.105,
      radius: 0.9 + (index % 3) * 0.34,
      drift: (index % 2 === 0 ? 1 : -1) * (0.07 + index * 0.006),
      pathBias: (index % 5) / 4,
    };
  });
}

function cycleAngle(seconds: number, offset = 0, reverse = false, periodSeconds = 12) {
  const fullTurn = (Math.PI * 2) / periodSeconds;
  return offset + seconds * fullTurn * (reverse ? -1 : 1);
}

function capColor(chip: KlaraCapabilityChip): [number, number, number] {
  if (chip === "rag" || chip === "memory") return [95, 123, 98];
  if (chip === "web") return [86, 112, 132];
  if (chip === "tool") return [165, 101, 63];
  if (chip === "verify") return [120, 122, 101];
  return [184, 129, 47];
}

function drawAmbientOrbitDots(
  runtime: RiveRuntime,
  renderer: CanvasRendererProxy,
  cx: number,
  cy: number,
  base: number,
  seconds: number,
  strength: number,
  variant: Props["variant"],
  reduceMotion: boolean,
) {
  const dots = variant === "hero"
    ? [
        { radius: 1.52, angle: 0.08, size: 0.02, alpha: 0.11 },
        { radius: 1.78, angle: 0.92, size: 0.012, alpha: 0.07 },
        { radius: 2.02, angle: 1.74, size: 0.014, alpha: 0.08 },
        { radius: 2.28, angle: 2.9, size: 0.014, alpha: 0.08 },
        { radius: 1.42, angle: 3.62, size: 0.01, alpha: 0.06 },
        { radius: 1.62, angle: 4.38, size: 0.012, alpha: 0.07 },
        { radius: 2.12, angle: 5.52, size: 0.013, alpha: 0.08 },
      ]
    : [
        { radius: 1.42, angle: 0.3, size: 0.028, alpha: 0.18 },
        { radius: 1.72, angle: 2.38, size: 0.018, alpha: 0.12 },
        { radius: 1.3, angle: 4.52, size: 0.014, alpha: 0.1 },
      ];
  dots.forEach((dot, index) => {
    const angle = reduceMotion ? dot.angle : cycleAngle(seconds, dot.angle + index * 0.18, index % 2 === 1);
    const x = cx + Math.cos(angle) * base * dot.radius;
    const y = cy + Math.sin(angle) * base * dot.radius;
    drawDot(runtime, renderer, x, y, Math.max(1.1, base * dot.size), dot.alpha + strength * (variant === "hero" ? 0.035 : 0.08));
  });
}

export function KlaraRiveField({
  phase = "idle",
  active = false,
  variant = "presence",
  elevated = false,
  pulseKey = 0,
  capabilities = [],
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const propsRef = useRef({ phase, active, variant, elevated, pulseKey, capabilities });
  const particleSeeds = useMemo(() => seedParticles(variant === "hero" ? 10 : 6, variant), [variant]);

  useEffect(() => {
    propsRef.current = { phase, active, variant, elevated, pulseKey, capabilities };
  }, [phase, active, variant, elevated, pulseKey, capabilities]);

  useEffect(() => {
    if (import.meta.env.MODE === "test") return;
    const canvas = canvasRef.current;
    if (!canvas) return;
    const context = canvas.getContext("2d");
    if (!context) return;

    let disposed = false;
    let runtime: RiveRuntime | null = null;
    let renderer: CanvasRendererProxy | null = null;
    let raf = 0;
    let lastPulseKey = pulseKey;
    let pulseStartedAt = 0;
    const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;

    const render = (time: number) => {
      if (disposed || !runtime || !renderer) return;
      const rect = canvas.getBoundingClientRect();
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      const nextWidth = Math.max(1, Math.round(rect.width * dpr));
      const nextHeight = Math.max(1, Math.round(rect.height * dpr));
      if (canvas.width !== nextWidth || canvas.height !== nextHeight) {
        canvas.width = nextWidth;
        canvas.height = nextHeight;
      }

      const p = propsRef.current;
      if (p.pulseKey !== lastPulseKey) {
        lastPulseKey = p.pulseKey;
        pulseStartedAt = time;
      }
      const seconds = time / 1000;
      const w = canvas.width;
      const h = canvas.height;
      // The homepage poster is not visually centered on its sun mark: the
      // KLARA wordmark sits lower, so a geometric center would put the optical
      // field too low. Keep presence/handoff centered, but anchor the hero
      // field around the poster's actual sun-K body.
      const cx = p.variant === "hero" ? w * 0.515 : w / 2;
      const cy = p.variant === "hero" ? h * 0.44 : h / 2;
      const base = Math.min(w, h) * (p.variant === "hero" ? 0.29 : 0.35);
      const strength = phaseStrength(p.phase, p.active, p.elevated, p.variant);
      const pulse = Math.max(0, 1 - (time - pulseStartedAt) / 860);
      const breathe = reduceMotion ? 0.52 : (Math.sin(seconds * 1.02) + 1) / 2;
      const activeRunGlow = p.phase === "thinking" || p.phase === "writing" || p.phase === "acting" || p.phase === "saving";
      const orbitPeriod = activeRunGlow ? 7.8 : 12;
      const orbitSeconds = activeRunGlow ? seconds * (12 / orbitPeriod) : seconds;
      const warm = p.phase !== "error";

      renderer.clear();
      if (p.variant === "hero") {
        drawRadialHalo(
          runtime,
          renderer,
          cx,
          cy,
          base * (1.66 + breathe * 0.12 + pulse * 0.08),
          strength * (0.12 + breathe * 0.05) + pulse * 0.08,
          warm,
        );
        drawRadialHalo(
          runtime,
          renderer,
          cx,
          cy,
          base * (2.22 + breathe * 0.16),
          0.025 + strength * 0.045 + pulse * 0.04,
          warm,
        );
      } else {
        drawRadialHalo(
          runtime,
          renderer,
          cx,
          cy,
          base * (1.42 + breathe * 0.16 + pulse * 0.12),
          strength * (0.3 + breathe * 0.14) + pulse * 0.18,
          warm,
        );
      }

      const drift = reduceMotion ? 0 : cycleAngle(seconds, 0, false, orbitPeriod);
      if (p.variant === "hero") {
        // The poster already contains the structural rings and stars. Keep the
        // live layer extremely light so motion reads as optical presence rather
        // than as a second diagram covering the illustration.
        drawArc(runtime, renderer, cx, cy, base * 1.74, drift + 0.35, Math.PI * 0.34, 0.035 + strength * 0.055, Math.max(0.6, base * 0.0045));
        drawArc(runtime, renderer, cx, cy, base * 2.1, cycleAngle(seconds, 4.3, false, orbitPeriod), Math.PI * 0.26, 0.02 + strength * 0.045, Math.max(0.5, base * 0.0036));
      } else {
        drawArc(runtime, renderer, cx, cy, base * 1.18, drift + 0.25, Math.PI * 0.52, 0.2 + strength * 0.2, Math.max(1, base * 0.014));
        drawArc(runtime, renderer, cx, cy, base * 1.56, cycleAngle(seconds, 2.9, true, orbitPeriod), Math.PI * 0.38, 0.12 + strength * 0.12, Math.max(0.8, base * 0.009));
      }
      if (activeRunGlow) {
        drawArc(runtime, renderer, cx, cy, base * 0.9, cycleAngle(seconds, 1.4, false, orbitPeriod), Math.PI * 1.58, 0.1 + strength * 0.12, Math.max(0.8, base * 0.008));
      }
      drawAmbientOrbitDots(runtime, renderer, cx, cy, base, orbitSeconds, strength, p.variant, reduceMotion);

      if (!reduceMotion && (p.active || p.phase === "listening" || pulse > 0.05 || p.variant === "hero")) {
        const maxParticles = activeRunGlow
          ? (p.variant === "hero" ? 11 : 8)
          : pulse > 0.05
            ? (p.variant === "hero" ? 10 : 7)
            : p.variant === "hero"
              ? 7
              : 4;
        particleSeeds.slice(0, maxParticles).forEach((seed, index) => {
          const local = pulse > 0.05
            ? Math.min(1, Math.max(0, (time - pulseStartedAt) / 900 - seed.delay * 0.7))
            : ((seconds * 0.18 + seed.delay) % 1 + 1) % 1;
          const eased = 1 - Math.pow(1 - local, 3);
          const sx = seed.x * w;
          const sy = seed.y * h;
          const tx = cx + Math.cos(index * 1.7) * base * 0.06;
          const ty = cy + Math.sin(index * 1.3) * base * 0.06;
          const curve = Math.sin(local * Math.PI) * base * seed.drift;
          const x = sx + (tx - sx) * eased + curve;
          const y = sy + (ty - sy) * eased - Math.sin(local * Math.PI) * base * (0.14 + seed.pathBias * 0.1);
          const alpha = ((p.variant === "hero" ? 0.14 : 0.1) + strength * (p.variant === "hero" ? 0.28 : 0.2) + pulse * 0.28) * Math.sin(local * Math.PI);
          drawDot(runtime!, renderer!, x, y, seed.radius * dpr, alpha);
        });
      }

      p.capabilities.slice(0, 2).forEach((chip, index) => {
        const angle = (reduceMotion ? index * 2.3 : cycleAngle(seconds, index * Math.PI * 1.15, index % 2 === 1, orbitPeriod));
        const radius = base * (1.05 + index * 0.3);
        drawDot(runtime!, renderer!, cx + Math.cos(angle) * radius, cy + Math.sin(angle) * radius, Math.max(2, base * 0.045), 0.44 + strength * 0.2, capColor(chip));
      });

      const allowPulseRing = p.phase !== "listening" && p.phase !== "idle";
      if (p.phase === "completed" || (allowPulseRing && pulse > 0.18)) {
        drawArc(runtime, renderer, cx, cy, base * (0.92 + pulse * 0.24), cycleAngle(seconds, 0.7), Math.PI * 2, 0.12 + pulse * 0.22, Math.max(1, base * 0.01));
      }

      if (!reduceMotion) raf = runtime.requestAnimationFrame(render);
    };

    loadRiveRuntime()
      .then((loadedRuntime) => {
        if (disposed) return;
        runtime = loadedRuntime;
        renderer = loadedRuntime.makeRenderer(canvas) as CanvasRendererProxy;
        raf = loadedRuntime.requestAnimationFrame(render);
      })
      .catch(() => {
        // Keep the Klara bitmap visible even if the Rive runtime cannot initialize.
      });

    return () => {
      disposed = true;
      if (runtime && raf) runtime.cancelAnimationFrame(raf);
      renderer?.delete();
    };
  }, [particleSeeds]);

  return <canvas className={`klara-rive-field klara-rive-${variant}`} ref={canvasRef} aria-hidden="true" />;
}
