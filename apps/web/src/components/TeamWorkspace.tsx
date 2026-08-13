import { useEffect, useState } from 'react';
import { ArrowLeft, Bot, Check, GitBranch, Inbox, MessageSquareText, Plus, RefreshCw, ShieldCheck, Square, Users } from 'lucide-react';
import { api, ApiError } from '../api/client';
import type { TeamAgent, TeamState, TeamWorktreeInspection } from '../types/domain';

const EMPTY: TeamState = { schema_version: 'klara.team-state.v1', team: { tenant_id: '', owner_id: '', team_id: '' }, agents: [], root_inbox: [], mailbox_counts: {}, worktrees: [] };

export function TeamWorkspace({ onBackToChat, onOpenPermissions }: { onBackToChat: () => void; onOpenPermissions: () => void }) {
  const [state, setState] = useState<TeamState>(EMPTY);
  const [mode, setMode] = useState<'teammate' | 'one-shot'>('teammate');
  const [name, setName] = useState('Research teammate');
  const [role, setRole] = useState('Verify evidence and summarize findings');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [permissionPending, setPermissionPending] = useState(false);
  const [inspection, setInspection] = useState<TeamWorktreeInspection | null>(null);
  const [inspecting, setInspecting] = useState('');

  useEffect(() => { const controller = new AbortController(); void refresh(controller.signal); return () => controller.abort(); }, []);

  async function refresh(signal?: AbortSignal) {
    try { setState(await api.getTeamState(signal)); setError(''); }
    catch (caught) { if (!(caught instanceof DOMException && caught.name === 'AbortError')) setError('Team state is unavailable. No delegated work was assumed successful.'); }
  }

  async function create() {
    if (!name.trim() || !role.trim()) return;
    setBusy('create'); setPermissionPending(false);
    try {
      if (mode === 'teammate') await api.createTeammate({ name: name.trim(), role: role.trim(), capability_names: ['web_search', 'web_fetch'] });
      else await api.spawnSubagent({ title: name.trim(), instructions: role.trim(), capability_names: ['web_search', 'web_fetch', 'evidence_submit'] });
      await refresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.code === 'permission_approval_required') { setPermissionPending(true); setError('Delegation is blocked until its exact authority is approved.'); }
      else setError('The new agent was not verified.');
    } finally { setBusy(''); }
  }

  async function stop(agent: TeamAgent) {
    setBusy(agent.agent_id);
    try { await api.stopTeamAgent(agent.agent_id); await refresh(); }
    catch { setError('Stop was not verified.'); }
    finally { setBusy(''); }
  }

  async function ping(agent: TeamAgent) {
    setBusy(agent.agent_id);
    try { await api.sendTeamMessage({ recipient_id: agent.agent_id, kind: 'question', body: 'Report current public progress and any blocker.' }); await refresh(); }
    catch { setError('Mailbox delivery was not verified.'); }
    finally { setBusy(''); }
  }

  async function inspectWorktree(worktreeId: string) {
    setInspecting(worktreeId);
    try { setInspection(await api.inspectTeamWorktree(worktreeId)); setError(''); }
    catch { setInspection(null); setError('The worktree diff state could not be verified.'); }
    finally { setInspecting(''); }
  }

  return <main className="team-page" aria-label="Team workspace">
    <header className="task-header">
      <button className="memory-back" onClick={onBackToChat}><ArrowLeft size={17} />Back to chat</button>
      <span className="memory-eyebrow"><Users size={14} />Bounded delegation</span>
      <h1>Team</h1>
      <p>Delegate clean task packets, communicate through durable mailboxes, and keep code changes isolated in permissioned worktrees.</p>
    </header>
    <section className="team-contract" aria-label="Team guarantees">
      <span><ShieldCheck size={16} />Exact authority</span><span><Inbox size={16} />Isolated mailboxes</span><span><GitBranch size={16} />Worktree boundaries</span>
      <button onClick={() => void refresh()}><RefreshCw size={15} />Refresh</button>
    </section>
    {error ? <div className="memory-alert" role="alert">{error}{permissionPending ? <button onClick={onOpenPermissions}>Review permission</button> : null}</div> : null}
    <section className="team-create-panel">
      <div className="team-mode" role="group" aria-label="Agent kind"><button className={mode === 'teammate' ? 'active' : ''} onClick={() => setMode('teammate')}><Users size={15} />Persistent teammate</button><button className={mode === 'one-shot' ? 'active' : ''} onClick={() => setMode('one-shot')}><Bot size={15} />One-shot agent</button></div>
      <label>Name or task<input value={name} onChange={(event) => setName(event.target.value)} maxLength={160} /></label>
      <label>{mode === 'teammate' ? 'Role' : 'Isolated instructions'}<textarea value={role} onChange={(event) => setRole(event.target.value)} rows={3} /></label>
      <button className="team-primary" disabled={busy === 'create'} onClick={() => void create()}><Plus size={16} />{busy === 'create' ? 'Checking authority…' : mode === 'teammate' ? 'Add teammate' : 'Delegate task'}</button>
    </section>
    <section className="team-grid" aria-label="Team members">
      {state.agents.length ? state.agents.map((agent) => <article className="team-card" key={agent.agent_id}>
        <header><span className={`team-avatar status-${agent.status}`}>{agent.kind === 'teammate' ? <Users size={19} /> : <Bot size={19} />}</span><div><strong>{agent.name}</strong><small>{agent.kind.replace('_', ' ')} · {agent.status}</small></div></header>
        <p>{agent.role}</p>
        <div className="team-chips">{agent.capability_names.map((item) => <span key={item}>{item}</span>)}{agent.child_task_id ? <span>task linked</span> : null}</div>
        {agent.summary ? <blockquote><Check size={14} />{agent.summary}</blockquote> : null}
        <footer><button disabled={busy === agent.agent_id || agent.status === 'stopped'} onClick={() => void ping(agent)}><MessageSquareText size={14} />Message</button>{!['completed', 'failed', 'stopped'].includes(agent.status) ? <button className="danger" disabled={busy === agent.agent_id} onClick={() => void stop(agent)}><Square size={13} />Stop</button> : null}</footer>
      </article>) : <div className="memory-empty">No delegated agents yet. Authority is always requested before creation.</div>}
    </section>
    <section className="team-lower-grid"><div><h2><Inbox size={17} />Parent inbox</h2>{state.root_inbox.length ? state.root_inbox.slice().reverse().map((message) => <p key={message.message_id}><strong>{message.kind.replace('_', ' ')}</strong><span>{message.body}</span></p>) : <small>No returned summaries or handoffs.</small>}</div><div><h2><GitBranch size={17} />Worktrees</h2>{state.worktrees.length ? state.worktrees.map((item) => <button className="worktree-row" key={item.worktree_id} onClick={() => void inspectWorktree(item.worktree_id)} disabled={inspecting === item.worktree_id}><strong>{item.branch_name}</strong><span>{inspecting === item.worktree_id ? 'Inspecting…' : `${item.status} · ${item.head_sha?.slice(0, 8) ?? 'no head'}`}</span></button>) : <small>No isolated code workspace has been created.</small>}</div></section>
    {inspection ? <section className="worktree-inspection" aria-label="Worktree inspection"><header><div><span>Read-only diff state</span><h2>{inspection.changed_file_count} changed · {inspection.conflict_count} conflicts</h2></div><strong>{inspection.ahead} ahead / {inspection.behind} behind</strong></header>{inspection.files.length ? <div>{inspection.files.map((file) => <p key={`${file.code}:${file.path}`} className={file.status === 'conflict' ? 'is-conflict' : ''}><span>{file.code}</span><strong>{file.path}</strong><small>{file.status}</small></p>)}</div> : <small>Clean worktree. No file content was read or rendered.</small>}</section> : null}
  </main>;
}
