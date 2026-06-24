import { CheckCircle2, ChevronDown, ChevronRight, CircleDashed, Wrench, XCircle } from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";
import type { ActivityFact, Run, RunEvent } from "../../types/domain";
import { isKlaraRunActive } from "./useKlaraRunMotion";

type LlmRound = {
  id: string;
  turnIndex: string;
  model: string;
  duration: string;
  promptTokens: string;
  completionTokens: string;
  totalTokens: string;
  tokenSource: string;
  toolCallCount: string;
  rawEvents: RunEvent[];
};

type ToolCard = {
  id: string;
  name: string;
  status: "running" | "completed" | "failed";
  duration: string;
  argumentsPreview: string;
  observationPreview: string;
  contentLength: string;
  error: string;
  rawEvents: RunEvent[];
};

export function KlaraRunSurface({
  run,
  developerCollapsed = false,
}: {
  run?: Run;
  developerCollapsed?: boolean;
}) {
  const active = isKlaraRunActive(run);
  const [expanded, setExpanded] = useState(developerCollapsed ? false : active);

  useEffect(() => {
    setExpanded(developerCollapsed ? false : active);
  }, [active, developerCollapsed, run?.run_id]);

  const visibleEvents = useMemo(
    () => (run?.events ?? []).filter((event) => event.event_type !== "answer_delta"),
    [run?.events],
  );
  const llmRounds = useMemo(() => buildLlmRounds(visibleEvents), [visibleEvents]);
  const toolCards = useMemo(() => buildToolCards(visibleEvents), [visibleEvents]);
  const activityFacts = useMemo(() => buildActivityFacts(visibleEvents), [visibleEvents]);
  const traceSaved = Boolean(
    run?.trace_saved ||
      visibleEvents.some(
        (event) =>
          event.event_type === "trace_saved" ||
          (event.event_type === "run_completed" && event.payload?.trace_saved === true),
      ),
  );
  const traceLabel = traceSaved
    ? "Trace saved"
    : active
      ? "Tracing"
      : visibleEvents.length
        ? "Events loaded"
        : "Trace unavailable";

  if (!run) return null;

  const title = `Developer debug - ${visibleEvents.length} events - ${toolCards.length} ${toolCards.length === 1 ? "tool" : "tools"}`;

  return (
    <section className={`klara-run-surface ${active ? "is-active" : "is-compact"}`} aria-label="Developer debug">
      <button
        className="klara-run-surface-toggle"
        type="button"
        aria-expanded={expanded}
        onClick={() => setExpanded((value) => !value)}
      >
        {expanded ? <ChevronDown size={16} /> : <ChevronRight size={16} />}
        <span>{title}</span>
        <small>{traceLabel}</small>
      </button>
      {expanded ? (
        <div className="klara-run-surface-body">
          {llmRounds.length ? (
            <DebugSection title="LLM rounds">
              <div className="klara-debug-card-grid">
                {llmRounds.map((round) => (
                  <LlmRoundCard key={round.id} round={round} />
                ))}
              </div>
            </DebugSection>
          ) : null}

          {toolCards.length ? (
            <DebugSection title="Tools">
              <div className="klara-tool-card-grid">
                {toolCards.map((tool) => (
                  <ToolRunCard key={tool.id} tool={tool} />
                ))}
              </div>
            </DebugSection>
          ) : null}

          {activityFacts.length ? (
            <DebugSection title="Activity facts">
              <div className="klara-debug-card-grid">
                {activityFacts.map((fact) => (
                  <ActivityFactCard key={fact.id} fact={fact} />
                ))}
              </div>
            </DebugSection>
          ) : null}

          {visibleEvents.length ? (
            <DebugSection title="Trace">
              <ol className="klara-run-timeline" aria-label="Lifecycle timeline">
                {visibleEvents.map((event) => (
                  <TraceEventItem key={event.event_id} event={event} />
                ))}
              </ol>
            </DebugSection>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function DebugSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="klara-debug-section">
      <h4>{title}</h4>
      {children}
    </section>
  );
}

function LlmRoundCard({ round }: { round: LlmRound }) {
  return (
    <article className="klara-debug-card">
      <header>
        <h5>Turn {round.turnIndex}</h5>
        <span>{round.model}</span>
      </header>
      <dl className="klara-debug-metrics">
        <Metric label="duration" value={round.duration} />
        <Metric label="input tokens" value={round.promptTokens} />
        <Metric label="output tokens" value={round.completionTokens} />
        <Metric label="total tokens" value={round.totalTokens} />
        <Metric label="token source" value={round.tokenSource} />
        <Metric label="tool calls" value={round.toolCallCount} />
      </dl>
      <RawEvents events={round.rawEvents} />
    </article>
  );
}

function ToolRunCard({ tool }: { tool: ToolCard }) {
  const Icon =
    tool.status === "completed" ? CheckCircle2 : tool.status === "failed" ? XCircle : CircleDashed;
  const detail = tool.status === "failed" ? tool.error : tool.observationPreview;
  return (
    <article className={`klara-tool-card is-${tool.status}`}>
      <span className="klara-tool-icon" aria-hidden="true">
        <Wrench size={15} />
      </span>
      <div>
        <header>
          <h4>{tool.name}</h4>
          <span>
            <Icon size={14} />
            {tool.status}
          </span>
        </header>
        <dl className="klara-debug-metrics">
          <Metric label="duration" value={tool.duration} />
          <Metric label="args" value={tool.argumentsPreview} />
          <Metric label="observation" value={detail || "unknown"} />
          <Metric label="content length" value={tool.contentLength} />
        </dl>
        <RawEvents events={tool.rawEvents} />
      </div>
    </article>
  );
}

function ActivityFactCard({ fact }: { fact: ActivityFact }) {
  return (
    <article className="klara-debug-card">
      <header>
        <h5>{fact.kind}</h5>
        <span>{fact.status}</span>
      </header>
      <dl className="klara-debug-metrics">
        <Metric label="source event" value={fact.source_event_type} />
        <Metric label="events" value={fact.evidence_event_ids.join(", ") || "unknown"} />
        <Metric label="tool" value={stringFrom(fact.tool?.name) || "unknown"} />
        <Metric label="preview" value={fact.observation_preview || fact.error_preview || "unknown"} />
      </dl>
      <details className="klara-debug-raw">
        <summary>Raw fact</summary>
        <pre>{JSON.stringify(fact, null, 2)}</pre>
      </details>
    </article>
  );
}

function Metric({ label, value }: { label: string; value: string }) {
  return (
    <>
      <dt>{label}</dt>
      <dd>{value}</dd>
    </>
  );
}

function RawEvents({ events }: { events: RunEvent[] }) {
  if (!events.length) return null;
  return (
    <details className="klara-debug-raw">
      <summary>Raw payload</summary>
      {events.map((event) => (
        <pre key={event.event_id}>{JSON.stringify(event.payload ?? {}, null, 2)}</pre>
      ))}
    </details>
  );
}

function TraceEventItem({ event }: { event: RunEvent }) {
  const status = event.event_type.includes("failed")
    ? "failed"
    : event.event_type.includes("started")
      ? "running"
      : "completed";
  return (
    <li className={`is-${status}`}>
      <span aria-hidden="true" />
      <div>
        <p>{event.event_type}</p>
        <small>
          {event.event_id} - {event.created_at}
        </small>
        <RawEvents events={[event]} />
      </div>
    </li>
  );
}

function buildLlmRounds(events: RunEvent[]): LlmRound[] {
  const rounds = new Map<string, Partial<LlmRound> & { rawEvents: RunEvent[] }>();
  events.forEach((event) => {
    if (event.event_type !== "llm_call_started" && event.event_type !== "llm_call_completed") return;
    const turnIndex = stringFrom(event.payload?.turn_index) || "unknown";
    const id = `llm_${turnIndex}`;
    const existing = rounds.get(id) ?? { id, turnIndex, rawEvents: [] };
    existing.rawEvents.push(event);
    if (event.event_type === "llm_call_started") {
      existing.model = stringFrom(event.payload?.model) || existing.model || "unknown";
    }
    if (event.event_type === "llm_call_completed") {
      existing.duration = durationLabel(event);
      existing.promptTokens = numberLabel(event.payload?.prompt_tokens);
      existing.completionTokens = numberLabel(event.payload?.completion_tokens);
      existing.totalTokens = numberLabel(event.payload?.total_tokens);
      existing.tokenSource = stringFrom(event.payload?.token_source) || "unknown";
      existing.toolCallCount = numberLabel(event.payload?.tool_call_count);
    }
    rounds.set(id, existing);
  });
  return Array.from(rounds.values()).map((round) => ({
    id: round.id ?? "llm_unknown",
    turnIndex: round.turnIndex ?? "unknown",
    model: round.model ?? "unknown",
    duration: round.duration ?? "unknown",
    promptTokens: round.promptTokens ?? "unknown",
    completionTokens: round.completionTokens ?? "unknown",
    totalTokens: round.totalTokens ?? "unknown",
    tokenSource: round.tokenSource ?? "unknown",
    toolCallCount: round.toolCallCount ?? "unknown",
    rawEvents: round.rawEvents,
  }));
}

function buildToolCards(events: RunEvent[]): ToolCard[] {
  const cards = new Map<string, ToolCard>();
  events.forEach((event) => {
    if (event.event_type === "tool_call_started") {
      const call = event.payload?.tool_call as { id?: string; name?: string; arguments?: unknown } | undefined;
      const id = call?.id ?? event.event_id;
      cards.set(id, {
        id,
        name: call?.name ?? "tool",
        status: "running",
        duration: "unknown",
        argumentsPreview: previewValue(call?.arguments),
        observationPreview: "",
        contentLength: "unknown",
        error: "",
        rawEvents: [event],
      });
      return;
    }
    if (event.event_type !== "tool_call_completed" && event.event_type !== "tool_call_failed") return;
    const result = event.payload?.tool_result as {
      tool_call_id?: string;
      name?: string;
      content_preview?: string;
      content_length?: number;
      error?: string;
    } | undefined;
    const id = result?.tool_call_id ?? event.event_id;
    const existing = cards.get(id);
    cards.set(id, {
      id,
      name: result?.name ?? existing?.name ?? "tool",
      status: event.event_type === "tool_call_failed" ? "failed" : "completed",
      duration: durationLabel(event),
      argumentsPreview: existing?.argumentsPreview ?? "unknown",
      observationPreview: result?.content_preview ?? existing?.observationPreview ?? "",
      error: result?.error ?? "",
      contentLength:
        typeof result?.content_length === "number"
          ? String(result.content_length)
          : existing?.contentLength ?? "unknown",
      rawEvents: [...(existing?.rawEvents ?? []), event],
    });
  });
  return Array.from(cards.values());
}

function buildActivityFacts(events: RunEvent[]): ActivityFact[] {
  return events
    .filter((event) => event.event_type === "activity_fact_recorded")
    .map((event) => event.payload?.fact)
    .filter(isActivityFact);
}

function isActivityFact(value: unknown): value is ActivityFact {
  if (!value || typeof value !== "object") return false;
  const record = value as Record<string, unknown>;
  return (
    typeof record.id === "string" &&
    typeof record.kind === "string" &&
    typeof record.status === "string" &&
    typeof record.source_event_type === "string" &&
    Array.isArray(record.evidence_event_ids)
  );
}

function durationLabel(event: RunEvent) {
  const metrics = event.payload?.metrics as { duration_ms?: number } | undefined;
  const duration = numberFrom(event.payload?.duration_ms) ?? numberFrom(metrics?.duration_ms);
  return duration != null ? `${duration}ms` : "unknown";
}

function previewValue(value: unknown) {
  if (value == null) return "unknown";
  if (typeof value === "string") return value.slice(0, 120) || "unknown";
  try {
    return JSON.stringify(value).slice(0, 120) || "unknown";
  } catch {
    return "unknown";
  }
}

function stringFrom(value: unknown) {
  if (typeof value === "number") return String(value);
  return typeof value === "string" && value.trim() ? value.trim() : "";
}

function numberLabel(value: unknown) {
  const number = numberFrom(value);
  return number == null ? "unknown" : String(number);
}

function numberFrom(value: unknown) {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}
