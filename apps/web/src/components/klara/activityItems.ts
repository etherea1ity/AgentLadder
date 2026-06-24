import type {
  ActivityFact,
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

export function visibleMainModelCommentaryItems(events: RunEvent[]) {
  return events
    .filter((event) => event.event_type === "assistant_activity_delta")
    .map((event) => {
      const text = safeText(event.payload?.text, 500);
      if (!text) return null;
      const phase = activityPhase(event.payload?.phase);
      const item: ThinkingActivityItem = {
        id: `activity_${event.event_id}`,
        title: phase,
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

export function visibleAgentTranscriptItems(events: RunEvent[]) {
  return events
    .filter((event) => event.event_type === "activity_fact_recorded")
    .map((event) => transcriptItemFromFact(event))
    .filter(isActivityItem)
    .filter(isSafeActivityItem);
}

function transcriptItemFromFact(event: RunEvent): ThinkingActivityItem | null {
  const fact = activityFact(event.payload?.fact);
  if (!fact) return null;
  const toolName = safeText(fact.tool?.name, 80);
  const status = activityStatus(fact.status);
  const evidence_event_ids = fact.evidence_event_ids.length
    ? fact.evidence_event_ids
    : [event.event_id];
  const base = {
    id: `transcript_${fact.id || event.event_id}`,
    status,
    source: "runtime_action" as ThinkingActivitySource,
    evidence_fact_ids: fact.id ? [fact.id] : undefined,
    evidence_event_ids,
    confidence: 1,
  };

  if (fact.kind === "web_search_result") {
    return {
      ...base,
      title: "web_search",
      body: joinParts(
        countLabel(numberField(fact.web?.result_count), "result"),
        stringList(fact.web?.top_domains).join(", "),
        stringList(fact.web?.top_titles).join(" · "),
      ),
      kind: "evidence",
    };
  }

  if (fact.kind === "web_fetch_result") {
    return {
      ...base,
      title: "web_fetch",
      body: joinParts(
        safeText(fact.web?.title_preview, 120),
        safeText(fact.web?.source_domain, 80),
        countLabel(numberField(fact.web?.text_length), "char"),
      ),
      kind: "evidence",
    };
  }

  if (fact.kind === "image_generation") {
    return {
      ...base,
      title: "image_generate",
      body: joinParts(
        countLabel(numberField(fact.image?.image_count), "asset"),
        safeText(fact.image?.provider, 80),
        safeText(fact.image?.model, 80),
      ),
      kind: "tool_activity",
    };
  }

  if (fact.kind === "error") {
    return {
      ...base,
      title: toolName ? `${toolName} failed` : "tool_failed",
      body: safeText(fact.error_preview || fact.observation_preview, 180) || "failed",
      kind: "error",
    };
  }

  if (fact.kind === "tool_call") {
    return {
      ...base,
      title: toolName || "tool",
      body: status,
      kind: "tool_activity",
    };
  }

  if (fact.kind === "tool_result") {
    return {
      ...base,
      title: toolName || "tool",
      body: joinParts(status, countLabel(numberField(fact.content_length), "char")),
      kind: "tool_activity",
    };
  }

  if (fact.kind === "policy_stop") {
    return {
      ...base,
      title: "policy_stop",
      body: safeText(fact.error_preview || fact.observation_preview, 180) || status,
      kind: "finalization",
    };
  }

  return null;
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

function activityFact(value: unknown): ActivityFact | null {
  if (!value || typeof value !== "object") return null;
  const record = value as ActivityFact;
  if (!record.kind || !record.status || !Array.isArray(record.evidence_event_ids))
    return null;
  return record;
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
  const text = stringField(value).replace(/\s+/g, " ");
  if (!text || containsFullUrl(text) || containsRawPayloadTerms(text)) return "";
  return text.slice(0, maxChars);
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

function numberField(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

function stringList(value: unknown) {
  return Array.isArray(value)
    ? value.map((item) => safeText(item, 90)).filter(Boolean)
    : [];
}

function countLabel(value: number | null, singular: string) {
  if (value == null) return "";
  const suffix = value === 1 ? singular : `${singular}s`;
  return `${value} ${suffix}`;
}

function joinParts(...parts: string[]) {
  return parts.filter(Boolean).join(" · ");
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
