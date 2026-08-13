import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowRight, Bot, Brain, CalendarClock, CheckCircle2, ClipboardList, Gauge, KeyRound, PlugZap, RefreshCw, ShieldAlert, Sparkles, Users } from 'lucide-react';
import { api } from '../api/client';
import type { EvaluationSummary, McpState, MemoryList, PermissionState, ProductWorkspace, SchedulerState, SkillsCatalog, TeamState, DurableTaskList } from '../types/domain';

type Snapshot = {
  tasks?: DurableTaskList;
  scheduler?: SchedulerState;
  team?: TeamState;
  skills?: SkillsCatalog;
  memory?: MemoryList;
  mcp?: McpState;
  permissions?: PermissionState;
  evaluation?: EvaluationSummary;
};

type Card = {
  id: ProductWorkspace;
  title: string;
  value: string;
  detail: string;
  state: 'ready' | 'attention' | 'quiet' | 'unavailable';
  icon: typeof Activity;
};

export function OperationsOverview({ onNavigate }: { onNavigate: (workspace: ProductWorkspace) => void }) {
  const [snapshot, setSnapshot] = useState<Snapshot>({});
  const [unavailable, setUnavailable] = useState<string[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshKey, setRefreshKey] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    const sources = [
      ['tasks', api.listTasks(controller.signal)],
      ['scheduler', api.getSchedulerState(controller.signal)],
      ['team', api.getTeamState(controller.signal)],
      ['skills', api.listSkills(controller.signal)],
      ['memory', api.listMemories(controller.signal)],
      ['mcp', api.getMcpState(controller.signal)],
      ['permissions', api.listPermissions(controller.signal)],
      ['evaluation', api.getEvaluationSummary(controller.signal)],
    ] as const;
    Promise.allSettled(sources.map(([, request]) => request)).then((results) => {
      if (controller.signal.aborted) return;
      const next: Snapshot = {};
      const failed: string[] = [];
      results.forEach((result, index) => {
        const key = sources[index][0] as keyof Snapshot;
        if (result.status === 'fulfilled') (next as Record<string, unknown>)[key] = result.value;
        else failed.push(key);
      });
      setSnapshot(next);
      setUnavailable(failed);
      setLoading(false);
    });
    return () => controller.abort();
  }, [refreshKey]);

  const cards = useMemo(() => buildCards(snapshot, unavailable), [snapshot, unavailable]);
  const attention = cards.filter((card) => card.state === 'attention').length;
  const reachable = cards.filter((card) => card.state !== 'unavailable').length;

  return (
    <main className="overview-page" aria-labelledby="overview-title">
      <header className="overview-hero">
        <div>
          <span className="overview-eyebrow"><Sparkles size={14} />Agent control plane</span>
          <h1 id="overview-title">Klara is observable.</h1>
          <p>One live view of work, authority, memory, delegation, integrations, and release evidence. Every number comes from the current API state.</p>
        </div>
        <button className="overview-refresh" onClick={() => setRefreshKey((value) => value + 1)} disabled={loading}>
          <RefreshCw className={loading ? 'spin' : ''} size={16} />{loading ? 'Reading state…' : 'Refresh state'}
        </button>
      </header>

      <section className="overview-pulse" aria-label="Agent runtime summary">
        <div className="overview-orbit" aria-hidden="true"><span /><span /><Bot size={24} /></div>
          <div><span>Runtime posture</span><strong>{loading ? 'Observing' : unavailable.length ? `${unavailable.length} source${unavailable.length === 1 ? '' : 's'} unavailable` : attention ? `${attention} item${attention === 1 ? '' : 's'} need attention` : 'All visible systems quiet'}</strong></div>
        <dl>
          <div><dt>Surfaces online</dt><dd>{loading ? '—' : `${reachable}/${cards.length}`}</dd></div>
          <div><dt>Authority</dt><dd>{snapshot.permissions?.requests.some((item) => item.status === 'pending') ? 'Approval waiting' : 'Fail closed'}</dd></div>
          <div><dt>Quality gate</dt><dd>{snapshot.evaluation?.available ? snapshot.evaluation.status : 'Not published'}</dd></div>
        </dl>
      </section>

      {unavailable.length ? <div className="overview-notice" role="status"><ShieldAlert size={16} />Partial state: {unavailable.join(', ')} could not be verified. No healthy value was inferred.</div> : null}

      <section className="overview-grid" aria-label="Agent product surfaces">
        {cards.map((card) => {
          const Icon = card.icon;
          return <button key={card.id} className={`overview-card is-${card.state}`} onClick={() => onNavigate(card.id)}>
            <span className="overview-card-icon"><Icon size={19} /></span>
            <span className="overview-card-copy"><small>{card.title}</small><strong>{loading ? 'Reading…' : card.value}</strong><span>{loading ? 'Waiting for current API state.' : card.detail}</span></span>
            <ArrowRight className="overview-card-arrow" size={16} />
          </button>;
        })}
      </section>

      <section className="overview-lanes" aria-label="Runtime flow">
        <header><span><Gauge size={16} />Guarded execution path</span><button onClick={() => onNavigate('traces')}>Open developer traces <ArrowRight size={14} /></button></header>
        <ol>
          <li><span>01</span><strong>Plan</strong><small>Visible todo state</small></li>
          <li><span>02</span><strong>Authorize</strong><small>Exact scoped decision</small></li>
          <li><span>03</span><strong>Execute</strong><small>Durable task or team</small></li>
          <li><span>04</span><strong>Observe</strong><small>Public event contract</small></li>
          <li><span>05</span><strong>Evaluate</strong><small>Frozen release evidence</small></li>
        </ol>
      </section>
    </main>
  );
}

function buildCards(snapshot: Snapshot, unavailable: string[]): Card[] {
  const missing = (key: string) => unavailable.includes(key);
  const pending = snapshot.permissions?.requests.filter((item) => item.status === 'pending').length ?? 0;
  const blocked = snapshot.tasks?.tasks.filter((item) => ['blocked', 'failed'].includes(item.state)).length ?? 0;
  const activeTasks = snapshot.tasks?.tasks.filter((item) => ['ready', 'running', 'waiting', 'paused'].includes(item.state)).length ?? 0;
  const activeSchedules = snapshot.scheduler?.schedules.filter((item) => item.status === 'active').length ?? 0;
  const runningAgents = snapshot.team?.agents.filter((item) => ['running', 'waiting'].includes(item.status)).length ?? 0;
  const connected = snapshot.mcp?.servers.filter((item) => item.connection.status === 'connected').length ?? 0;
  const memories = snapshot.memory?.records.filter((item) => item.status === 'active').length ?? 0;
  return [
    { id: 'tasks', title: 'Durable tasks', value: missing('tasks') ? 'Unavailable' : `${activeTasks} active`, detail: blocked ? `${blocked} blocked or failed` : `${snapshot.tasks?.tasks.length ?? 0} tasks recorded`, state: missing('tasks') ? 'unavailable' : blocked ? 'attention' : activeTasks ? 'ready' : 'quiet', icon: ClipboardList },
    { id: 'scheduler', title: 'Scheduler', value: missing('scheduler') ? 'Unavailable' : `${activeSchedules} active`, detail: `${snapshot.scheduler?.occurrences.length ?? 0} occurrences retained`, state: missing('scheduler') ? 'unavailable' : activeSchedules ? 'ready' : 'quiet', icon: CalendarClock },
    { id: 'team', title: 'Team & worktrees', value: missing('team') ? 'Unavailable' : `${runningAgents} running`, detail: `${snapshot.team?.agents.length ?? 0} agents · ${snapshot.team?.worktrees.length ?? 0} worktrees`, state: missing('team') ? 'unavailable' : runningAgents ? 'ready' : 'quiet', icon: Users },
    { id: 'permissions', title: 'Permissions', value: missing('permissions') ? 'Unavailable' : pending ? `${pending} waiting` : 'No requests', detail: `${snapshot.permissions?.grants.filter((item) => item.status === 'active').length ?? 0} active grants`, state: missing('permissions') ? 'unavailable' : pending ? 'attention' : 'quiet', icon: KeyRound },
    { id: 'memory', title: 'Long-term memory', value: missing('memory') ? 'Unavailable' : `${memories} active`, detail: 'Scoped, editable, and forgettable', state: missing('memory') ? 'unavailable' : memories ? 'ready' : 'quiet', icon: Brain },
    { id: 'skills', title: 'Skills runtime', value: missing('skills') ? 'Unavailable' : `${snapshot.skills?.skills.length ?? 0} available`, detail: 'Body loaded only after selection', state: missing('skills') ? 'unavailable' : snapshot.skills?.skills.length ? 'ready' : 'quiet', icon: CheckCircle2 },
    { id: 'integrations', title: 'MCP integrations', value: missing('mcp') ? 'Unavailable' : `${connected} connected`, detail: `${snapshot.mcp?.servers.length ?? 0} servers configured`, state: missing('mcp') ? 'unavailable' : snapshot.mcp?.servers.some((item) => ['error', 'degraded'].includes(item.connection.status)) ? 'attention' : connected ? 'ready' : 'quiet', icon: PlugZap },
    { id: 'evaluations', title: 'Evaluation gate', value: missing('evaluation') ? 'Unavailable' : snapshot.evaluation?.available ? snapshot.evaluation.status : 'Not run', detail: snapshot.evaluation?.gate_kind ?? 'No published aggregate', state: missing('evaluation') ? 'unavailable' : snapshot.evaluation?.status === 'failed' ? 'attention' : snapshot.evaluation?.status === 'passed' ? 'ready' : 'quiet', icon: Activity },
  ];
}
