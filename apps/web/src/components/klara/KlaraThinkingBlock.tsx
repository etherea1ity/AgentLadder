import { ChevronRight } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import type { Run, RunEvent } from "../../types/domain";
import { KlaraPresence } from "./KlaraPresence";
import {
  visibleAgentTranscriptItems,
  visibleMainModelCommentaryItems,
  visibleProviderReasoningItems,
} from "./activityItems";
import { isKlaraRunActive } from "./useKlaraRunMotion";

type Props = {
  run?: Run;
  isActivityOpen?: boolean;
  onOpenActivity?: (runId: string, trigger: HTMLButtonElement) => void;
};

export function KlaraThinkingBlock({
  run,
  isActivityOpen = false,
  onOpenActivity,
}: Props) {
  const active = isKlaraRunActive(run);
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!active) return;
    const timer = window.setInterval(() => setNow(Date.now()), 500);
    return () => window.clearInterval(timer);
  }, [active]);

  const events = useMemo(
    () =>
      [...(run?.events ?? [])].sort((a, b) =>
        a.created_at.localeCompare(b.created_at),
      ),
    [run?.events],
  );
  const completionEvent = useMemo(
    () =>
      [...events]
        .reverse()
        .find((event) => event.event_type === "thinking_summary_completed"),
    [events],
  );
  const providerItems = useMemo(() => visibleProviderReasoningItems(events), [events]);
  const commentaryItems = useMemo(
    () => visibleMainModelCommentaryItems(events),
    [events],
  );
  const transcriptItems = useMemo(
    () => visibleAgentTranscriptItems(events),
    [events],
  );
  const latestCommentary =
    commentaryItems.length > 0
      ? commentaryItems[commentaryItems.length - 1]?.body ?? ""
      : "";

  if (!run) return null;
  const hasVisibleActivity =
    providerItems.length > 0 ||
    commentaryItems.length > 0 ||
    transcriptItems.length > 0;
  if (!active && !hasVisibleActivity) return null;

  const durationMs = thinkingDurationMs(
    run,
    events,
    completionEvent,
    active,
    now,
  );
  const durationLabel = formatThoughtDuration(durationMs);
  const label = active
    ? `Thinking... ${durationLabel}`
    : `Thought for ${durationLabel}`;

  return (
    <section
      className={`klara-thinking-block ${active ? "is-active" : "is-completed"}`}
      aria-label="Thinking"
    >
      <div className="klara-thinking-row">
        <span
          className={`klara-thinking-mini ${active ? "is-active" : "is-completed"}`}
          aria-label="Mini Klara"
          role="img"
        >
          <KlaraPresence
            active={active}
            phase={active ? "thinking" : "completed"}
            size="status"
            capabilities={active ? ["model"] : []}
            elevated={active}
            pulseKey={events.length}
          />
        </span>
        <span className="klara-thinking-title">{label}</span>
        {hasVisibleActivity ? (
          <button
            type="button"
            className="klara-thinking-toggle"
            aria-label="Open activity"
            aria-haspopup="dialog"
            aria-expanded={isActivityOpen}
            onClick={(event) => onOpenActivity?.(run.run_id, event.currentTarget)}
          >
            <ChevronRight size={16} aria-hidden="true" />
          </button>
        ) : null}
      </div>
      {active && latestCommentary ? (
        <p className="klara-thinking-activity">{latestCommentary}</p>
      ) : null}
    </section>
  );
}

function thinkingDurationMs(
  run: Run,
  events: RunEvent[],
  completionEvent: RunEvent | undefined,
  active: boolean,
  now: number,
) {
  const explicitDuration = numberFrom(completionEvent?.payload?.duration_ms);
  if (explicitDuration != null) return explicitDuration;
  if (run.latency_ms != null) return run.latency_ms;
  if (run.live?.elapsed_ms != null) return run.live.elapsed_ms;
  const startEvent =
    events.find((event) => event.event_type === "thinking_summary_started") ??
    events[0];
  if (active && startEvent) {
    const startedAt = Date.parse(startEvent.created_at);
    if (!Number.isNaN(startedAt)) return Math.max(0, now - startedAt);
  }
  return 0;
}

function numberFrom(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function formatThoughtDuration(ms: number) {
  if (!Number.isFinite(ms) || ms <= 0) return "0s";
  if (ms < 1000) return `${Math.round(ms)}ms`;
  if (ms < 60000) return `${(ms / 1000).toFixed(1).replace(/\.0$/, "")}s`;
  const minutes = Math.floor(ms / 60000);
  const seconds = Math.round((ms % 60000) / 1000);
  return `${minutes}m ${seconds}s`;
}
