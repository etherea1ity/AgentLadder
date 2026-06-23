import { X } from "lucide-react";
import { useMemo } from "react";
import type {
  Run,
  RunEvent,
  ThinkingActivityItem,
  ThinkingActivityKind,
  ThinkingActivitySource,
  ThinkingActivityStatus,
} from "../../types/domain";

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
  const narratorItems = useMemo(() => latestNarratorItems(events), [events]);
  const runtimeItems = useMemo(() => runtimeActivityItems(events), [events]);

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

        <section className="klara-activity-section">
          <h4>Klara thinking</h4>
          {narratorItems.length ? (
            <ActivityList items={narratorItems} />
          ) : (
            <p className="klara-activity-empty">
              No public thinking summary was generated for this run.
            </p>
          )}
        </section>

        <section className="klara-activity-section">
          <h4>Agent activity</h4>
          {runtimeItems.length ? (
            <ActivityList items={runtimeItems} />
          ) : (
            <p className="klara-activity-empty">
              No runtime activity items were emitted for this run.
            </p>
          )}
        </section>
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

function latestNarratorItems(events: RunEvent[]) {
  const deltas = events.filter(
    (event) => event.event_type === "thinking_summary_delta",
  );
  const latest = deltas[deltas.length - 1];
  const items = latest?.payload?.items;
  if (!Array.isArray(items)) return [];
  return items.map(normalizeActivityItem).filter(isActivityItem);
}

function runtimeActivityItems(events: RunEvent[]) {
  return events
    .filter((event) => event.event_type === "activity_item_upserted")
    .map((event) => normalizeActivityItem(event.payload?.item))
    .filter(isActivityItem);
}

function normalizeActivityItem(value: unknown): ThinkingActivityItem | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const evidence = record.evidence_event_ids;
  return {
    id: stringField(record.id),
    title: stringField(record.title),
    body: stringField(record.body),
    status: activityStatus(record.status),
    kind: activityKind(record.kind),
    source: activitySource(record.source),
    evidence_event_ids: Array.isArray(evidence)
      ? evidence.filter((item): item is string => typeof item === "string")
      : [],
    confidence:
      typeof record.confidence === "number" && Number.isFinite(record.confidence)
        ? record.confidence
        : undefined,
  };
}

function isActivityItem(
  item: ThinkingActivityItem | null,
): item is ThinkingActivityItem {
  return Boolean(item?.id && item.title && item.body);
}

function stringField(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function activityStatus(value: unknown): ThinkingActivityStatus {
  return value === "running" || value === "failed" ? value : "completed";
}

function activityKind(value: unknown): ThinkingActivityKind {
  if (
    value === "orientation" ||
    value === "evidence" ||
    value === "tool_activity" ||
    value === "composition" ||
    value === "finalization"
  )
    return value;
  return "orientation";
}

function activitySource(value: unknown): ThinkingActivitySource {
  if (
    value === "runtime_event" ||
    value === "provider_reasoning" ||
    value === "fallback"
  )
    return value;
  return "narrator_model";
}

