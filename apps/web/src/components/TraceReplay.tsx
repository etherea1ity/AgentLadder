import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowLeft, CheckCircle2, CircleDashed, Clock3, Code2, RefreshCw, Search, ShieldCheck, XCircle } from 'lucide-react';
import { api } from '../api/client';
import type { Run, RunEvent } from '../types/domain';

export function TraceReplay({ runs, onBackToChat }: { runs: Record<string, Run>; onBackToChat: () => void }) {
  const orderedRuns = useMemo(() => Object.values(runs).sort((a, b) => String(b.started_at ?? b.completed_at ?? '').localeCompare(String(a.started_at ?? a.completed_at ?? ''))), [runs]);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(orderedRuns[0]?.run_id ?? null);
  const [detail, setDetail] = useState<Run | null>(orderedRuns[0] ?? null);
  const [query, setQuery] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (!selectedRunId && orderedRuns[0]) setSelectedRunId(orderedRuns[0].run_id);
  }, [orderedRuns, selectedRunId]);

  useEffect(() => {
    if (!selectedRunId) { setDetail(null); return; }
    const controller = new AbortController();
    setLoading(true); setError('');
    api.getRun(selectedRunId, controller.signal).then((response) => {
      setDetail({ ...response.run, events: response.events });
    }).catch((caught: unknown) => {
      if (!controller.signal.aborted) {
        setDetail(runs[selectedRunId] ?? null);
        setError('The persisted trace could not be refreshed. Showing the current in-memory public events only.');
      }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [selectedRunId, runs]);

  const events = (detail?.events ?? []).filter((event) => `${event.event_type} ${event.message}`.toLowerCase().includes(query.trim().toLowerCase()));
  const toolCount = detail?.events.filter((event) => event.event_type === 'tool_call_started').length ?? 0;
  const failureCount = detail?.events.filter((event) => event.event_type.endsWith('failed') || event.event_type === 'policy_stop').length ?? 0;

  return <main className="trace-page" aria-labelledby="trace-title">
    <header className="trace-header">
      <div><button onClick={onBackToChat}><ArrowLeft size={16} />Back to chat</button><span><Code2 size={14} />Developer surface</span><h1 id="trace-title">Trace replay</h1><p>Inspect the ordered public event contract. Private chain-of-thought, raw secrets, and hidden evaluation cases are never rendered here.</p></div>
      <span className="trace-safety"><ShieldCheck size={17} />Public payloads only</span>
    </header>
    <div className="trace-layout">
      <aside className="trace-run-list" aria-label="Runs">
        <header><strong>Runs</strong><span>{orderedRuns.length}</span></header>
        {orderedRuns.length ? orderedRuns.map((run) => <button key={run.run_id} className={run.run_id === selectedRunId ? 'active' : ''} onClick={() => setSelectedRunId(run.run_id)}>
          <span className={`trace-run-state is-${run.status}`}>{run.status === 'completed' ? <CheckCircle2 size={15} /> : run.status === 'failed' || run.status === 'cancelled' ? <XCircle size={15} /> : <CircleDashed size={15} />}</span>
          <span><strong>{run.run_id}</strong><small>{run.model ?? 'model pending'}</small></span><time>{formatClock(run.started_at ?? run.completed_at)}</time>
        </button>) : <p>No run is loaded. Start a chat run to create an observable trace.</p>}
      </aside>
      <section className="trace-inspector" aria-live="polite">
        {detail ? <>
          <header className="trace-summary"><div><span>{detail.status}</span><strong>{detail.run_id}</strong><small>{detail.model ?? 'Model not recorded'}</small></div><dl><div><dt>Events</dt><dd>{detail.events.length}</dd></div><div><dt>Tools</dt><dd>{toolCount}</dd></div><div><dt>Stops / failures</dt><dd>{failureCount}</dd></div><div><dt>Latency</dt><dd>{detail.latency_ms ? `${detail.latency_ms} ms` : '—'}</dd></div></dl></header>
          <label className="trace-search"><Search size={15} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Filter event type or public label" />{loading ? <RefreshCw className="spin" size={14} /> : null}</label>
          {error ? <div className="trace-notice" role="status">{error}</div> : null}
          <ol className="trace-events">{events.map((event, index) => <TraceEventRow event={event} index={index} key={event.event_id} />)}</ol>
          {!events.length ? <div className="trace-empty">No public event matches this filter.</div> : null}
        </> : <div className="trace-empty"><Activity size={22} />Choose a run to replay its public lifecycle.</div>}
      </section>
    </div>
  </main>;
}

function TraceEventRow({ event, index }: { event: RunEvent; index: number }) {
  const payload = event.payload && Object.keys(event.payload).length ? JSON.stringify(event.payload, null, 2) : '';
  return <li>
    <span className="trace-sequence">{String(index + 1).padStart(2, '0')}</span>
    <span className="trace-rail" aria-hidden="true"><i /></span>
    <article><header><strong>{event.event_type}</strong><time><Clock3 size={12} />{formatClock(event.created_at)}</time></header><p>{event.message}</p>{payload ? <details><summary>Safe payload · {Object.keys(event.payload ?? {}).length} fields</summary><pre>{payload}</pre></details> : null}</article>
  </li>;
}

function formatClock(value?: string | null) {
  if (!value) return '—';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? '—' : date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' });
}
