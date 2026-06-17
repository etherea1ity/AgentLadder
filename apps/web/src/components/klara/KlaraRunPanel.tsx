import type { KlaraRunEvent, ModuleResult, Run } from "../../types/domain";
import { KlaraPresence } from "./KlaraPresence";
import { formatLatency, isKlaraRunActive, useKlaraRunMotion } from "./useKlaraRunMotion";

type CardStatus = "active" | "completed" | "failed" | "cancelled" | "queued";
type Fact = { label: string; value?: unknown };
type DetailSection = { title: string; value: unknown };
type Lane = { title: string; facts: Fact[]; payload?: Record<string, unknown> };

type RunActionCard = {
  id: string;
  title: string;
  status: CardStatus;
  description: string;
  facts: Fact[];
  events: KlaraRunEvent[];
  inputPayload?: Record<string, unknown>;
  outputPayload?: Record<string, unknown>;
  details?: DetailSection[];
  lanes?: Lane[];
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
          <small>v0.3 Agentic RAG</small>
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
                  <p className="klara-action-eyebrow">Layer</p>
                  <h5>{card.title}</h5>
                </div>
                <span className="klara-action-status">{labelForCardStatus(card.status)}</span>
              </header>
              <p className="klara-action-description">{card.description}</p>
              {card.facts.length ? <FactGrid facts={card.facts} /> : null}
              {card.lanes?.length ? (
                <div className="klara-action-events" aria-label={`${card.title} lanes`}>
                  {card.lanes.map((lane) => (
                    <details className="klara-action-details" key={lane.title}>
                      <summary>{lane.title}</summary>
                      <FactGrid facts={lane.facts} />
                      {lane.payload ? <pre>{JSON.stringify(lane.payload, null, 2)}</pre> : null}
                    </details>
                  ))}
                </div>
              ) : null}
              {card.details?.length
                ? card.details.map((detail) => (
                    <details className="klara-action-details" key={detail.title}>
                      <summary>{detail.title}</summary>
                      <pre>{formatDetailValue(detail.value)}</pre>
                    </details>
                  ))
                : null}
              {!card.details?.length && (card.inputPayload || card.outputPayload) ? (
                <details className="klara-action-details">
                  <summary>Structured JSON</summary>
                  <pre>{formatDetailValue({ input: card.inputPayload, output: card.outputPayload })}</pre>
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

function FactGrid({ facts }: { facts: Fact[] }) {
  const visible = facts.filter((fact) => fact.value !== undefined && fact.value !== null && fact.value !== "");
  if (!visible.length) return null;
  return (
    <dl className="klara-action-metrics">
      {visible.map((fact) => (
        <div key={fact.label}>
          <dt>{fact.label}</dt>
          <dd>{formatValue(fact.value)}</dd>
        </div>
      ))}
    </dl>
  );
}

function buildRunActionCards(run: Run, events: KlaraRunEvent[]): RunActionCard[] {
  const modules = latestModuleMap(run);
  const cards = [
    buildRouterCard(run, modules.get("intent_router")),
    buildRetrievalLayerCard(run, modules),
    buildWriterCard(run, modules.get("klara_writer")),
  ].filter((card): card is RunActionCard => Boolean(card));
  return cards.length ? cards : [buildLlmCallCard(run, events)];
}

function buildRouterCard(run: Run, module?: ModuleResult): RunActionCard | null {
  if (!module) return null;
  const output = module.output_payload ?? {};
  const decision = objectValue(output.decision) ?? output;
  const route = stringValue(decision.route ?? output.route);
  const confidence = numberValue(decision.confidence ?? output.confidence);
  return {
    id: `${run.run_id}-router-layer`,
    title: "Intent Router",
    status: statusFromModule(module, run),
    description: "Decides whether this question needs local knowledge.",
    facts: [
      { label: "route", value: route?.toUpperCase() },
      { label: "confidence", value: confidence != null ? confidence.toFixed(2) : undefined },
      { label: "query type", value: stringValue(decision.query_type ?? output.query_type) },
      { label: "model", value: stringValue(output.model ?? decision.router_model) },
      { label: "latency", value: module.latency_ms != null ? formatLatency(module.latency_ms) : undefined },
      { label: "input tokens", value: numberValue(output.prompt_tokens) },
      { label: "output tokens", value: numberValue(output.completion_tokens) },
    ],
    events: [],
    details: [
      { title: "System prompt", value: module.input_payload?.system_prompt },
      { title: "Structured JSON", value: { input: omitKeys(module.input_payload, ["system_prompt"]), output: module.output_payload } },
    ],
  };
}

function buildRetrievalLayerCard(run: Run, modules: Map<string, ModuleResult>): RunActionCard | null {
  const dense = modules.get("dense_retrieval");
  const bm25 = modules.get("bm25_retrieval");
  const hybrid = modules.get("hybrid_retrieval");
  const rerank = modules.get("reranking");
  const context = modules.get("context_builder");
  const retrievalModules = [dense, bm25, hybrid, rerank, context].filter((item): item is ModuleResult => Boolean(item));
  if (!retrievalModules.length) return null;

  const denseOut = dense?.output_payload ?? {};
  const bm25Out = bm25?.output_payload ?? {};
  const hybridOut = hybrid?.output_payload ?? {};
  const rerankOut = rerank?.output_payload ?? {};
  const contextOut = context?.output_payload ?? {};
  const lanes: Lane[] = [];
  const retrievalLatency = sumLatency(retrievalModules);

  if (dense || bm25) {
    lanes.push({
      title: "Coarse Recall",
      facts: [
        { label: "dense", value: dense ? `${formatNumber(numberValue(denseOut.candidate_count))} candidates` : undefined },
        { label: "dense latency", value: dense?.latency_ms != null ? formatLatency(dense.latency_ms) : undefined },
        { label: "dense method", value: denseOut.algorithm ?? "cosine_similarity" },
        { label: "sparse", value: bm25 ? `${formatNumber(numberValue(bm25Out.candidate_count))} candidates` : undefined },
        { label: "sparse latency", value: bm25?.latency_ms != null ? formatLatency(bm25.latency_ms) : undefined },
        { label: "sparse method", value: bm25Out.algorithm ?? "BM25" },
      ],
      payload: {
        dense: { input: dense?.input_payload, output: dense?.output_payload },
        sparse: { input: bm25?.input_payload, output: bm25?.output_payload },
      },
    });
  }
  if (hybrid) {
    lanes.push({
      title: "Fusion",
      facts: [
        { label: "fusion", value: hybridOut.algorithm ?? "weighted_score_fusion" },
        { label: "fused", value: hybridOut.candidate_count },
        { label: "dense weight", value: hybridOut.dense_weight },
        { label: "sparse weight", value: hybridOut.sparse_weight },
        { label: "latency", value: hybrid.latency_ms != null ? formatLatency(hybrid.latency_ms) : undefined },
      ],
      payload: {
        input: hybrid.input_payload,
        output: hybrid.output_payload,
      },
    });
  }
  if (rerank || context) {
    lanes.push({
      title: "Fine Reranking",
      facts: [
        { label: "reranker", value: rerankOut.algorithm ?? "SimpleReranker" },
        { label: "rerank latency", value: rerank?.latency_ms != null ? formatLatency(rerank.latency_ms) : undefined },
        { label: "selected", value: rerankOut.selected_chunks },
        { label: "evidence tokens", value: contextOut.token_estimate },
      ],
      payload: {
        reranking: { input: rerank?.input_payload, output: rerank?.output_payload },
        selected_evidence: contextOut.writer_input ?? { evidence: contextOut.sources },
      },
    });
  }

  return {
    id: `${run.run_id}-retrieval-layer`,
    title: "RAG Retrieval",
    status: combinedStatus(retrievalModules, run),
    description: "Coarse recall finds candidates; fusion and fine reranking select evidence for the writer.",
    facts: [
      { label: "latency", value: retrievalLatency != null ? formatLatency(retrievalLatency) : undefined },
      { label: "dense", value: numberValue(denseOut.candidate_count) },
      { label: "sparse", value: numberValue(bm25Out.candidate_count) },
      { label: "selected", value: numberValue(rerankOut.selected_chunks) },
      { label: "evidence tokens", value: numberValue(contextOut.token_estimate) },
    ],
    events: [],
    lanes,
    details: [
      {
        title: "Structured JSON",
        value: {
          coarse_recall: {
            dense: { input: dense?.input_payload, output: dense?.output_payload },
            sparse: { input: bm25?.input_payload, output: bm25?.output_payload },
          },
          fusion: { input: hybrid?.input_payload, output: hybrid?.output_payload },
          fine_reranking: { input: rerank?.input_payload, output: rerank?.output_payload },
          selected_evidence: contextOut.writer_input ?? { evidence: contextOut.sources },
        },
      },
    ],
  };
}

function buildWriterCard(run: Run, module?: ModuleResult): RunActionCard | null {
  if (!module) return null;
  const output = module.output_payload ?? {};
  const systemPrompt = stringValue(module.input_payload?.system_prompt);
  const structuredInput = module.input_payload?.structured_input;
  return {
    id: `${run.run_id}-writer-layer`,
    title: "Writer",
    status: statusFromModule(module, run),
    description: "Writes the final answer from the selected context.",
    facts: [
      { label: "model", value: stringValue(output.model) ?? run.model },
      { label: "latency", value: module.latency_ms != null ? formatLatency(module.latency_ms) : undefined },
      { label: "input tokens", value: firstNumber(run.prompt_tokens, numberValue(output.prompt_tokens)) },
      { label: "output tokens", value: firstNumber(run.completion_tokens, numberValue(output.completion_tokens)) },
      { label: "route", value: stringValue(output.route)?.toUpperCase() },
    ],
    events: [],
    details: [
      { title: "System prompt", value: systemPrompt },
      { title: "Structured input", value: structuredInput },
      { title: "Answer frame", value: output.answer_frame },
    ],
  };
}

function sumLatency(modules: ModuleResult[]) {
  const values = modules
    .map((module) => module.latency_ms)
    .filter((value): value is number => typeof value === "number");
  return values.length ? values.reduce((total, value) => total + value, 0) : null;
}

function latestModuleMap(run: Run): Map<string, ModuleResult> {
  const byId = new Map<string, ModuleResult>();
  for (const event of run.events ?? []) {
    if (!["module_started", "module_completed", "module_failed"].includes(event.event_type)) continue;
    const raw = event.payload?.module_result;
    if (!isModuleResult(raw) || raw.module_id === "trace_saved") continue;
    byId.set(raw.module_id, raw);
  }
  return byId;
}

function isModuleResult(value: unknown): value is ModuleResult {
  return Boolean(value && typeof value === "object" && typeof (value as ModuleResult).module_id === "string" && typeof (value as ModuleResult).module_name === "string");
}

function statusFromModule(module: ModuleResult, run: Run): CardStatus {
  if (module.status === "completed" || module.status === "skipped") return "completed";
  if (module.status === "failed") return "failed";
  if (run.status === "cancelled") return "cancelled";
  if (module.status === "running") return "active";
  return "queued";
}

function combinedStatus(modules: ModuleResult[], run: Run): CardStatus {
  if (modules.some((module) => module.status === "failed")) return "failed";
  if (run.status === "cancelled") return "cancelled";
  if (modules.some((module) => module.status === "running")) return "active";
  if (modules.every((module) => module.status === "completed" || module.status === "skipped")) return "completed";
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
  const status: CardStatus =
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
    facts: [
      { label: "latency", value: cardDuration(run, llmEvents) },
      { label: "input tokens", value: firstNumber(run.prompt_tokens, payloadNumber(run, "prompt_tokens")) },
      { label: "output tokens", value: firstNumber(run.completion_tokens, payloadNumber(run, "completion_tokens")) },
      { label: "model", value: run.model },
    ],
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
  const modules = latestModuleMap(run);
  let inputTokens = 0;
  let outputTokens = 0;
  let hasModuleUsage = false;
  for (const moduleId of ["intent_router", "klara_writer"]) {
    const output = modules.get(moduleId)?.output_payload;
    const prompt = numberValue(output?.prompt_tokens);
    const completion = numberValue(output?.completion_tokens);
    if (prompt != null || completion != null) {
      hasModuleUsage = true;
      inputTokens += prompt ?? 0;
      outputTokens += completion ?? 0;
    }
  }
  return {
    duration: run.latency_ms != null ? formatLatency(run.latency_ms) : run.live?.elapsed_ms != null ? formatLatency(run.live.elapsed_ms) : undefined,
    inputTokens: hasModuleUsage ? inputTokens : firstNumber(run.prompt_tokens, payloadNumber(run, "prompt_tokens")),
    outputTokens: hasModuleUsage ? outputTokens : firstNumber(run.completion_tokens, payloadNumber(run, "completion_tokens")),
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

function numberValue(value: unknown) {
  return typeof value === "number" ? value : null;
}

function stringValue(value: unknown) {
  return typeof value === "string" ? value : undefined;
}

function objectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === "object" && !Array.isArray(value) ? (value as Record<string, unknown>) : undefined;
}

function formatNumber(value?: number | null) {
  return typeof value === "number" ? value.toLocaleString("en-US") : "—";
}

function formatValue(value: unknown) {
  if (typeof value === "number") return formatNumber(value);
  if (typeof value === "boolean") return value ? "yes" : "no";
  if (Array.isArray(value)) return value.join(", ");
  return String(value ?? "—");
}

function formatDetailValue(value: unknown) {
  if (typeof value === "string") return value;
  return JSON.stringify(value ?? null, null, 2);
}

function omitKeys(source: Record<string, unknown> | undefined, keys: string[]) {
  if (!source) return undefined;
  const blocked = new Set(keys);
  return Object.fromEntries(Object.entries(source).filter(([key]) => !blocked.has(key)));
}

function labelForCardStatus(status: CardStatus) {
  if (status === "active") return "Running";
  if (status === "completed") return "Completed";
  if (status === "failed") return "Failed";
  if (status === "cancelled") return "Stopped";
  return "Queued";
}
