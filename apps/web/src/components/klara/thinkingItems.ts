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
    .filter(isSafeActivityItem);
}

export function visibleThinkingItems(events: RunEvent[]) {
  return events
    .flatMap((event) => {
      if (event.event_type === "assistant_activity_delta") {
        const text = safeText(event.payload?.text);
        if (!text) return [];
        const phase = activityPhase(event.payload?.phase);
        return [
          {
            id: `activity_${event.event_id}`,
            title: "thinking",
            body: text,
            status: "completed",
            kind: phaseToKind(phase),
            source: "main_model_commentary",
            evidence_event_ids: evidenceIds(event),
            confidence: 1,
          } satisfies ThinkingActivityItem,
        ];
      }
      if (event.event_type === "provider_reasoning_delta") {
        const items = event.payload?.items;
        return Array.isArray(items)
          ? items.map(normalizeActivityItem).filter(isActivityItem)
          : [];
      }
      return [];
    })
    .filter(
      (item) =>
        item.source === "main_model_commentary" ||
        item.source === "provider_reasoning",
    )
    .filter(isSafeActivityItem);
}

export function visibleMainModelCommentaryItems(events: RunEvent[]) {
  return events
    .filter((event) => event.event_type === "assistant_activity_delta")
    .map((event) => {
      const text = safeText(event.payload?.text);
      if (!text) return null;
      const phase = activityPhase(event.payload?.phase);
      const item: ThinkingActivityItem = {
        id: `activity_${event.event_id}`,
        title: "activity",
        body: text,
        status: "completed",
        kind: phaseToKind(phase),
        source: "main_model_commentary",
        evidence_event_ids: evidenceIds(event),
        confidence: 1,
      };
      return item;
    })
    .filter(isActivityItem)
    .filter(isSafeActivityItem);
}

function normalizeActivityItem(value: unknown): ThinkingActivityItem | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const evidence = record.evidence_event_ids;
  const evidenceFacts = record.evidence_fact_ids;
  return {
    id: stringField(record.id),
    title: safeText(record.title),
    body: safeText(record.body),
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

function evidenceIds(event: RunEvent) {
  const ids = event.payload?.evidence_event_ids;
  return Array.isArray(ids)
    ? ids.filter((item): item is string => typeof item === "string")
    : [event.event_id];
}

function stringField(value: unknown) {
  return typeof value === "string" ? value.trim() : "";
}

function safeText(value: unknown) {
  const text = stripInternalActivityLabels(
    stringField(value).replace(/\s+/g, " "),
  );
  if (!text || containsFullUrl(text) || containsRawPayloadTerms(text)) return "";
  return text;
}

function stripInternalActivityLabels(text: string) {
  return text
    .replace(
      /\b(?:update_activity(?:\.text)?|activity_commentary|public_activity|assistant_activity(?:_delta)?)\s*[:\uFF1A]\s*/gi,
      "",
    )
    .trim();
}

function activityStatus(value: unknown): ThinkingActivityStatus {
  return value === "running" || value === "started"
    ? "running"
    : value === "failed"
      ? "failed"
      : "completed";
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
  return value === "provider_reasoning"
    ? "provider_reasoning"
    : value === "main_model_commentary"
      ? "main_model_commentary"
      : value === "runtime_action"
        ? "runtime_action"
        : "provider_reasoning";
}

function activityPhase(value: unknown) {
  if (value === "between_tools" || value === "finalizing") return value;
  return "before_tool";
}

function phaseToKind(phase: string): ThinkingActivityKind {
  return phase === "finalizing" ? "finalization" : "orientation";
}

function isSafeActivityItem(item: ThinkingActivityItem) {
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
