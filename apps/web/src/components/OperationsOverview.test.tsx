import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import { OperationsOverview } from './OperationsOverview';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, api: { ...actual.api, listTasks: vi.fn(), getSchedulerState: vi.fn(), getTeamState: vi.fn(), listSkills: vi.fn(), listMemories: vi.fn(), getMcpState: vi.fn(), listPermissions: vi.fn(), getEvaluationSummary: vi.fn() } };
});

describe('OperationsOverview', () => {
  afterEach(() => vi.clearAllMocks());

  it('aggregates only current API state and routes to a product surface', async () => {
    vi.mocked(api.listTasks).mockResolvedValue({ schema_version: 'klara.durable-task-list.v1', tasks: [], counts_by_state: {} });
    vi.mocked(api.getSchedulerState).mockResolvedValue({ schema_version: 'klara.scheduler-state.v1', schedules: [], occurrences: [], notifications: [] });
    vi.mocked(api.getTeamState).mockResolvedValue({ schema_version: 'klara.team-state.v1', team: { tenant_id: 't', owner_id: 'o', team_id: 'team' }, agents: [], root_inbox: [], mailbox_counts: {}, worktrees: [] });
    vi.mocked(api.listSkills).mockResolvedValue({ schema_version: 'klara.skills-catalog.v1', precedence: [], body_loading: 'on_demand', skills: [] });
    vi.mocked(api.listMemories).mockResolvedValue({ schema_version: 'klara.memory-list.v1', records: [], counts_by_kind: {} });
    vi.mocked(api.getMcpState).mockResolvedValue({ schema_version: 'klara.mcp-state.v1', servers: [], audit: [] });
    vi.mocked(api.listPermissions).mockResolvedValue({ schema_version: 'klara.permissions-state.v1', requests: [], grants: [], audit: [] });
    vi.mocked(api.getEvaluationSummary).mockResolvedValue({ available: true, status: 'passed', gate_kind: 'control', interpretation: 'safe', counts: {}, metrics: {}, checks: {}, split_hashes: {} });
    const navigate = vi.fn();

    render(<OperationsOverview onNavigate={navigate} />);

    expect(await screen.findByText('All visible systems quiet')).toBeInTheDocument();
    expect(screen.getByText('8/8')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: /Durable tasks/i }));
    expect(navigate).toHaveBeenCalledWith('tasks');
  });

  it('marks a rejected source unavailable without inventing a healthy value', async () => {
    vi.mocked(api.listTasks).mockRejectedValue(new Error('offline'));
    vi.mocked(api.getSchedulerState).mockRejectedValue(new Error('offline'));
    vi.mocked(api.getTeamState).mockRejectedValue(new Error('offline'));
    vi.mocked(api.listSkills).mockRejectedValue(new Error('offline'));
    vi.mocked(api.listMemories).mockRejectedValue(new Error('offline'));
    vi.mocked(api.getMcpState).mockRejectedValue(new Error('offline'));
    vi.mocked(api.listPermissions).mockRejectedValue(new Error('offline'));
    vi.mocked(api.getEvaluationSummary).mockRejectedValue(new Error('offline'));

    render(<OperationsOverview onNavigate={() => undefined} />);

    expect(await screen.findByText(/Partial state:/)).toBeInTheDocument();
    expect(screen.getAllByText('Unavailable')).toHaveLength(8);
  });
});
