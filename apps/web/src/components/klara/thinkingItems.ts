import type {
  RunEvent,
  ThinkingActivityItem,
  ThinkingActivityKind,
  ThinkingActivitySource,
  ThinkingActivityStatus,
} from "../../types/domain";

export function visibleProviderReasoningItems(events: RunEvent[]) {
  const items = events
    .filter((event) => event.event_type === "provider_reasoning_delta")
    .flatMap((event) => {
      const items = event.payload?.items;
      return Array.isArray(items)
        ? items.map(normalizeActivityItem).filter(isActivityItem)
        : [];
    })
    .filter((item) => item.source === "provider_reasoning")
    .filter(isSafeActivityItem);

  return dedupeSimilarItems(items);
}

export function visibleMainModelCommentaryItems(events: RunEvent[]) {
  const items = events
    .filter((event) => event.event_type === "assistant_activity_delta")
    .map((event) => {
      const text = safeText(event.payload?.text, 500);
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

  return dedupeSimilarItems(items);
}

function normalizeActivityItem(value: unknown): ThinkingActivityItem | null {
  if (!value || typeof value !== "object") return null;
  const record = value as Record<string, unknown>;
  const evidence = record.evidence_event_ids;
  const evidenceFacts = record.evidence_fact_ids;
  return {
    id: stringField(record.id),
    title: safeText(record.title, 120),
    body: safeText(record.body, 900),
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

function safeText(value: unknown, maxChars: number) {
  const text = stripInternalActivityLabels(
    stringField(value).replace(/\s+/g, " "),
  );
  if (!text || containsFullUrl(text) || containsRawPayloadTerms(text)) return "";
  return text.slice(0, maxChars);
}

function stripInternalActivityLabels(text: string) {
  return text
    .replace(
      /\b(?:update_activity(?:\.text)?|activity_commentary|public_activity|assistant_activity(?:_delta)?)\s*[:\uFF1A]\s*/gi,
      "",
    )
    .trim();
}

function dedupeSimilarItems(items: ThinkingActivityItem[]) {
  const kept: ThinkingActivityItem[] = [];
  for (const item of items) {
    const duplicateIndex = kept.findIndex((candidate) =>
      isSimilarText(candidate.body, item.body),
    );
    if (duplicateIndex >= 0) kept.splice(duplicateIndex, 1);
    kept.push(item);
  }
  return kept;
}

function isSimilarText(left: string, right: string) {
  const a = canonicalText(left);
  const b = canonicalText(right);
  if (!a || !b) return false;
  if (a === b) return true;

  const shorter = a.length <= b.length ? a : b;
  const longer = a.length > b.length ? a : b;
  if (shorter.length >= 24 && longer.includes(shorter)) return true;

  const prefixRatio = commonPrefixLength(a, b) / Math.min(a.length, b.length);
  if (prefixRatio >= 0.68) return true;

  return diceCoefficient(a, b) >= 0.72;
}

function canonicalText(text: string) {
  return text.toLocaleLowerCase().replace(/[^\p{Letter}\p{Number}]+/gu, "");
}

function commonPrefixLength(left: string, right: string) {
  let length = 0;
  while (length < left.length && length < right.length && left[length] === right[length]) {
    length += 1;
  }
  return length;
}

function diceCoefficient(left: string, right: string) {
  if (left.length < 2 || right.length < 2) return left === right ? 1 : 0;
  const leftBigrams = bigramCounts(left);
  let overlap = 0;
  for (let index = 0; index < right.length - 1; index += 1) {
    const bigram = right.slice(index, index + 2);
    const count = leftBigrams.get(bigram) ?? 0;
    if (count > 0) {
      overlap += 1;
      leftBigrams.set(bigram, count - 1);
    }
  }
  return (2 * overlap) / (left.length + right.length - 2);
}

function bigramCounts(text: string) {
  const counts = new Map<string, number>();
  for (let index = 0; index < text.length - 1; index += 1) {
    const bigram = text.slice(index, index + 2);
    counts.set(bigram, (counts.get(bigram) ?? 0) + 1);
  }
  return counts;
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
