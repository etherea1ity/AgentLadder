import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import { ApiError, api } from '../api/client';
import { TeamWorkspace } from './TeamWorkspace';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, api: { getTeamState: vi.fn(), createTeammate: vi.fn(), spawnSubagent: vi.fn(), sendTeamMessage: vi.fn(), stopTeamAgent: vi.fn() } };
});

const empty = { schema_version: 'klara.team-state.v1' as const, team: { tenant_id: 't', owner_id: 'o', team_id: 'default-team' }, agents: [], root_inbox: [], mailbox_counts: {}, worktrees: [] };

describe('TeamWorkspace', () => {
  beforeEach(() => {
    vi.mocked(api.getTeamState).mockResolvedValue(empty);
    vi.mocked(api.createTeammate).mockReset();
    vi.mocked(api.spawnSubagent).mockReset();
  });

  it('fails closed and routes an exact delegation approval to Permissions', async () => {
    const openPermissions = vi.fn();
    vi.mocked(api.createTeammate).mockRejectedValue(new ApiError(409, JSON.stringify({ detail: { code: 'permission_approval_required' } })));
    render(<TeamWorkspace onBackToChat={() => undefined} onOpenPermissions={openPermissions} />);
    await screen.findByText('No delegated agents yet. Authority is always requested before creation.');
    fireEvent.click(screen.getByRole('button', { name: 'Add teammate' }));
    await screen.findByText(/Delegation is blocked/);
    fireEvent.click(screen.getByRole('button', { name: 'Review permission' }));
    expect(openPermissions).toHaveBeenCalledOnce();
  });

  it('creates a one-shot task and renders returned summary state', async () => {
    const agent = { agent_id: 'agent-1', scope: empty.team, name: 'Evidence check', role: 'Check the cited source', kind: 'one_shot' as const, status: 'completed' as const, capability_names: ['web_fetch'], summary: 'The source supports the claim.', created_at: '2026-01-01T00:00:00Z', updated_at: '2026-01-01T00:01:00Z' };
    vi.mocked(api.spawnSubagent).mockResolvedValue({ agent });
    vi.mocked(api.getTeamState).mockResolvedValueOnce(empty).mockResolvedValueOnce({ ...empty, agents: [agent] });
    render(<TeamWorkspace onBackToChat={() => undefined} onOpenPermissions={() => undefined} />);
    await screen.findByText('No delegated agents yet. Authority is always requested before creation.');
    fireEvent.click(screen.getByRole('button', { name: 'One-shot agent' }));
    fireEvent.change(screen.getByLabelText('Name or task'), { target: { value: 'Evidence check' } });
    fireEvent.change(screen.getByLabelText('Isolated instructions'), { target: { value: 'Check the cited source' } });
    fireEvent.click(screen.getByRole('button', { name: 'Delegate task' }));
    await waitFor(() => expect(api.spawnSubagent).toHaveBeenCalledWith(expect.objectContaining({ title: 'Evidence check' })));
    expect(await screen.findByText('The source supports the claim.')).toBeInTheDocument();
  });
});
