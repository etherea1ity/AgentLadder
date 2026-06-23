import { X } from "lucide-react";
import { useMemo } from "react";
import type { Run, ThinkingActivityItem } from "../../types/domain";
import {
  visibleNarratorActivityItems,
  visibleProviderReasoningItems,
  visibleThinkingPreamble,
} from "./activityItems";

type Props = {
  run: Run;
  durationLabel: string;
  onClose: () => void;
};

export function KlaraActivityDrawer({ run, durationLabel, onClose }: Props) {
  const events = useMemo(
    () => [...run.events].sort((a, b) => a.created_at.localeCompare(b.created_at)),
    [run.events],
  );
  const providerItems = useMemo(() => visibleProviderReasoningItems(events), [events]);
  const narratorItems = useMemo(() => visibleNarratorActivityItems(events), [events]);
  const preamble = useMemo(() => visibleThinkingPreamble(events), [events]);

  return (
    <div className="klara-activity-layer">
      <aside
        className="klara-activity-drawer"
        role="dialog"
        aria-label="Activity"
      >
        <header className="klara-activity-header">
          <div>
            <h3>Activity</h3>
            <span>{durationLabel}</span>
          </div>
          <button type="button" aria-label="Close activity" onClick={onClose}>
            <X size={18} />
          </button>
        </header>

        {preamble ? (
          <section className="klara-activity-section">
            <h4>Klara preamble</h4>
            <p className="klara-activity-preamble">{preamble.text}</p>
          </section>
        ) : null}

        {providerItems.length ? (
          <section className="klara-activity-section">
            <h4>Model thinking</h4>
            <ActivityList items={providerItems} />
          </section>
        ) : null}

        {narratorItems.length ? (
          <section className="klara-activity-section">
            <h4>Klara activity</h4>
            <ActivityList items={narratorItems} />
          </section>
        ) : null}
      </aside>
    </div>
  );
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
