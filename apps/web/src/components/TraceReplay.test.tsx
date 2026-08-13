import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { api } from '../api/client';
import type { Run } from '../types/domain';
import { TraceReplay } from './TraceReplay';

vi.mock('../api/client', async () => {
  const actual = await vi.importActual<typeof import('../api/client')>('../api/client');
  return { ...actual, api: { ...actual.api, getRun: vi.fn() } };
});

const run: Run = {
  run_id: 'run_public', session_id: 'session', user_message_id: 'user', assistant_message_id: 'assistant', status: 'completed', model: 'provider/model', started_at: '2026-08-14T00:00:00Z', latency_ms: 42,
  events: [{ event_id: 'event_1', run_id: 'run_public', event_type: 'tool_call_completed', message: 'Safe observation returned.', payload: { tool_result: { name: 'current_time', ok: true } }, created_at: '2026-08-14T00:00:01Z' }],
};

describe('TraceReplay', () => {
  it('renders ordered public events and filters them without exposing absent private text', async () => {
    vi.mocked(api.getRun).mockResolvedValue({ run: { ...run, events: undefined } as never, events: run.events, trace: { private_chain_of_thought: 'must-not-render' } });

    render(<TraceReplay runs={{ [run.run_id]: run }} onBackToChat={() => undefined} />);

    expect(await screen.findByText('Safe observation returned.')).toBeInTheDocument();
    expect(screen.queryByText('must-not-render')).not.toBeInTheDocument();
    await userEvent.type(screen.getByPlaceholderText('Filter event type or public label'), 'no match');
    expect(screen.getByText('No public event matches this filter.')).toBeInTheDocument();
  });
});
