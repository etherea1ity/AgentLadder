import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { SchedulerTimeline } from './SchedulerTimeline';

const schedule = { schedule_id: 'schedule_1', scope: { tenant_id: 't', owner_id: 'u', agent_id: 'klara' }, title: 'Morning brief', task_description: 'Summarize', session_id: 'session_1', kind: 'daily', timezone: 'UTC', status: 'active', run_at: null, local_time: '09:00', weekdays: [], interval_seconds: null, misfire_policy: 'fire_once', misfire_grace_seconds: 300, overlap_policy: 'queue_one', next_run_at: '2026-08-14T01:00:00+00:00', last_scheduled_at: null, last_result: null, queued_overlap: false, created_at: '2026-08-13T00:00:00+00:00', updated_at: '2026-08-13T00:00:00+00:00' };
const emptyState = { schema_version: 'klara.scheduler-state.v1', schedules: [schedule], occurrences: [], notifications: [] };

afterEach(() => vi.restoreAllMocks());

it('renders real schedule state and pauses through the API', async () => {
  const fetchMock = vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(json(emptyState))
    .mockResolvedValueOnce(json({ sessions: [{ session_id: 'session_1', title: 'Research', created_at: '', updated_at: '', message_ids: [] }] }))
    .mockResolvedValueOnce(json({ schedule: { ...schedule, status: 'paused' } }))
    .mockResolvedValueOnce(json({ ...emptyState, schedules: [{ ...schedule, status: 'paused' }] }));
  render(<SchedulerTimeline onBackToChat={() => undefined} />);
  expect(await screen.findByText('Morning brief')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /pause/i }));
  await waitFor(() => expect(fetchMock.mock.calls[2][0]).toBe('/api/scheduler/schedule_1/pause'));
  expect(await screen.findByRole('button', { name: /resume/i })).toBeInTheDocument();
});

it('keeps an explicit truthful empty state', async () => {
  vi.spyOn(globalThis, 'fetch')
    .mockResolvedValueOnce(json({ ...emptyState, schedules: [] }))
    .mockResolvedValueOnce(json({ sessions: [] }));
  render(<SchedulerTimeline onBackToChat={() => undefined} />);
  expect(await screen.findByText(/No schedules yet/)).toBeInTheDocument();
});

function json(value: unknown) { return new Response(JSON.stringify(value), { status: 200, headers: { 'Content-Type': 'application/json' } }); }
