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
