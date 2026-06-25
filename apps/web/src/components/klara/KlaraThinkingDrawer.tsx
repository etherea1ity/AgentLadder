import { X } from "lucide-react";
import { useEffect, useMemo, useRef } from "react";
import type { Run, ThinkingActivityItem } from "../../types/domain";
import { formatThinkingDuration, thinkingDurationMs } from "./thinkingDuration";
import { visibleThinkingItems } from "./thinkingItems";

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
  const thoughtItems = useMemo(() => visibleThinkingItems(events), [events]);
  const hasVisibleContent = thoughtItems.length > 0;
  const durationLabel = run
    ? formatThinkingDuration(thinkingDurationMs(run, events))
    : "";

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
            {durationLabel ? <span>{durationLabel}</span> : null}
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

function ThoughtList({
  items,
}: {
  items: ThinkingActivityItem[];
}) {
  return (
    <ol className="klara-thought-list">
      {items.map((item, index) => {
        const isCurrent = index === items.length - 1;
        return (
          <li
            key={item.id}
            className={isCurrent ? "is-current" : undefined}
          >
            <p>{item.body}</p>
          </li>
        );
      })}
    </ol>
  );
}
