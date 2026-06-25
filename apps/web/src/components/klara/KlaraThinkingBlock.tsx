import { ChevronRight } from "lucide-react";
import { useMemo } from "react";
import type { Run } from "../../types/domain";
import { formatThinkingDuration, thinkingDurationMs } from "./thinkingDuration";
import { visibleThinkingItems } from "./thinkingItems";
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
  const thinkingItems = useMemo(
    () => visibleThinkingItems(events),
    [events],
  );
  const latestThinking = thinkingItems[thinkingItems.length - 1];
  const durationLabel = run
    ? formatThinkingDuration(thinkingDurationMs(run, events))
    : "";

  if (!run) return null;
  if (!latestThinking) return null;

  const label = active
    ? latestThinking.body
    : durationLabel
      ? `Thought for ${durationLabel}`
      : "Thought";

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
    </section>
  );
}
