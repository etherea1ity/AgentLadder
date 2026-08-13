import { useEffect, useState } from 'react';
import { AlertTriangle, CheckCircle2, GitCompareArrows, RefreshCw, ShieldCheck } from 'lucide-react';
import { api } from '../api/client';
import type { EvaluationCatalog, EvaluationRunProjection, EvaluationSummary } from '../types/domain';

type Props = {
  onBackToChat: () => void;
};

export function EvaluationDashboard({ onBackToChat }: Props) {
  const [summary, setSummary] = useState<EvaluationSummary | null>(null);
  const [catalog, setCatalog] = useState<EvaluationCatalog | null>(null);
  const [error, setError] = useState('');
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setError('');
    setCatalog(null);
    api.getEvaluationSummary(controller.signal)
      .then((nextSummary) => {
        setSummary(nextSummary);
        void api.getEvaluationRuns(controller.signal)
          .then(setCatalog)
          .catch(() => {
            if (!controller.signal.aborted) setCatalog({ schema_version: 'klara.evaluation-catalog.v1', runs: [] });
          });
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setError(reason instanceof Error ? reason.message : 'Evaluation summary unavailable');
      });
    return () => controller.abort();
  }, [refreshKey]); // The catalog is supplemental; a missing comparison must not hide the primary gate.

  return (
    <main className="evaluation-workspace" aria-labelledby="evaluation-title">
      <header className="evaluation-header">
        <div>
          <span className="evaluation-eyebrow">Quality evidence</span>
          <h1 id="evaluation-title">Agent evaluations</h1>
          <p>Deterministic gates first, independent review second. Hidden cases stay outside this surface.</p>
        </div>
        <div className="evaluation-actions">
          <button type="button" onClick={() => setRefreshKey((value) => value + 1)}><RefreshCw size={16} /> Refresh</button>
          <button type="button" className="evaluation-primary" onClick={onBackToChat}>Back to chat</button>
        </div>
      </header>

      {!summary && !error ? <EvaluationState label="Loading evaluation evidence…" /> : null}
      {error ? <EvaluationState label={error} error /> : null}
      {summary && !summary.available ? <EvaluationState label="No evaluation run has been published yet." /> : null}
      {summary?.available ? <EvaluationReport summary={summary} catalog={catalog} /> : null}
    </main>
  );
}

function EvaluationReport({ summary, catalog }: { summary: EvaluationSummary; catalog: EvaluationCatalog | null }) {
  const passedChecks = Object.values(summary.checks).filter(Boolean).length;
  const totalChecks = Object.keys(summary.checks).length;
  const metricCards = [
    ['Task success', summary.metrics.normal_task_success_rate],
    ['Critical safety', summary.metrics.critical_deterministic_rate],
    ['Reference gap', summary.metrics.reference_gap],
    ['Human acceptance', summary.metrics.human_acceptability_rate],
  ] as const;
  return (
    <div className="evaluation-content">
      <section className={`evaluation-status ${summary.status}`}>
        <span className="evaluation-status-icon">{summary.status === 'passed' ? <ShieldCheck size={22} /> : <AlertTriangle size={22} />}</span>
        <div><strong>{summary.status === 'passed' ? 'Contract gate passed' : 'Gate needs attention'}</strong><p>{summary.interpretation}</p></div>
        <span className="evaluation-check-count">{passedChecks}/{totalChecks} checks</span>
      </section>

      <section className="evaluation-metrics" aria-label="Evaluation metrics">
        {metricCards.map(([label, value]) => <article key={label}><span>{label}</span><strong>{formatMetric(value)}</strong></article>)}
      </section>

      <section className="evaluation-panel">
        <header><div><span className="evaluation-eyebrow">Release gates</span><h2>Acceptance checks</h2></div><small>{summary.scorer_version}</small></header>
        <div className="evaluation-checks">
          {Object.entries(summary.checks).map(([name, passed]) => (
            <div key={name} className={passed ? 'passed' : 'failed'}>
              {passed ? <CheckCircle2 size={17} /> : <AlertTriangle size={17} />}
              <span>{humanize(name)}</span>
              <strong>{passed ? 'Pass' : 'Fail'}</strong>
            </div>
          ))}
        </div>
      </section>

      <section className="evaluation-panel evaluation-provenance">
        <header><div><span className="evaluation-eyebrow">Frozen inputs</span><h2>Dataset lineage</h2></div><small>{summary.counts.observations ?? 0} observations</small></header>
        <dl>{Object.entries(summary.split_hashes).map(([split, hash]) => <div key={split}><dt>{humanize(split)}</dt><dd title={hash}>{hash.slice(0, 16)}…</dd></div>)}</dl>
      </section>
      <EvaluationHistory runs={catalog?.runs ?? []} />
    </div>
  );
}

function EvaluationHistory({ runs }: { runs: EvaluationRunProjection[] }) {
  const [selected, setSelected] = useState<string | null>(runs[0]?.artifact_id ?? null);
  const current = runs.find((run) => run.artifact_id === selected) ?? runs[0];
  return <section className="evaluation-panel evaluation-history">
    <header><div><span className="evaluation-eyebrow">Safe comparison</span><h2><GitCompareArrows size={18} />Published gate history</h2></div><small>{runs.length} aggregate reports</small></header>
    {runs.length ? <div className="evaluation-history-layout">
      <div className="evaluation-run-list">{runs.slice(0, 18).map((run) => <button key={run.artifact_id} className={run.artifact_id === current?.artifact_id ? 'active' : ''} onClick={() => setSelected(run.artifact_id)}><span className={`is-${run.status}`} /> <strong>{humanize(run.stage === 'product' ? run.artifact_id : run.stage)}</strong><small>{run.status} · {run.evaluated_at ? new Date(run.evaluated_at).toLocaleDateString() : 'undated'}</small></button>)}</div>
      {current ? <article className="evaluation-run-detail"><header><div><span>{current.gate_kind}</span><strong>{humanize(current.artifact_id)}</strong></div><small>{current.scorer_version ?? 'scorer not declared'}</small></header><p>{current.interpretation || 'Published aggregate gate; detailed rationale remains in its bilingual report.'}</p><dl>{Object.entries(current.metrics).slice(0, 8).map(([key, value]) => <div key={key}><dt>{humanize(key)}</dt><dd>{formatCatalogMetric(key, value)}</dd></div>)}</dl><div className="evaluation-failures"><strong>Failed checks</strong>{Object.entries(current.checks).filter(([, passed]) => !passed).length ? Object.entries(current.checks).filter(([, passed]) => !passed).map(([key]) => <span key={key}><AlertTriangle size={13} />{humanize(key)}</span>) : <span className="is-clear"><CheckCircle2 size={13} />No failed aggregate check</span>}</div></article> : null}
    </div> : <div className="evaluation-empty"><p>No comparable aggregate gate has been published.</p></div>}
  </section>;
}

function EvaluationState({ label, error = false }: { label: string; error?: boolean }) {
  return <section className={`evaluation-empty ${error ? 'is-error' : ''}`}>{error ? <AlertTriangle size={22} /> : <RefreshCw size={22} />}<p>{label}</p></section>;
}

function formatMetric(value: number | undefined) {
  if (value === undefined) return '—';
  return `${(value * 100).toFixed(value === 1 || value === 0 ? 0 : 1)}%`;
}

function formatCatalogMetric(name: string, value: number) {
  if (/(rate|ratio|accuracy|precision|recall|success|acceptance|reference_gap)/i.test(name)) return formatMetric(value);
  if (/latency/i.test(name)) return `${value.toLocaleString()} ms`;
  return value.toLocaleString(undefined, { maximumFractionDigits: 3 });
}

function humanize(value: string) {
  return value.replace(/_/g, ' ').replace(/\b\w/g, (letter: string) => letter.toUpperCase());
}
