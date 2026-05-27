import {
  useEffect,
  useRef,
  useState,
  type CSSProperties,
  type Dispatch,
  type SetStateAction,
} from "react";
import type { KlaraVisualPhase, Run } from "../../types/domain";
import { KlaraPresence } from "./KlaraPresence";

type HandoffStage = "collecting" | "charging" | "linking" | "settling";

type HandoffParticle = {
  id: string;
  x: number;
  y: number;
  dx: number;
  dy: number;
  delay: number;
  size: number;
};

export type KlaraHandoff = {
  runId: string;
  phase: KlaraVisualPhase;
  fromX: number;
  fromY: number;
  toX: number | null;
  toY: number | null;
  stage: HandoffStage;
  pulseKey: number;
  particles: HandoffParticle[];
  linkParticles: HandoffParticle[];
};

type HandoffSchedule = {
  timeout: number | null;
  arrivalTimeout: number | null;
  rafs: number[];
  active: boolean;
  targetRunId: string | null;
};

export function useKlaraHandoff(activeRun?: Run, triggerRunId?: string | null) {
  const [handoff, setHandoff] = useState<KlaraHandoff | null>(null);
  const [handoffTargetRunId, setHandoffTargetRunId] = useState<string | null>(null);
  const [arrivalRunId, setArrivalRunId] = useState<string | null>(null);
  const previousTriggerRef = useRef<string | null>(null);
  const previousActiveRunIdRef = useRef<string | null>(null);
  const scheduleRef = useRef<HandoffSchedule>({
    timeout: null,
    arrivalTimeout: null,
    rafs: [],
    active: false,
    targetRunId: null,
  });

  useEffect(() => () => clearSchedule(scheduleRef.current), []);

  useEffect(() => {
    const nextActiveRunId = activeRun?.run_id ?? null;
    const previousActiveRunId = previousActiveRunIdRef.current;

    if (
      nextActiveRunId &&
      previousActiveRunId &&
      nextActiveRunId !== previousActiveRunId &&
      scheduleRef.current.active
    ) {
      // Optimistic draft runs are replaced by real backend run ids. Keep the
      // same local-send handoff and retarget only the answer-side fade-in.
      scheduleRef.current.targetRunId = nextActiveRunId;
      setHandoffTargetRunId(nextActiveRunId);
    }

    previousActiveRunIdRef.current = nextActiveRunId;
  }, [activeRun?.run_id]);

  useEffect(() => {
    if (!triggerRunId) {
      if (previousTriggerRef.current) {
        previousTriggerRef.current = null;
        clearSchedule(scheduleRef.current);
        setHandoff(null);
        setHandoffTargetRunId(null);
        setArrivalRunId(null);
      }
      return;
    }
    if (triggerRunId === previousTriggerRef.current) return;
    previousTriggerRef.current = triggerRunId;
    if (scheduleRef.current.active) {
      scheduleRef.current.targetRunId = triggerRunId;
      setHandoffTargetRunId(triggerRunId);
      return;
    }
    startKlaraHandoff(
      triggerRunId,
      phaseForActiveRun(activeRun),
      setHandoff,
      setHandoffTargetRunId,
      setArrivalRunId,
      scheduleRef.current,
    );
  }, [triggerRunId]);

  const effectiveHandoffRunId = handoff ? handoffTargetRunId ?? handoff.runId : null;
  return { handoff, handoffRunId: effectiveHandoffRunId, arrivalRunId };
}

export function KlaraHandoffOverlay({ handoff }: { handoff: KlaraHandoff }) {
  return (
    <>
      {handoff.particles.length ? (
        <div className={`klara-collect-particles is-${handoff.stage}`} aria-hidden="true">
          {handoff.particles.map((particle) => (
            <span
              key={particle.id}
              style={
                {
                  "--particle-x": `${particle.x}px`,
                  "--particle-y": `${particle.y}px`,
                  "--particle-dx": `${particle.dx}px`,
                  "--particle-dy": `${particle.dy}px`,
                  "--particle-delay": `${particle.delay}ms`,
                  "--particle-size": `${particle.size}px`,
                } as CSSProperties
              }
            />
          ))}
        </div>
      ) : null}
      {handoff.linkParticles.length ? (
        <div className={`klara-link-particles is-${handoff.stage}`} aria-hidden="true">
          {handoff.linkParticles.map((particle) => (
            <span
              key={particle.id}
              style={
                {
                  "--particle-x": `${particle.x}px`,
                  "--particle-y": `${particle.y}px`,
                  "--particle-dx": `${particle.dx}px`,
                  "--particle-dy": `${particle.dy}px`,
                  "--particle-delay": `${particle.delay}ms`,
                  "--particle-size": `${particle.size}px`,
                } as CSSProperties
              }
            />
          ))}
        </div>
      ) : null}
      <div
        className={`klara-handoff-ghost is-${handoff.stage}`}
        style={
          {
            "--from-x": `${handoff.fromX}px`,
            "--from-y": `${handoff.fromY}px`,
          } as CSSProperties
        }
        aria-hidden="true"
      >
        <KlaraPresence
          active
          phase={handoff.phase}
          size="status"
          capabilities={[]}
          elevated
          pulseKey={handoff.pulseKey}
        />
      </div>
    </>
  );
}

function startKlaraHandoff(
  runId: string,
  phase: KlaraVisualPhase,
  setHandoff: Dispatch<SetStateAction<KlaraHandoff | null>>,
  setHandoffTargetRunId: Dispatch<SetStateAction<string | null>>,
  setArrivalRunId: Dispatch<SetStateAction<string | null>>,
  schedule: HandoffSchedule,
) {
  if (typeof window === "undefined") return;
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) return;

  clearSchedule(schedule);
  schedule.active = true;
  schedule.targetRunId = runId;
  setHandoffTargetRunId(runId);
  setArrivalRunId(null);

  const measureAfterLayout = () => {
    const composer = document.querySelector("[data-klara-composer-anchor]");
    if (!composer) return;

    const inputBox = document.querySelector("[data-klara-input-anchor]");
    const run = findRunPresenceAnchor(schedule.targetRunId ?? runId);
    const start = centerOf(composer);
    const target = run ? centerOf(run) : null;
    const sourceRect = inputBox ? inputBox.getBoundingClientRect() : null;
    const next: KlaraHandoff = {
      runId,
      phase,
      fromX: start.x,
      fromY: start.y,
      toX: target?.x ?? null,
      toY: target?.y ?? null,
      stage: "collecting",
      pulseKey: 1,
      particles: sourceRect ? makeCollectionParticles(sourceRect, start) : [],
      linkParticles: target ? makeLinkParticles(start, target) : [],
    };

    setHandoff(next);

    const collectMs = 520;
    const chargeMs = 760;
    const linkMs = 980;
    schedule.timeout = window.setTimeout(() => {
      setHandoff((current) =>
        current?.runId === runId
          ? { ...current, stage: "charging", pulseKey: current.pulseKey + 1 }
          : current,
      );
      schedule.timeout = window.setTimeout(() => {
        const arrivedRunId = schedule.targetRunId ?? runId;
        setArrivalRunId(arrivedRunId);
        setHandoff((current) => {
          if (current?.runId !== runId) return current;
          const latestTarget = findRunPresenceAnchor(arrivedRunId);
          if (!latestTarget) {
            return { ...current, stage: "linking", pulseKey: current.pulseKey + 1 };
          }
          const nextTarget = centerOf(latestTarget);
          return {
            ...current,
            stage: "linking",
            pulseKey: current.pulseKey + 1,
            toX: nextTarget.x,
            toY: nextTarget.y,
            linkParticles: makeLinkParticles({ x: current.fromX, y: current.fromY }, nextTarget),
          };
        });
        schedule.timeout = window.setTimeout(() => {
          schedule.active = false;
          schedule.targetRunId = null;
          setHandoffTargetRunId(null);
          if (schedule.arrivalTimeout != null) window.clearTimeout(schedule.arrivalTimeout);
          schedule.arrivalTimeout = window.setTimeout(() => {
            setArrivalRunId((current) => (current === arrivedRunId ? null : current));
            schedule.arrivalTimeout = null;
          }, 1800);
          setHandoff((current) =>
            current?.runId === runId
              ? { ...current, stage: "settling", pulseKey: current.pulseKey + 1 }
              : current,
          );
          schedule.timeout = window.setTimeout(() => setHandoff(null), 220);
        }, linkMs);
      }, chargeMs);
    }, collectMs);
  };

  // Wait two frames so optimistic messages render and the chat scroller can
  // settle. The answer-side anchor is used only for particle direction, never
  // for moving Klara itself, so scroll changes cannot drag the presence around.
  schedule.rafs.push(
    window.requestAnimationFrame(() => {
      schedule.rafs.push(window.requestAnimationFrame(measureAfterLayout));
    }),
  );
}

function clearSchedule(schedule: HandoffSchedule) {
  schedule.rafs.forEach((raf) => window.cancelAnimationFrame(raf));
  schedule.rafs = [];
  if (schedule.timeout != null) {
    window.clearTimeout(schedule.timeout);
    schedule.timeout = null;
  }
  if (schedule.arrivalTimeout != null) {
    window.clearTimeout(schedule.arrivalTimeout);
    schedule.arrivalTimeout = null;
  }
  schedule.active = false;
  schedule.targetRunId = null;
}

function makeCollectionParticles(rect: DOMRect, target: { x: number; y: number }): HandoffParticle[] {
  const seeds = [
    [0.12, 0.22],
    [0.34, 0.16],
    [0.62, 0.2],
    [0.86, 0.28],
    [0.2, 0.64],
    [0.48, 0.72],
    [0.74, 0.62],
    [0.92, 0.78],
  ] as const;
  return seeds.map(([xRatio, yRatio], index) => {
    const x = rect.left + rect.width * xRatio;
    const y = rect.top + rect.height * yRatio;
    return {
      id: `collect-${index}`,
      x,
      y,
      dx: target.x - x,
      dy: target.y - y,
      delay: index * 38,
      size: 3 + (index % 3),
    };
  });
}

function makeLinkParticles(from: { x: number; y: number }, to: { x: number; y: number }): HandoffParticle[] {
  return Array.from({ length: 14 }, (_, index) => {
    const t = (index + 1) / 15;
    const wave = Math.sin(t * Math.PI) * 18;
    const x = from.x + (to.x - from.x) * t;
    const y = from.y + (to.y - from.y) * t - wave;
    return {
      id: `link-${index}`,
      x,
      y,
      dx: (to.x - from.x) * 0.16,
      dy: (to.y - from.y) * 0.16 - wave * 0.12,
      delay: 80 + index * 44,
      size: index % 4 === 0 ? 4 : 2.6,
    };
  });
}

function findRunPresenceAnchor(runId: string | null) {
  if (!runId) return null;
  const escaped = escapeAttributeValue(runId);
  return (
    document.querySelector(`[data-klara-run-presence-anchor="${escaped}"]`) ??
    document.querySelector(`[data-klara-run-anchor="${escaped}"]`)
  );
}

function centerOf(element: Element) {
  const rect = element.getBoundingClientRect();
  return { x: rect.left + rect.width / 2, y: rect.top + rect.height / 2 };
}

function phaseForActiveRun(run?: Run): KlaraVisualPhase {
  if (run?.status === "streaming") return "writing";
  if (run?.status === "thinking") return "thinking";
  if (run?.status === "failed") return "error";
  if (run?.status === "cancelled") return "error";
  return "thinking";
}

function escapeAttributeValue(value: string) {
  if (typeof CSS !== "undefined" && typeof CSS.escape === "function") {
    return CSS.escape(value);
  }
  return value.replace(/["\\]/g, "\\$&");
}
