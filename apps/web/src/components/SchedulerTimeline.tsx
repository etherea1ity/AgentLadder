import { useEffect, useMemo, useState } from 'react';
import { Ban, Bell, CalendarClock, CirclePause, Play, Plus, RotateCcw } from 'lucide-react';
import { api } from '../api/client';
import type { ScheduleKind, ScheduleOccurrence, ScheduleRecord, SchedulerState, Session } from '../types/domain';

const EMPTY: SchedulerState = { schema_version: 'klara.scheduler-state.v1', schedules: [], occurrences: [], notifications: [] };
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

export function SchedulerTimeline({ onBackToChat }: { onBackToChat: () => void }) {
  const [state, setState] = useState<SchedulerState>(EMPTY);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState('');
  const [title, setTitle] = useState('');
  const [description, setDescription] = useState('');
  const [kind, setKind] = useState<ScheduleKind>('once');
  const [runAt, setRunAt] = useState('');
  const [localTime, setLocalTime] = useState('09:00');
  const [intervalMinutes, setIntervalMinutes] = useState(60);
  const [weekdays, setWeekdays] = useState<number[]>([0]);
  const timezone = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';

  const occurrences = useMemo(() => selected ? state.occurrences.filter((item) => item.schedule_id === selected) : [], [selected, state.occurrences]);
  const unread = state.notifications.filter((item) => !item.read_at);

  useEffect(() => {
    const controller = new AbortController();
    Promise.all([api.getSchedulerState(controller.signal), api.listSessions(controller.signal)])
      .then(([scheduler, sessionList]) => { setState(scheduler); setSessions(sessionList.sessions); setSelected(scheduler.schedules[0]?.schedule_id ?? null); setError(''); })
      .catch(() => setError('Scheduler state is unavailable. No automation was assumed to have run.'))
      .finally(() => setLoading(false));
    return () => controller.abort();
  }, []);

  async function refresh(preferred?: string | null) {
    const next = await api.getSchedulerState();
    setState(next);
    setSelected((current) => preferred ?? current ?? next.schedules[0]?.schedule_id ?? null);
  }

  async function create(event: React.FormEvent) {
    event.preventDefault();
    if (!title.trim() || !sessions[0]) return;
    setBusy('create');
    try {
      const result = await api.createSchedule({
        title: title.trim(), task_description: description.trim(), session_id: sessions[0].session_id,
        kind, timezone, run_at: kind === 'once' ? new Date(runAt).toISOString() : undefined,
        local_time: kind === 'daily' || kind === 'weekly' ? localTime : undefined,
        weekdays: kind === 'weekly' ? weekdays : undefined,
        interval_seconds: kind === 'interval' ? intervalMinutes * 60 : undefined,
        misfire_policy: 'fire_once', overlap_policy: 'queue_one'
      });
      setTitle(''); setDescription(''); setError('');
      await refresh(result.schedule.schedule_id);
    } catch { setError('The schedule was not created. Check its time and recurrence fields.'); }
    finally { setBusy(null); }
  }

  async function transition(schedule: ScheduleRecord, action: 'pause' | 'resume' | 'run' | 'cancel') {
    setBusy(schedule.schedule_id);
    try {
      if (action === 'pause') await api.pauseSchedule(schedule.schedule_id);
      else if (action === 'resume') await api.resumeSchedule(schedule.schedule_id);
      else if (action === 'run') await api.runScheduleNow(schedule.schedule_id);
      else await api.cancelSchedule(schedule.schedule_id);
      setError(''); await refresh(schedule.schedule_id);
    } catch { setError(`Schedule ${action} was not verified.`); }
    finally { setBusy(null); }
  }

  async function retry(occurrence: ScheduleOccurrence) {
    setBusy(occurrence.occurrence_id);
    try { await api.retryScheduleOccurrence(occurrence.occurrence_id); await refresh(occurrence.schedule_id); }
    catch { setError('Occurrence retry was not verified.'); }
    finally { setBusy(null); }
  }

  async function markRead(notificationId: string) {
    setBusy(notificationId);
    try { await api.readScheduleNotification(notificationId); await refresh(); }
    catch { setError('Notification state was not updated.'); }
    finally { setBusy(null); }
  }

  return <main className="scheduler-page" aria-label="Background scheduler">
    <header className="scheduler-header"><div><button onClick={onBackToChat}>← Back to chat</button><span>Chapter 15 · Durable automation</span><h1>Scheduler</h1><p>Every occurrence becomes a leased durable task before Klara runs it.</p></div><div className="scheduler-clock"><CalendarClock size={20} /><strong>{timezone}</strong><span>{unread.length} unread updates</span></div></header>
    <section className="scheduler-contract" aria-label="Scheduler guarantees"><b>One occurrence ID</b><span>→</span><b>one durable task</b><span>→</span><b>one recoverable result</b><p>DST gaps move forward; repeated wall-clock hours run once. Overlap queues at most one deferred run.</p></section>
    {error ? <p className="scheduler-error" role="alert">{error}</p> : null}
    <div className="scheduler-grid">
      <form className="schedule-composer" onSubmit={create}>
        <div className="schedule-section-title"><Plus size={16} /><strong>New automation</strong></div>
        <label>Title<input value={title} onChange={(event) => setTitle(event.target.value)} placeholder="Morning evidence brief" /></label>
        <label>Instructions<textarea value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Summarize verified work and list unresolved claims." /></label>
        <label>Conversation<select aria-label="Conversation" disabled={!sessions.length}><option>{sessions[0]?.title ?? 'Create a chat first'}</option></select></label>
        <div className="schedule-two"><label>Recurrence<select aria-label="Recurrence" value={kind} onChange={(event) => setKind(event.target.value as ScheduleKind)}><option value="once">Once</option><option value="interval">Interval</option><option value="daily">Daily</option><option value="weekly">Weekly</option></select></label><label>Timezone<input value={timezone} readOnly /></label></div>
        {kind === 'once' ? <label>Run at<input aria-label="Run at" type="datetime-local" value={runAt} onChange={(event) => setRunAt(event.target.value)} required /></label> : null}
        {kind === 'interval' ? <label>Every (minutes)<input aria-label="Interval minutes" type="number" min={1} value={intervalMinutes} onChange={(event) => setIntervalMinutes(Number(event.target.value))} /></label> : null}
        {kind === 'daily' || kind === 'weekly' ? <label>Local time<input aria-label="Local time" type="time" value={localTime} onChange={(event) => setLocalTime(event.target.value)} /></label> : null}
        {kind === 'weekly' ? <fieldset><legend>Weekdays</legend><div className="weekday-row">{WEEKDAYS.map((day, index) => <button aria-pressed={weekdays.includes(index)} type="button" key={day} onClick={() => setWeekdays((items) => items.includes(index) ? items.filter((item) => item !== index) : [...items, index].sort())}>{day}</button>)}</div></fieldset> : null}
        <footer><small>Misfires fire once · overlaps queue one</small><button className="primary" disabled={busy === 'create' || !sessions.length}>{busy === 'create' ? 'Creating…' : 'Create schedule'}</button></footer>
      </form>
      <section className="schedule-list" aria-label="Schedule timeline">
        <header><div><span>Timeline</span><h2>Upcoming work</h2></div><strong>{state.schedules.filter((item) => item.status === 'active').length} active</strong></header>
        {loading ? <p className="scheduler-empty">Loading schedules…</p> : null}
        {!loading && !state.schedules.length ? <p className="scheduler-empty">No schedules yet. Create one to see its durable timeline.</p> : null}
        {state.schedules.map((schedule) => <article className={`schedule-card ${selected === schedule.schedule_id ? 'selected' : ''}`} key={schedule.schedule_id}>
          <button className="schedule-main" onClick={() => setSelected(schedule.schedule_id)}><span className={`schedule-dot ${schedule.status}`} /><span><strong>{schedule.title}</strong><small>{scheduleLabel(schedule)}</small></span><time>{schedule.next_run_at ? formatDate(schedule.next_run_at) : schedule.status}</time></button>
          <footer><span>{schedule.last_result ? `Last: ${schedule.last_result}` : 'No previous run'}{schedule.queued_overlap ? ' · one run queued' : ''}</span><div>{schedule.status === 'active' ? <button onClick={() => void transition(schedule, 'pause')}><CirclePause size={13} />Pause</button> : null}{schedule.status === 'paused' ? <button onClick={() => void transition(schedule, 'resume')}><Play size={13} />Resume</button> : null}{!['cancelled'].includes(schedule.status) ? <button onClick={() => void transition(schedule, 'run')}><Play size={13} />Run now</button> : null}{!['completed', 'cancelled'].includes(schedule.status) ? <button className="danger" onClick={() => void transition(schedule, 'cancel')}><Ban size={13} />Cancel</button> : null}</div></footer>
          {selected === schedule.schedule_id ? <div className="occurrence-strip" aria-label="Occurrence history">{occurrences.length ? occurrences.slice(0, 6).map((item) => <p key={item.occurrence_id}><i className={item.status} /><span><strong>{item.status.replace(/_/g, ' ')}</strong><small>{formatDate(item.scheduled_for)} · {item.trigger}</small></span>{item.status === 'failed' ? <button disabled={busy === item.occurrence_id} onClick={() => void retry(item)}><RotateCcw size={12} />Retry</button> : null}</p>) : <small>No occurrences yet.</small>}</div> : null}
        </article>)}
      </section>
      <aside className="scheduler-notifications" aria-label="Schedule notifications"><header><Bell size={16} /><strong>Results</strong></header>{state.notifications.length ? state.notifications.slice(0, 8).map((item) => <button className={item.read_at ? '' : 'unread'} key={item.notification_id} disabled={busy === item.notification_id} onClick={() => void markRead(item.notification_id)}><span>{item.message}</span><time>{formatDate(item.created_at)}</time></button>) : <p>No completed runs.</p>}</aside>
    </div>
  </main>;
}

function scheduleLabel(schedule: ScheduleRecord) {
  if (schedule.kind === 'once') return 'One time';
  if (schedule.kind === 'interval') return `Every ${Math.round((schedule.interval_seconds ?? 60) / 60)} min`;
  if (schedule.kind === 'daily') return `Daily at ${schedule.local_time}`;
  return `${schedule.weekdays.map((day) => WEEKDAYS[day]).join(', ')} at ${schedule.local_time}`;
}
function formatDate(value: string) { return new Date(value).toLocaleString([], { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' }); }
