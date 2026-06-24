import type {
  RunEvent,
  ThinkingActivityItem,
  ThinkingActivityKind,
  ThinkingActivitySource,
  ThinkingActivityStatus,
} from "../../types/domain";

export function visibleProviderReasoningItems(events: RunEvent[]) {
  return events
    .filter((event) => event.event_type === "provider_reasoning_delta")
    .flatMap((event) => {
      const items = event.payload?.items;
      return Array.isArray(items)
        ? items.map(normalizeActivityItem).filter(isActivityItem)
        : [];
    })
    .filter((item) => item.source === "provider_reasoning")
    .filter(isSafeProviderItem);
}

function normalizeActivityItem(value: unknown): ThinkingActivityItem | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const evidence = record.evidence_event_ids;
  const evidenceFacts = record.evidence_fact_ids;
  return {
    id: stringField(record.id),
    title: stringField(record.title),
    body: stringField(record.body),
    status: activityStatus(record.status),
    kind: activityKind(record.kind),
    source: activitySource(record.source),
    evidence_fact_ids: Array.isArray(evidenceFacts)
      ? evidenceFacts.filter((item): item is string => typeof item === "string")
      : undefined,
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
    value === "finalization" ||
    value === "error"
  )
    return value;
  return "orientation";
}

function activitySource(value: unknown): ThinkingActivitySource {
  return value === "provider_reasoning" ? value : "provider_reasoning";
}

function isSafeProviderItem(item: ThinkingActivityItem) {
  return (
    !containsFullUrl(item.title, item.body) &&
    !containsRawPayloadTerms(item.title, item.body)
  );
}

function containsFullUrl(...parts: string[]) {
  const text = parts.join("\n").toLowerCase();
  return text.includes("http://") || text.includes("https://");
}

function containsRawPayloadTerms(...parts: string[]) {
  const text = parts.join("\n").toLowerCase();
  return [
    "query",
    "argument",
    "arguments",
    "raw args",
    "raw payload",
    "\u53c2\u6570",
    "\u67e5\u8be2\u8bcd",
    "\u641c\u7d22\u8bcd",
  ].some((term) => text.includes(term));
}
