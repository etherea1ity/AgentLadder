import type { KlaraRunEvent, ModuleResult, Run } from "../../types/domain";
import { KlaraPresence } from "./KlaraPresence";
import { formatLatency, isKlaraRunActive, useKlaraRunMotion } from "./useKlaraRunMotion";

type RunActionCard = {
  id: string;
  title: string;
  status: "active" | "completed" | "failed" | "cancelled" | "queued";
  description: string;
  model?: string | null;
  duration?: string;
  inputTokens?: number | null;
  outputTokens?: number | null;
  events: KlaraRunEvent[];
  inputPayload?: Record<string, unknown>;
  outputPayload?: Record<string, unknown>;
};

export function KlaraRunPanel({
  run,
}: {
  run: Run;
  trace?: Record<string, unknown> | null;
}) {
  const view = useKlaraRunMotion(run);
  const live = isKlaraRunActive(run);
  const cards = buildRunActionCards(run, view.events);
  const summary = buildSummary(run);

  return (
    <section className="klara-run-panel">
      <header className="klara-run-projection">
        <KlaraPresence
          active={live}
          phase={view.phase}
          size="panel"
          capabilities={view.capabilities}
          elevated
          pulseKey={run.events.length}
        />
        <div>
          <p className="run-margin-eyebrow">Public Activity</p>
          <h3>{live ? "Live Run" : "Run Complete"}</h3>
          <small>{run.model ?? "selected model"}</small>
        </div>
      </header>

      <section className="klara-action-stack" aria-label="Run action cards">
        <h4>Run Chain</h4>
        {cards.map((card, index) => (
          <article className={`klara-action-card is-${card.status}`} key={card.id}>
            <div className="klara-action-index" aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </div>
            <div className="klara-action-body">
              <header className="klara-action-header">
                <div>
                  <p className="klara-action-eyebrow">Action</p>
                  <h5>{card.title}</h5>
                </div>
                <span className="klara-action-status">{labelForCardStatus(card.status)}</span>
              </header>
              <p className="klara-action-description">{card.description}</p>
              <dl className="klara-action-metrics">
                <div>
                  <dt>latency</dt>
                  <dd>{card.duration ?? "—"}</dd>
                </div>
                <div>
                  <dt>input tokens</dt>
                  <dd>{formatNumber(card.inputTokens)}</dd>
                </div>
                <div>
                  <dt>output tokens</dt>
                  <dd>{formatNumber(card.outputTokens)}</dd>
                </div>
                <div>
                  <dt>model</dt>
                  <dd>{card.model ?? "—"}</dd>
                </div>
              </dl>
              {card.events.length ? (
                <ol className="klara-action-events" aria-label={`${card.title} events`}>
                  {card.events.map((event) => (
                    <li key={event.eventId} className={`event-${event.status}`}>
                      <span aria-hidden="true">{event.status === "completed" ? "✓" : event.status === "failed" ? "!" : "●"}</span>
                      <b>{event.publicLabel}</b>
                    </li>
                  ))}
                </ol>
              ) : null}
              {card.inputPayload || card.outputPayload ? (
                <details className="klara-action-details">
                  <summary>View module data</summary>
                  {card.inputPayload ? (
                    <>
                      <b>Input</b>
                      <pre>{JSON.stringify(card.inputPayload, null, 2)}</pre>
                    </>
                  ) : null}
                  {card.outputPayload ? (
                    <>
                      <b>Output</b>
                      <pre>{JSON.stringify(card.outputPayload, null, 2)}</pre>
                    </>
                  ) : null}
                </details>
              ) : null}
            </div>
          </article>
        ))}
      </section>

      <section className="klara-run-summary" aria-label="Run summary totals">
        <h4>Summary</h4>
        <dl>
          <dt>latency</dt>
          <dd>{summary.duration ?? "—"}</dd>
          <dt>input tokens</dt>
          <dd>{formatNumber(summary.inputTokens)}</dd>
          <dt>output tokens</dt>
          <dd>{formatNumber(summary.outputTokens)}</dd>
        </dl>
      </section>
    </section>
  );
}

function buildRunActionCards(run: Run, events: KlaraRunEvent[]): RunActionCard[] {
  const moduleCards = buildModuleCards(run, events);
  return moduleCards.length ? moduleCards : [buildLlmCallCard(run, events)];
}

function buildModuleCards(run: Run, events: KlaraRunEvent[]): RunActionCard[] {
  const modules = latestModuleResults(run);
  const order = [
    "intent_router",
    "dense_retrieval",
    "bm25_retrieval",
    "hybrid_retrieval",
    "reranking",
    "context_builder",
    "klara_writer",
  ];
  return modules
    .sort((a, b) => {
      const ai = order.indexOf(a.module_id);
      const bi = order.indexOf(b.module_id);
      return (ai === -1 ? 99 : ai) - (bi === -1 ? 99 : bi);
    })
    .map((module) => ({
      id: `${run.run_id}-${module.module_id}`,
      title: module.module_name,
      status: statusFromModule(module, run),
      description: module.output_summary || module.input_summary || module.module_name,
      model: module.module_id === "klara_writer" ? run.model : null,
      duration: module.latency_ms != null ? formatLatency(module.latency_ms) : undefined,
      inputTokens: module.module_id === "klara_writer" ? firstNumber(run.prompt_tokens, payloadNumber(run, "prompt_tokens")) : null,
      outputTokens: module.module_id === "klara_writer" ? firstNumber(run.completion_tokens, payloadNumber(run, "completion_tokens")) : null,
      events: events.filter((event) => event.safePayload && (event.safePayload as { module_result?: { module_id?: string } }).module_result?.module_id === module.module_id),
      inputPayload: module.input_payload,
      outputPayload: module.output_payload,
    }));
}

function latestModuleResults(run: Run): ModuleResult[] {
  const byId = new Map<string, ModuleResult>();
  for (const event of run.events ?? []) {
    if (!["module_started", "module_completed", "module_failed"].includes(event.event_type)) continue;
    const raw = event.payload?.module_result;
    if (!isModuleResult(raw) || raw.module_id === "trace_saved") continue;
    byId.set(raw.module_id, raw);
  }
  return Array.from(byId.values());
}

function isModuleResult(value: unknown): value is ModuleResult {
  return Boolean(value && typeof value === "object" && typeof (value as ModuleResult).module_id === "string" && typeof (value as ModuleResult).module_name === "string");
}

function statusFromModule(module: ModuleResult, run: Run): RunActionCard["status"] {
  if (module.status === "completed" || module.status === "skipped") return "completed";
  if (module.status === "failed") return "failed";
  if (run.status === "cancelled") return "cancelled";
  if (module.status === "running") return "active";
  return "queued";
}

function buildLlmCallCard(run: Run, events: KlaraRunEvent[]): RunActionCard {
  const llmEvents = events.filter((event) =>
    [
      "model.call.started",
      "answer.started",
      "model.call.completed",
      "run.completed",
      "run.error",
    ].includes(event.kind),
  );
  const status: RunActionCard["status"] =
    run.status === "failed"
      ? "failed"
      : run.status === "cancelled"
        ? "cancelled"
        : run.status === "completed"
          ? "completed"
          : run.status === "queued"
            ? "queued"
            : "active";
  return {
    id: `${run.run_id}-llm-call`,
    title: "LLM Call",
    status,
    description: descriptionForLlmCard(run),
    model: run.model,
    duration: cardDuration(run, llmEvents),
    inputTokens: firstNumber(run.prompt_tokens, payloadNumber(run, "prompt_tokens")),
    outputTokens: firstNumber(run.completion_tokens, payloadNumber(run, "completion_tokens")),
    events: compactCardEvents(llmEvents),
  };
}

function compactCardEvents(events: KlaraRunEvent[]) {
  const wanted = new Set([
    "model.call.started",
    "answer.started",
    "model.call.completed",
    "run.completed",
    "run.error",
  ]);
  return events.filter((event) => wanted.has(event.kind));
}

function descriptionForLlmCard(run: Run) {
  if (run.status === "queued") return "Klara is preparing the model request.";
  if (run.status === "thinking") return "Klara is calling the selected model.";
  if (run.status === "streaming") return "The model is streaming the public answer.";
  if (run.status === "completed") return "The model call finished and the answer was saved.";
  if (run.status === "failed") return run.error?.message ?? "The model call failed.";
  return "The model call was stopped and partial output was preserved.";
}

function cardDuration(run: Run, events: KlaraRunEvent[]) {
  if (run.latency_ms != null) return formatLatency(run.latency_ms);
  if (run.live?.elapsed_ms != null) return formatLatency(run.live.elapsed_ms);
  const started = events.find((event) => event.kind === "model.call.started");
  const ended = [...events].reverse().find((event) =>
    ["model.call.completed", "run.completed", "run.error"].includes(event.kind),
  );
  if (!started || !ended) return undefined;
  const ms = Date.parse(ended.timestamp) - Date.parse(started.timestamp);
  return Number.isFinite(ms) && ms >= 0 ? formatLatency(ms) : undefined;
}

function buildSummary(run: Run) {
  return {
    duration: run.latency_ms != null ? formatLatency(run.latency_ms) : run.live?.elapsed_ms != null ? formatLatency(run.live.elapsed_ms) : undefined,
    inputTokens: firstNumber(run.prompt_tokens, payloadNumber(run, "prompt_tokens")),
    outputTokens: firstNumber(run.completion_tokens, payloadNumber(run, "completion_tokens")),
  };
}

function payloadNumber(run: Run, key: "prompt_tokens" | "completion_tokens") {
  for (const event of [...(run.events ?? [])].reverse()) {
    const value = event.payload?.[key];
    if (typeof value === "number") return value;
    const moduleResult = event.payload?.module_result as ModuleResult | undefined;
    const moduleValue = moduleResult?.output_payload?.[key];
    if (typeof moduleValue === "number") return moduleValue;
  }
  return null;
}

function firstNumber(...values: Array<number | null | undefined>) {
  return values.find((value): value is number => typeof value === "number") ?? null;
}

function formatNumber(value?: number | null) {
  return typeof value === "number" ? value.toLocaleString("en-US") : "—";
}

function labelForCardStatus(status: RunActionCard["status"]) {
  if (status === "active") return "Running";
  if (status === "completed") return "Completed";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Stopped";
  return "Queued";
}
