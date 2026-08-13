import { useEffect, useMemo, useState } from 'react';
import { Activity, ArrowLeft, Cable, CircleOff, ExternalLink, PlugZap, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react';
import { api, ApiError } from '../api/client';
import type { McpServerState, McpState, McpTransportKind } from '../types/domain';

const EMPTY: McpState = { schema_version: 'klara.mcp-state.v1', servers: [], audit: [] };

export function McpIntegrations({ onBackToChat, onOpenPermissions }: { onBackToChat: () => void; onOpenPermissions: () => void }) {
  const [state, setState] = useState<McpState>(EMPTY);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [approvalQueued, setApprovalQueued] = useState(false);
  const [name, setName] = useState('');
  const [transport, setTransport] = useState<McpTransportKind>('stdio');
  const [command, setCommand] = useState('');
  const [args, setArgs] = useState('');
  const [endpoint, setEndpoint] = useState('');
  const [credentialRef, setCredentialRef] = useState('');
  const connected = useMemo(() => state.servers.filter((item) => item.connection.status === 'connected').length, [state.servers]);

  useEffect(() => {
    const controller = new AbortController();
    refresh(controller.signal).finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  async function refresh(signal?: AbortSignal, preserveError = false) {
    try { setState(await api.getMcpState(signal)); if (!preserveError) setError(''); }
    catch (caught) {
      if (caught instanceof DOMException && caught.name === 'AbortError') return;
      setError('Integration state is unavailable. External tools remain unavailable.');
    }
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    setBusy('create'); setApprovalQueued(false);
    try {
      await api.createMcpServer({
        name: name.trim(), transport,
        command: transport === 'stdio' ? command.trim() : undefined,
        args: transport === 'stdio' ? args.split('\n').map((item) => item.trim()).filter(Boolean) : [],
        endpoint: transport === 'streamable_http' ? endpoint.trim() : undefined,
        credential_ref: transport === 'streamable_http' && credentialRef.trim() ? credentialRef.trim() : undefined,
      });
      setName(''); setCommand(''); setArgs(''); setEndpoint(''); setCredentialRef('');
      await refresh();
    } catch (caught) { setError(friendlyMcpError(caught, 'The integration was not saved.')); }
    finally { setBusy(null); }
  }

  async function transition(server: McpServerState, action: 'connect' | 'reconnect' | 'disconnect' | 'ping' | 'delete') {
    setBusy(server.config.server_id); setApprovalQueued(false); setError('');
    try {
      if (action === 'delete') await api.deleteMcpServer(server.config.server_id);
      else await api.transitionMcpServer(server.config.server_id, action);
      await refresh();
    } catch (caught) {
      if (caught instanceof ApiError && caught.status === 403) {
        setApprovalQueued(true);
        setError('This exact MCP action is waiting for your approval. Nothing was executed.');
      } else setError(friendlyMcpError(caught, `The ${action} action was not verified.`));
      await refresh(undefined, true);
    } finally { setBusy(null); }
  }

  return <main className="mcp-page" aria-label="MCP integrations">
    <header className="mcp-header"><div><button onClick={onBackToChat}><ArrowLeft size={15} />Back to chat</button><span><PlugZap size={14} />Chapter 17 · External tools</span><h1>Integrations</h1><p>Connect MCP servers without turning their output—or their credentials—into trusted instructions.</p></div><aside><strong>{connected}</strong><span>connected</span><small>Protocol 2025-11-25</small></aside></header>
    <section className="mcp-contract" aria-label="MCP safety guarantees"><span><ShieldCheck size={15} />Exact permission per action</span><span><CircleOff size={15} />No secret values stored</span><span><Activity size={15} />Bounded, audited output</span><button onClick={() => void refresh()}><RefreshCw size={14} />Refresh</button></section>
    {error ? <div className="mcp-alert" role="alert"><span>{error}</span>{approvalQueued ? <button onClick={onOpenPermissions}>Open permissions <ExternalLink size={13} /></button> : null}</div> : null}
    <div className="mcp-grid">
      <form className="mcp-composer" onSubmit={create}>
        <div><Cable size={16} /><strong>Add a server</strong></div>
        <label>Name<input required value={name} onChange={(event) => setName(event.target.value)} placeholder="Research tools" /></label>
        <fieldset><legend>Transport</legend><div className="mcp-tabs"><button type="button" aria-pressed={transport === 'stdio'} onClick={() => setTransport('stdio')}>Local stdio</button><button type="button" aria-pressed={transport === 'streamable_http'} onClick={() => setTransport('streamable_http')}>Streamable HTTP</button></div></fieldset>
        {transport === 'stdio' ? <><label>Command<input required value={command} onChange={(event) => setCommand(event.target.value)} placeholder="python" /></label><label>Arguments, one per line<textarea value={args} onChange={(event) => setArgs(event.target.value)} placeholder="path/to/server.py" /></label><p>Secrets must be supplied through named environment references, never command arguments.</p></> : <><label>Endpoint<input required type="url" value={endpoint} onChange={(event) => setEndpoint(event.target.value)} placeholder="https://mcp.example.com/mcp" /></label><label>Credential environment name<input value={credentialRef} onChange={(event) => setCredentialRef(event.target.value)} placeholder="MCP_SERVER_TOKEN" /></label><p>Only the environment variable name is persisted. Its value stays outside Klara's database.</p></>}
        <button className="primary" disabled={busy === 'create'}>{busy === 'create' ? 'Saving…' : 'Save integration'}</button>
      </form>
      <section className="mcp-servers" aria-label="Configured MCP servers"><header><div><span>Servers</span><h2>Capability catalog</h2></div><strong>{state.servers.length} configured</strong></header>
        {loading ? <p className="mcp-empty">Loading integrations…</p> : null}
        {!loading && !state.servers.length ? <p className="mcp-empty">No MCP servers configured. Add one to inspect its negotiated capabilities.</p> : null}
        {state.servers.map((server) => <ServerCard key={server.config.server_id} server={server} busy={busy === server.config.server_id} onAction={transition} />)}
      </section>
      <aside className="mcp-audit" aria-label="MCP audit trail"><header><Activity size={15} /><strong>Recent activity</strong></header>{state.audit.length ? state.audit.slice(0, 12).map((event) => <article key={event.event_id}><i className={event.outcome} /><span><strong>{event.operation.replace(/_/g, ' ')}</strong><small>{event.outcome}{event.duration_ms != null ? ` · ${event.duration_ms} ms` : ''}</small></span><time>{new Date(event.occurred_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></article>) : <p>No external action has run.</p>}</aside>
    </div>
  </main>;
}

function ServerCard({ server, busy, onAction }: { server: McpServerState; busy: boolean; onAction: (server: McpServerState, action: 'connect' | 'reconnect' | 'disconnect' | 'ping' | 'delete') => void }) {
  const catalog = server.connection.catalog;
  return <article className={`mcp-server status-${server.connection.status}`}><header><i /><div><strong>{server.config.name}</strong><small>{server.config.transport === 'stdio' ? server.config.command : server.config.endpoint}</small></div><span>{server.connection.status}</span></header>
    {server.connection.last_error ? <p className="mcp-server-error">{server.connection.last_error}</p> : null}
    {catalog ? <div className="mcp-catalog"><p><b>{catalog.server_name}</b><span>v{catalog.server_version} · {catalog.protocol_version}</span></p><Catalog title="Tools" items={catalog.tools.map((item) => item.name ?? 'unnamed')} /><Catalog title="Resources" items={catalog.resources.map((item) => item.name ?? item.uri ?? 'unnamed')} /><Catalog title="Prompts" items={catalog.prompts.map((item) => item.name ?? 'unnamed')} /></div> : <p className="mcp-no-catalog">Connect to negotiate a read-only capability catalog.</p>}
    <footer>{server.connection.status === 'connected' ? <><button disabled={busy} onClick={() => onAction(server, 'ping')}>Ping</button><button disabled={busy} onClick={() => onAction(server, 'reconnect')}>Reconnect</button><button disabled={busy} onClick={() => onAction(server, 'disconnect')}>Disconnect</button></> : <button disabled={busy} onClick={() => onAction(server, 'connect')}>Connect</button>}<button className="danger" disabled={busy} aria-label={`Delete ${server.config.name}`} onClick={() => onAction(server, 'delete')}><Trash2 size={13} /></button></footer>
  </article>;
}

function Catalog({ title, items }: { title: string; items: string[] }) { return <section><span>{title}</span><div>{items.length ? items.map((item) => <code key={item}>{item}</code>) : <small>None</small>}</div></section>; }
function friendlyMcpError(caught: unknown, fallback: string) { return caught instanceof ApiError && caught.message ? `${fallback} ${caught.message}` : fallback; }
