import type {
  RunEvent,
  ThinkingActivityItem,
  ThinkingActivityKind,
  ThinkingPreamble,
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

export function visibleNarratorActivityItems(events: RunEvent[]) {
  const deltas = events.filter(
    (event) => event.event_type === "thinking_summary_delta",
  );
  const latest = [...deltas]
    .reverse()
    .find((event) => {
      const items = event.payload?.items;
      return Array.isArray(items) && items.length > 0;
    });
  const items = latest?.payload?.items;
  if (!Array.isArray(items)) return [];
  return items
    .map(normalizeActivityItem)
    .filter(isActivityItem)
    .filter((item) => item.source === "narrator_model")
    .filter(isSafeNarratorItem);
}

export function visibleThinkingPreamble(events: RunEvent[]): ThinkingPreamble | null {
  const latest = [...events]
    .reverse()
    .find((event) => event.event_type === "thinking_preamble_delta");
  const text = stringField(latest?.payload?.text);
  if (!text || !isSafePreamble(text)) return null;
  const evidence = latest?.payload?.evidence_event_ids;
  return {
    text,
    evidence_event_ids: Array.isArray(evidence)
      ? evidence.filter((item): item is string => typeof item === "string")
      : [],
    confidence:
      typeof latest?.payload?.confidence === "number" &&
      Number.isFinite(latest.payload.confidence)
        ? latest.payload.confidence
        : undefined,
  };
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

function activitySource(value: unknown) {
  if (value === "provider_reasoning") return value;
  return "narrator_model";
}

function isSafeProviderItem(item: ThinkingActivityItem) {
  return (
    !containsFullUrl(item.title, item.body) &&
    !containsRawPayloadTerms(item.title, item.body)
  );
}

function isSafeNarratorItem(item: ThinkingActivityItem) {
  return (
    isSafeProviderItem(item) &&
    !containsPublicThinkingTerms(item.title, item.body) &&
    !containsBoilerplateActivityTerms(item.title, item.body)
  );
}

function isSafePreamble(text: string) {
  return (
    !containsFullUrl(text) &&
    !containsRawPayloadTerms(text) &&
    !containsPrivateReasoningTerms(text) &&
    !containsGenericPreambleTerms(text)
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

function containsPublicThinkingTerms(...parts: string[]) {
  const text = parts.join("\n").toLowerCase();
  return [
    "chain-of-thought",
    "chain of thought",
    "scratchpad",
    "hidden reasoning",
    "raw reasoning",
    "thinking process",
    "thought process",
    "private thinking",
    "\u601d\u8003",
    "\u63a8\u7406",
    "\u601d\u7ef4\u94fe",
  ].some((term) => text.includes(term));
}

function containsPrivateReasoningTerms(...parts: string[]) {
  const text = parts.join("\n").toLowerCase();
  return [
    "chain-of-thought",
    "chain of thought",
    "scratchpad",
    "hidden reasoning",
    "raw reasoning",
    "private thinking",
    "\u601d\u7ef4\u94fe",
    "\u63a8\u7406\u94fe",
  ].some((term) => text.includes(term));
}

function containsGenericPreambleTerms(...parts: string[]) {
  const text = parts.join("\n").toLowerCase();
  return [
    "i am thinking",
    "i'm thinking",
    "thinking about your request",
    "preparing an answer",
    "\u6211\u6b63\u5728\u601d\u8003",
    "\u6b63\u5728\u601d\u8003",
    "\u51c6\u5907\u56de\u7b54",
  ].some((term) => text.includes(term));
}

function containsBoilerplateActivityTerms(...parts: string[]) {
  const text = parts.join("\n").toLowerCase();
  return [
    "preparing the run",
    "reading the request",
    "writing the answer",
    "model response received",
    "set up the runtime",
    "setting up the runtime",
    "\u51c6\u5907\u8fd0\u884c",
    "\u51c6\u5907\u56de\u7b54",
    "\u6700\u7ec8\u56de\u7b54",
    "\u8bfb\u53d6\u8bf7\u6c42",
  ].some((term) => text.includes(term));
}
