import { useEffect, useMemo, useState } from 'react';
import { ArrowLeft, Ban, CheckCircle2, CirclePause, ClipboardList, Clock3, Link2, RefreshCw, RotateCcw } from 'lucide-react';
import { api } from '../api/client';
import type { DurableTask, DurableTaskDetail, DurableTaskList } from '../types/domain';

const EMPTY: DurableTaskList = { schema_version: 'klara.durable-task-list.v1', tasks: [], counts_by_state: {} };

export function TaskBoard({ onBackToChat }: { onBackToChat: () => void }) {
  const [state, setState] = useState<DurableTaskList>(EMPTY);
  const [detail, setDetail] = useState<DurableTaskDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const groups = useMemo(() => groupTasks(state.tasks), [state.tasks]);

  useEffect(() => {
    const controller = new AbortController();
    void refresh(controller.signal);
    return () => controller.abort();
  }, []);

  async function refresh(signal?: AbortSignal, preferredTaskId?: string) {
    setLoading(true);
    try {
      const next = await api.listTasks(signal);
      setState(next);
      const selected = preferredTaskId ?? detail?.task.task_id;
      if (selected && next.tasks.some((task) => task.task_id === selected)) setDetail(await api.getTask(selected, signal));
      else setDetail(null);
      setError('');
    } catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return;
      setError('Task state is unavailable. No lifecycle action was assumed successful.');
    } finally {
      setLoading(false);
    }
  }

  async function inspect(task: DurableTask) {
    setBusy(task.task_id);
    try { setDetail(await api.getTask(task.task_id)); setError(''); }
    catch { setError('Task detail could not be loaded.'); }
    finally { setBusy(null); }
  }

  async function transition(task: DurableTask, action: 'resume' | 'retry' | 'cancel') {
    setBusy(task.task_id);
    try {
      if (action === 'resume') await api.resumeTask(task.task_id);
      else if (action === 'retry') await api.retryTask(task.task_id);
      else await api.cancelTask(task.task_id);
      await refresh(undefined, task.task_id);
    } catch { setError(`Task ${action} was not verified.`); }
    finally { setBusy(null); }
  }

  return (
    <main className="task-page" aria-label="Durable task board">
      <header className="task-header">
        <button className="memory-back" onClick={onBackToChat}><ArrowLeft size={17} />Back to chat</button>
        <span className="memory-eyebrow"><ClipboardList size={14} />Crash-safe work</span>
        <h1>Tasks</h1>
        <p>Every run has durable ownership, attempts, leases, checkpoints, dependencies and artifacts. Completion is earned by the declared evidence contract.</p>
      </header>
      <section className="task-contract" aria-label="Task guarantees">
        <span><Clock3 size={16} />Leased execution</span><span><Link2 size={16} />Dependency lineage</span><span><CheckCircle2 size={16} />Artifact-gated completion</span>
        <button onClick={() => void refresh()} disabled={loading}><RefreshCw size={15} />Refresh</button>
      </section>
      {error ? <div className="memory-alert" role="alert">{error}</div> : null}
      {loading && !state.tasks.length ? <div className="memory-empty">Loading durable tasks…</div> : null}
      {!loading && !state.tasks.length ? <div className="memory-empty">No durable tasks yet. New chat runs appear here automatically.</div> : null}
      <div className="task-layout">
        <section className="task-columns" aria-label="Task lifecycle columns">
          {groups.map(([label, tasks]) => (
            <div className="task-column" key={label}>
              <header><h2>{label}</h2><span>{tasks.length}</span></header>
              {tasks.map((task) => (
                <article className={`task-card state-${task.state} ${detail?.task.task_id === task.task_id ? 'selected' : ''}`} key={task.task_id}>
                  <button className="task-card-main" disabled={busy === task.task_id} onClick={() => void inspect(task)}>
                    <span className="task-state">{task.state}</span><strong>{task.title}</strong>
                    <span className="task-progress"><i style={{ width: `${task.progress}%` }} />{task.progress}%</span>
                    <small>{task.current_step ?? `${task.attempt_count}/${task.max_attempts} attempts`}</small>
                  </button>
                  <footer>
                    {(task.state === 'paused' || task.state === 'blocked') ? <button onClick={() => void transition(task, 'resume')}><CirclePause size={13} />Resume</button> : null}
                    {task.state === 'failed' && task.attempt_count < task.max_attempts ? <button onClick={() => void transition(task, 'retry')}><RotateCcw size={13} />Retry</button> : null}
                    {!['completed', 'cancelled'].includes(task.state) ? <button className="danger" onClick={() => void transition(task, 'cancel')}><Ban size={13} />Cancel</button> : null}
                  </footer>
                </article>
              ))}
            </div>
          ))}
        </section>
        {detail ? <TaskInspector detail={detail} onClose={() => setDetail(null)} /> : null}
      </div>
    </main>
  );
}

function TaskInspector({ detail, onClose }: { detail: DurableTaskDetail; onClose: () => void }) {
  return <aside className="task-inspector" aria-label="Task detail">
    <header><div><span className="task-state">{detail.task.state}</span><h2>{detail.task.title}</h2></div><button onClick={onClose}>Close</button></header>
    <dl><div><dt>Owner</dt><dd>{detail.task.scope.owner_id}</dd></div><div><dt>Attempts</dt><dd>{detail.task.attempt_count}/{detail.task.max_attempts}</dd></div><div><dt>Checkpoints</dt><dd>{detail.task.checkpoint_sequence}</dd></div><div><dt>Dependencies</dt><dd>{detail.task.dependency_ids.length}</dd></div></dl>
    {detail.task.block_reason ? <p className="task-block-reason">Blocked: {detail.task.block_reason}</p> : null}
    <section><h3>Attempts</h3>{detail.attempts.length ? detail.attempts.map((item) => <p key={item.attempt_id}><strong>#{item.number} · {item.outcome}</strong><span>{item.worker_id}</span></p>) : <small>No worker has claimed this task.</small>}</section>
    <section><h3>Artifacts</h3>{detail.artifacts.length ? detail.artifacts.map((item) => <p key={item.artifact_id}><strong>{item.name}{item.is_evidence ? ' · evidence' : ''}</strong><span>{item.uri}</span></p>) : <small>No artifact is recorded.</small>}</section>
    <section><h3>Immutable history</h3>{detail.events.slice(-8).reverse().map((item) => <p key={item.event_id}><strong>{item.operation.replace(/_/g, ' ')}</strong><span>{new Date(item.occurred_at).toLocaleString()}</span></p>)}</section>
  </aside>;
}

function groupTasks(tasks: DurableTask[]): [string, DurableTask[]][] {
  const definitions: [string, string[]][] = [['Active', ['running', 'ready']], ['Waiting', ['waiting', 'paused', 'blocked']], ['Finished', ['completed', 'failed', 'cancelled']]];
  return definitions.map(([label, states]) => [label, tasks.filter((task) => states.includes(task.state))]);
}
