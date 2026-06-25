import { ChevronRight } from "lucide-react";
import { useMemo } from "react";
import type { Run } from "../../types/domain";
import { KlaraPresence } from "./KlaraPresence";
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

  if (!run) return null;
  if (!latestThinking) return null;

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
        <span className={active ? "is-current" : undefined}>
          {latestThinking.body}
        </span>
        <span className="klara-thinking-toggle" aria-hidden="true">
          <ChevronRight size={16} />
        </span>
      </button>
      {active ? (
        <div className="klara-thinking-cursor" aria-hidden="true">
          <span className="klara-thinking-cursor-mark">
            <KlaraPresence
              active
              phase="thinking"
              size="status"
              capabilities={["model"]}
              elevated
              pulseKey={events.length}
            />
          </span>
          <span className="klara-thinking-cursor-dots">
            <span />
            <span />
            <span />
          </span>
        </div>
      ) : null}
    </section>
  );
}
