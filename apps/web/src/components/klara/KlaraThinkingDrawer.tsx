import { X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import type { Run, RunEvent, ThinkingActivityItem } from "../../types/domain";
import {
  visibleMainModelCommentaryItems,
  visibleProviderReasoningItems,
} from "./thinkingItems";

type Props = {
  run?: Run | null;
  open: boolean;
  onClose: () => void;
};

export function KlaraThinkingDrawer({ run, open, onClose }: Props) {
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
  const thoughtItems = useMemo(
    () => [...commentaryItems, ...providerItems],
    [commentaryItems, providerItems],
  );
  const hasVisibleContent = thoughtItems.length > 0;
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
      className="klara-thinking-drawer-layer"
      role="presentation"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget) onClose();
      }}
    >
      <aside
        className="klara-thinking-drawer"
        role="dialog"
        aria-modal="true"
        aria-labelledby="klara-thinking-drawer-title"
        aria-label="Thinking"
        onMouseDown={(event) => event.stopPropagation()}
      >
        <header className="klara-thinking-drawer-header">
          <div>
            <h3 id="klara-thinking-drawer-title">Thinking</h3>
            <span>{durationLabel}</span>
          </div>
          <button
            ref={closeButtonRef}
            type="button"
            aria-label="Close thinking"
            onClick={onClose}
          >
            <X size={18} />
          </button>
        </header>

        <ThoughtList items={thoughtItems} />
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

function ThoughtList({ items }: { items: ThinkingActivityItem[] }) {
  return (
    <ol className="klara-thought-list">
      {items.map((item) => (
        <li key={item.id}>
          <p>{item.body}</p>
        </li>
      ))}
    </ol>
  );
}
