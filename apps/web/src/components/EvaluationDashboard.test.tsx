import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { EvaluationDashboard } from './EvaluationDashboard';

describe('EvaluationDashboard', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('renders aggregate machine evidence without hidden cases', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      available: true,
      status: 'passed',
      gate_kind: 'contract_control_probe',
      interpretation: 'Control probe only.',
      scorer_version: 'klara.behavior-scorer.v1',
      evaluated_at: '2026-08-13T00:00:00Z',
      counts: { observations: 24 },
      metrics: { normal_task_success_rate: 1, critical_deterministic_rate: 1, reference_gap: 0, human_acceptability_rate: 1 },
      checks: { critical_deterministic: true, p0_zero: true },
      split_hashes: { development: 'a'.repeat(64) },
    }), { status: 200 })));

    render(<EvaluationDashboard onBackToChat={() => undefined} />);

    expect(await screen.findByText('Contract gate passed')).toBeInTheDocument();
    expect(screen.getByText('24 observations')).toBeInTheDocument();
    expect(screen.queryByText('hidden-case')).not.toBeInTheDocument();
  });

  it('returns to chat through the explicit action', async () => {
    const onBack = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ available: false, status: 'not_run', gate_kind: 'unknown', interpretation: '', counts: {}, metrics: {}, checks: {}, split_hashes: {} }), { status: 200 })));
    render(<EvaluationDashboard onBackToChat={onBack} />);

    await waitFor(() => expect(screen.getByText('No evaluation run has been published yet.')).toBeInTheDocument());
    await userEvent.click(screen.getByRole('button', { name: 'Back to chat' }));
    expect(onBack).toHaveBeenCalledOnce();
  });
});
