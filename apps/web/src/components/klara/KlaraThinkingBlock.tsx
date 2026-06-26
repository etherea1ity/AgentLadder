import { ChevronRight } from "lucide-react";
import { useMemo } from "react";
import type { Run } from "../../types/domain";
import { KlaraPresence } from "./KlaraPresence";
import { formatThinkingDuration, thinkingDurationMs } from "./thinkingDuration";
import {
  visibleMainModelCommentaryItems,
  visibleThinkingItems,
} from "./thinkingItems";
import { isKlaraRunActive } from "./useKlaraRunMotion";

type Props = {
  run?: Run;
  isThinkingOpen?: boolean;
  onToggleThinking?: (runId: string, trigger: HTMLButtonElement) => void;
};

export function KlaraThinkingBlock({
  run,
  isThinkingOpen = false,
  onToggleThinking,
}: Props) {
  const active = isKlaraRunActive(run);

  const events = useMemo(
    () =>
      [...(run?.events ?? [])].sort((a, b) =>
        a.created_at.localeCompare(b.created_at),
      ),
    [run?.events],
  );
  const thinkingItems = useMemo(() => visibleThinkingItems(events), [events]);
  const mainThinkingItems = useMemo(
    () => visibleMainModelCommentaryItems(events),
    [events],
  );
  const latestMainThinking = mainThinkingItems[mainThinkingItems.length - 1];
  const hasThinkingDetails = thinkingItems.length > 0;
  const durationLabel = run
    ? formatThinkingDuration(thinkingDurationMs(run, events))
    : "";

  if (!run) return null;
  if (active && !latestMainThinking) {
    if (!active) return null;
    return (
      <section
        className="klara-thinking-block is-active is-pending"
        aria-label="Thinking"
      >
        <div className="klara-thinking-pending" aria-label="Klara is thinking">
          <ThinkingCursor />
          <span className="klara-thinking-pending-text">Thinking</span>
        </div>
      </section>
    );
  }
  if (!active && !hasThinkingDetails) return null;

  const label = active
    ? latestMainThinking?.body
    : durationLabel
      ? `Completed in ${durationLabel}`
      : "Completed";

  return (
    <section
      className={`klara-thinking-block ${active ? "is-active" : "is-completed"} ${isThinkingOpen ? "is-open" : ""}`}
      aria-label="Thinking"
    >
      <button
        type="button"
        className="klara-thinking-current"
        aria-label="Toggle thinking details"
        aria-haspopup="dialog"
        aria-expanded={isThinkingOpen}
        onClick={(event) => onToggleThinking?.(run.run_id, event.currentTarget)}
      >
        <span
          className={
            active
              ? "klara-thinking-text is-current"
              : "klara-thinking-summary"
          }
        >
          {label}
        </span>
        <span className="klara-thinking-toggle" aria-hidden="true">
          <ChevronRight size={16} />
        </span>
      </button>
      {active ? (
        <div
          className="klara-thinking-cursor-row"
          aria-label="Klara is still thinking"
        >
          <ThinkingCursor />
          <span className="klara-thinking-pending-text">Thinking</span>
        </div>
      ) : null}
    </section>
  );
}

function ThinkingCursor() {
  return (
    <span className="klara-thinking-cursor" aria-hidden="true">
      <KlaraPresence
        active
        phase="thinking"
        size="status"
        capabilities={["model"]}
        elevated
      />
      <span className="klara-thinking-cursor-dots">
        <span />
        <span />
        <span />
      </span>
    </span>
  );
}
