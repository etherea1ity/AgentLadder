import type { Run } from "../types/domain";
import { isKlaraRunActive } from "./klara/useKlaraRunMotion";
import { KlaraRunPanel } from "./klara/KlaraRunPanel";

type Props = {
  run: Run | null;
  onClose: () => void;
  trace?: Record<string, unknown> | null;
};

export function RunMargin({ run, onClose, trace }: Props) {
  if (!run) return null;
  const safeJson = JSON.stringify(
    sanitizeTraceForDisplay(trace ?? run),
    null,
    2,
  );
  const live = isKlaraRunActive(run);
  return (
    <aside
      className="run-margin klara-run-margin"
      id="run-margin-panel"
      aria-label="Run Margin"
    >
      <header className="run-margin-header klara-run-margin-header">
        <div>
          <small>Run Margin</small>
          <h2>{live ? "Klara Run · Live" : "Klara Run · Summary"}</h2>
        </div>
        <button onClick={onClose} aria-label="Close Run Margin">
          ×
        </button>
      </header>
      <KlaraRunPanel run={run} trace={trace} />
      <AgenticTraceSummary trace={trace} />
      {run.status === "failed" ? (
        <FailedView run={run} onClose={onClose} />
      ) : null}
      {run.status === "completed" ? (
        <details className="trace-toggle klara-trace-toggle">
          <summary>View safe JSON trace</summary>
          <pre>{safeJson}</pre>
        </details>
      ) : null}
      {run.status === "completed" ? (
        <button className="copy-json" onClick={() => copyText(safeJson)}>
          Copy safe JSON
        </button>
      ) : null}
    </aside>
  );
}


function AgenticTraceSummary({ trace }: { trace?: Record<string, unknown> | null }) {
  const answerFrame = asRecord(trace?.answer_frame);
  const searchPlan = asRecord(trace?.search_plan);
  const verification = asRecord(trace?.verification);
  const sources = asArray(answerFrame?.sources).slice(0, 8).map(asRecord).filter(Boolean) as Record<string, unknown>[];
  const visuals = asArray(answerFrame?.visual_sources).slice(0, 6).map(asRecord).filter(Boolean) as Record<string, unknown>[];
  const attempts = asArray(trace?.retrieval_attempts);
  if (!answerFrame && !searchPlan && !verification) return null;
  return (
    <section className="agentic-run-summary" aria-label="Agentic RAG run summary">
      <header>
        <small>Chapter 3 Runtime</small>
        <h3>Controlled Evidence Search</h3>
      </header>
      <dl className="agentic-run-metrics">
        <div><dt>search units</dt><dd>{asArray(searchPlan?.search_units).length}</dd></div>
        <div><dt>retrieval attempts</dt><dd>{attempts.length}</dd></div>
        <div><dt>evidence items</dt><dd>{asArray(answerFrame?.evidence_items).length}</dd></div>
        <div><dt>verification</dt><dd>{String(verification?.status ?? "unknown")}</dd></div>
      </dl>
      {sources.length ? (
        <div className="agentic-run-cards">
          <strong>Sources</strong>
          {sources.map((source, index) => (
            <article key={String(source.source_id ?? index)}>
              <span>{index + 1}</span>
              <div>
                <b>{String(source.title ?? source.paper_title ?? source.source_id ?? "Source")}</b>
                <p>{source.source_type ? String(source.source_type) : "paper source"}</p>
              </div>
            </article>
          ))}
        </div>
      ) : null}
      {visuals.length ? (
        <div className="agentic-run-cards visual-source-cards">
          <strong>Visual Sources</strong>
          {visuals.map((visual, index) => {
            const imagePath = typeof visual.image_path === "string" ? visual.image_path : "";
            const imageUrl = isImageAsset(imagePath) ? `/api/assets/local?path=${encodeURIComponent(imagePath)}` : "";
            return (
              <article key={String(visual.visual_id ?? visual.source_id ?? index)}>
                <span>{String(visual.visual_type ?? "visual")}</span>
                <div>
                  <b>{String(visual.title ?? visual.source_id ?? "Visual evidence")}</b>
                  {imageUrl ? <img src={imageUrl} alt={String(visual.caption ?? "Visual evidence")} loading="lazy" onError={(event) => { event.currentTarget.style.display = "none"; }} /> : null}
                  <p>{String(visual.caption ?? visual.visual_summary ?? "Caption metadata available.")}</p>
                  {imagePath ? <small>{imagePath}</small> : null}
                </div>
              </article>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function isImageAsset(path: string): boolean {
  return /\.(png|jpe?g|webp|svg|gif)$/i.test(path);
}

function asRecord(value: unknown): Record<string, unknown> | null {
  return value && typeof value === "object" && !Array.isArray(value) ? value as Record<string, unknown> : null;
}

function asArray(value: unknown): unknown[] {
  return Array.isArray(value) ? value : [];
}

function FailedView({ run, onClose }: { run: Run; onClose: () => void }) {
  const errorText = run.error?.message ?? "The LLM call failed.";
  return (
    <div className="failed">
      <p>{errorText}</p>
      <dl className="live-metrics">
        <dt>stage</dt>
        <dd>{run.error?.stage ?? "llm_call"}</dd>
        <dt>code</dt>
        <dd>{run.error?.code ?? "—"}</dd>
      </dl>
      <div className="run-actions">
        <button onClick={() => copyText(errorText)}>Copy error</button>
        <button onClick={onClose}>Close</button>
      </div>
    </div>
  );
}

function sanitizeTraceForDisplay(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sanitizeTraceForDisplay);
  if (!value || typeof value !== "object") return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .filter(([key]) => !/reasoning|chain|scratchpad|cot|delta/i.test(key))
      .map(([key, item]) => [key, sanitizeTraceForDisplay(item)]),
  );
}

function copyText(text: string) {
  void navigator.clipboard?.writeText(text);
}
