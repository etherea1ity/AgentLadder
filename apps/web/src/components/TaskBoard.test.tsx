import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, expect, it, vi } from 'vitest';
import { TaskBoard } from './TaskBoard';

const fetchMock = vi.fn();
const now = '2026-08-13T12:00:00Z';
const task = {
  task_id: 'task_1', scope: { tenant_id: 't', owner_id: 'u', agent_id: 'klara' }, title: 'Build verified report', description: '', state: 'blocked', dependency_ids: [], parent_task_id: null,
  required_artifacts: ['report'], required_evidence: ['sources'], active_attempt_id: null, attempt_count: 1, max_attempts: 3, progress: 45, current_step: 'Await approval', block_reason: 'Permission required',
  lease_worker_id: null, lease_expires_at: null, heartbeat_at: now, checkpoint_sequence: 1, created_at: now, updated_at: now, completed_at: null, cancelled_at: null,
};
const detail = { schema_version: 'klara.durable-task-detail.v1', task, attempts: [{ attempt_id: 'a1', task_id: 'task_1', number: 1, worker_id: 'worker', outcome: 'blocked', started_at: now, ended_at: now }], artifacts: [], latest_checkpoint: { checkpoint_id: 'cp1', sequence: 1, summary: 'Saved', payload_sha256: 'a'.repeat(64), payload_field_count: 1 }, events: [{ event_id: 'e1', operation: 'blocked', from_state: 'running', to_state: 'blocked', occurred_at: now }] };

beforeEach(() => { fetchMock.mockReset(); vi.stubGlobal('fetch', fetchMock); });

it('shows real lifecycle state, detail, and resumes through API', async () => {
  fetchMock
    .mockResolvedValueOnce(json({ schema_version: 'klara.durable-task-list.v1', tasks: [task], counts_by_state: { blocked: 1 } }))
    .mockResolvedValueOnce(json(detail))
    .mockResolvedValueOnce(json({ task: { ...task, state: 'ready', block_reason: null } }))
    .mockResolvedValueOnce(json({ schema_version: 'klara.durable-task-list.v1', tasks: [{ ...task, state: 'ready', block_reason: null }], counts_by_state: { ready: 1 } }))
    .mockResolvedValueOnce(json({ ...detail, task: { ...task, state: 'ready', block_reason: null } }));
  render(<TaskBoard onBackToChat={() => undefined} />);
  expect(await screen.findByText('Build verified report')).toBeInTheDocument();
  fireEvent.click(screen.getByText('Build verified report'));
  expect(await screen.findByText('Immutable history')).toBeInTheDocument();
  fireEvent.click(screen.getByRole('button', { name: /Resume/ }));
  await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(5));
  expect(fetchMock.mock.calls[2][0]).toBe('/api/tasks/task_1/resume');
});

it('reports fail-closed loading error', async () => {
  fetchMock.mockRejectedValueOnce(new Error('offline'));
  render(<TaskBoard onBackToChat={() => undefined} />);
  expect(await screen.findByRole('alert')).toHaveTextContent('No lifecycle action was assumed successful');
});

function json(value: unknown) { return Promise.resolve({ ok: true, json: async () => value }); }
