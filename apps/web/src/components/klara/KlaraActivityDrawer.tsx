import { X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import type { Run, RunEvent, ThinkingActivityItem } from "../../types/domain";
import {
  visibleAgentTranscriptItems,
  visibleMainModelCommentaryItems,
  visibleProviderReasoningItems,
} from "./activityItems";

type Props = {
  run?: Run | null;
  open: boolean;
  onClose: () => void;
};

export function KlaraActivityDrawer({ run, open, onClose }: Props) {
  const closeButtonRef = useRef<HTMLButtonElement | null>(null);
  const events = useMemo(
    () =>
      [...(run?.events ?? [])].sort((a, b) =>
        a.created_at.localeCompare(b.created_at),
      ),
    [run?.events],
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
  const hasVisibleContent =
    providerItems.length > 0 ||
    commentaryItems.length > 0 ||
    transcriptItems.length > 0;
  const durationLabel = run ? activityDurationLabel(run, events) : "0s";

  useEffect(() => {
    if (!open) return;
    closeButtonRef.current?.focus();
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [onClose, open]);

  if (!open || !run || !hasVisibleContent) return null;

  return (
    <div
      className="klara-activity-layer"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className="klara-activity-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="klara-activity-title"
        aria-label="Activity"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="klara-activity-header">
          <div>
            <h3 id="klara-activity-title">Activity</h3>
            <span>{durationLabel}</span>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close activity"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>

        {commentaryItems.length > 0 ? <ThoughtList items={commentaryItems} /> : null}

        {transcriptItems.length > 0 ? (
          <details className="klara-activity-section klara-activity-provider">
            <summary>Actions</summary>
            <ActivityList items={transcriptItems} />
          </details>
        ) : null}

        {providerItems.length > 0 ? (
          <details className="klara-activity-section klara-activity-provider">
            <summary>Original model reasoning</summary>
            <ThoughtList items={providerItems} />
          </details>
        ) : null}
      </aside>
    </div>
  );
}

function activityDurationLabel(run: Run, events: RunEvent[]) {
  const completionEvent = [...events]
    .reverse()
    .find((event) => event.event_type === "thinking_summary_completed");
  const explicitDuration = numberFrom(completionEvent?.payload?.duration_ms);
  const ms =
    explicitDuration ??
    run.latency_ms ??
    run.live?.elapsed_ms ??
    durationFromEvents(events) ??
    0;
  return formatThoughtDuration(ms);
}

function durationFromEvents(events: RunEvent[]) {
  if (events.length < 2) return null;
  const start = Date.parse(events[0].created_at);
  const end = Date.parse(events[events.length - 1].created_at);
  if (Number.isNaN(start) || Number.isNaN(end)) return null;
  return Math.max(0, end - start);
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

function ActivityList({ items }: { items: ThinkingActivityItem[] }) {
  return (
    <ol className="klara-activity-list">
      {items.map((item) => (
        <li className={`is-${item.status}`} key={item.id}>
          <span aria-hidden="true" />
          <article>
            <h5>{item.title}</h5>
            <p>{item.body}</p>
          </article>
        </li>
      ))}
    </ol>
  );
}

function ThoughtList({ items }: { items: ThinkingActivityItem[] }) {
  return (
    <div className="klara-thought-list">
      {items.map((item) => (
        <p key={item.id}>{item.body}</p>
      ))}
    </div>
  );
}
