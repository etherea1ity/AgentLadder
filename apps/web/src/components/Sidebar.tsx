import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, MessageCircle, MoreHorizontal, PanelLeftClose, PanelLeftOpen, Plus, Settings } from 'lucide-react';
import type { Session } from '../types/domain';

type Props = {
  sessions: Session[];
  activeSessionId: string | null;
  collapsed: boolean;
  deletingSessionIds?: Record<string, boolean>;
  renamingSessionIds?: Record<string, boolean>;
  onToggleCollapsed: () => void;
  onNewChat: () => void;
  onSelect: (id: string) => void;
  onRename: (id: string, title: string) => void;
  onDelete: (id: string) => void;
};

export function Sidebar({ sessions, activeSessionId, collapsed, deletingSessionIds = {}, renamingSessionIds = {}, onToggleCollapsed, onNewChat, onSelect, onRename, onDelete }: Props) {
  const today = sessions.filter((session) => isToday(session.updated_at));
  const earlier = sessions.filter((session) => !isToday(session.updated_at));
  return (
    <aside className={`sidebar ${collapsed ? 'is-collapsed' : ''}`} aria-label="Conversation sidebar">
      <button className="sidebar-toggle" onClick={onToggleCollapsed} aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}>
        {collapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
      </button>
      <div className="brand-row brand-row-image">
        <img className="navbar-brand-logo" src="/brand/klara/klara-lockup-light.png" alt="Klara" />
        <img className="navbar-brand-symbol" src="/brand/klara/klara-mark-light.png" alt="Klara" />
      </div>
      <div className="version-row sidebar-copy"><span>v0.3</span><span>Agentic RAG</span></div>
      <button className="new-chat" onClick={onNewChat} title="New Chat"><Plus size={18} /><span className="sidebar-copy">New Chat</span><kbd className="sidebar-copy">⌘N</kbd></button>
      <ConversationGroup title="Today" sessions={today} activeSessionId={activeSessionId} deletingSessionIds={deletingSessionIds} renamingSessionIds={renamingSessionIds} onSelect={onSelect} onRename={onRename} onDelete={onDelete} />
      <ConversationGroup title="Earlier" sessions={earlier} activeSessionId={activeSessionId} deletingSessionIds={deletingSessionIds} renamingSessionIds={renamingSessionIds} onSelect={onSelect} onRename={onRename} onDelete={onDelete} />
      <div className="sidebar-footer"><span className="avatar">K</span><Settings size={18} /></div>
    </aside>
  );
}

function ConversationGroup(props: { title: string; sessions: Session[]; activeSessionId: string | null; deletingSessionIds: Record<string, boolean>; renamingSessionIds: Record<string, boolean>; onSelect: (id: string) => void; onRename: (id: string, title: string) => void; onDelete: (id: string) => void }) {
  return (
    <section className="conversation-group">
      <h2 className="sidebar-copy">{props.title}</h2>
      {props.sessions.map((session) => <ConversationItem key={session.session_id} session={session} active={session.session_id === props.activeSessionId} deleting={Boolean(props.deletingSessionIds[session.session_id])} renaming={Boolean(props.renamingSessionIds[session.session_id])} onSelect={props.onSelect} onRename={props.onRename} onDelete={props.onDelete} />)}
    </section>
  );
}

function ConversationItem({ session, active, deleting, renaming, onSelect, onRename, onDelete }: { session: Session; active: boolean; deleting: boolean; renaming: boolean; onSelect: (id: string) => void; onRename: (id: string, title: string) => void; onDelete: (id: string) => void }) {
  const [mode, setMode] = useState<'menu' | 'rename' | 'delete'>('menu');
  const [draftTitle, setDraftTitle] = useState(session.title);
  const menuRef = useRef<HTMLDetailsElement | null>(null);

  useEffect(() => {
    const closeMenu = () => {
      const menu = menuRef.current;
      if (!menu?.open) return;
      menu.open = false;
      setMode('menu');
    };

    const onPointerDown = (event: PointerEvent) => {
      const menu = menuRef.current;
      if (!menu?.open) return;
      if (event.target instanceof Node && menu.contains(event.target)) return;
      closeMenu();
    };

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') closeMenu();
    };

    document.addEventListener('pointerdown', onPointerDown, true);
    document.addEventListener('keydown', onKeyDown);
    return () => {
      document.removeEventListener('pointerdown', onPointerDown, true);
      document.removeEventListener('keydown', onKeyDown);
    };
  }, []);

  return (
    <div className={`conversation-item ${active ? 'active' : ''}`}>
      <button onClick={() => onSelect(session.session_id)} title={session.title}>
        <MessageCircle className="chat-icon" size={16} />
        <span className="conversation-title sidebar-copy">{deleting ? 'Deleting...' : session.title}</span>
        <time className="sidebar-copy">{formatTime(session.updated_at)}</time>
      </button>
      <details ref={menuRef} className="more-menu sidebar-copy" onToggle={(event) => { if (!(event.currentTarget as HTMLDetailsElement).open) setMode('menu'); }}>
        <summary aria-label="Conversation actions">{deleting || renaming ? <LoaderCircle className="spin" size={16} /> : <MoreHorizontal size={16} />}</summary>
        <div className="menu-popover">
          {mode === 'menu' ? (
            <>
              <button disabled={deleting || renaming} onClick={() => { setDraftTitle(session.title); setMode('rename'); }}>Rename</button>
              <button disabled={deleting || renaming} className="danger" onClick={() => setMode('delete')}>Delete</button>
            </>
          ) : null}
          {mode === 'rename' ? (
            <form
              className="inline-form"
              onSubmit={(event) => {
                event.preventDefault();
                const title = draftTitle.trim();
                if (title) onRename(session.session_id, title);
                setMode('menu');
              }}
            >
              <label>Rename conversation</label>
              <input value={draftTitle} onChange={(event) => setDraftTitle(event.target.value)} autoFocus />
              <div className="popover-actions"><button type="button" onClick={() => setMode('menu')}>Cancel</button><button type="submit" disabled={renaming}>{renaming ? 'Saving...' : 'Save'}</button></div>
            </form>
          ) : null}
          {mode === 'delete' ? (
            <div className="delete-confirm">
              <strong>Delete this conversation?</strong>
              <p>This removes it from the sidebar and conversation view.</p>
              <div className="popover-actions"><button onClick={() => setMode('menu')}>Cancel</button><button className="danger" disabled={deleting} onClick={() => onDelete(session.session_id)}>{deleting ? 'Deleting...' : 'Delete'}</button></div>
            </div>
          ) : null}
        </div>
      </details>
    </div>
  );
}

function isToday(value: string) {
  return new Date(value).toDateString() === new Date().toDateString();
}
function formatTime(value: string) {
  const date = new Date(value);
  if (isToday(value)) return date.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
  const yesterday = new Date();
  yesterday.setDate(yesterday.getDate() - 1);
  if (date.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return date.toLocaleDateString([], { month: 'short', day: 'numeric' });
}
