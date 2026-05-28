import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { ThinkingInlineBar } from './ThinkingInlineBar';
import type { Run } from '../types/domain';

const baseRun: Run = {
  run_id: 'run_1',
  session_id: 'sess_1',
  user_message_id: 'msg_u',
  assistant_message_id: 'msg_a',
  status: 'queued',
  events: []
};

describe('ThinkingInlineBar', () => {
  it('renders safe status text and opens run margin', async () => {
    const onOpen = vi.fn();
    render(<ThinkingInlineBar run={{ ...baseRun, status: 'thinking' }} expanded={false} onOpen={onOpen} />);
    const button = screen.getByRole('button', { name: /open run trace/i });
    expect(button).toHaveTextContent('Thinking · Calling the language model...');
    expect(button).toHaveAttribute('aria-expanded', 'false');
    await userEvent.click(button);
    expect(onOpen).toHaveBeenCalledOnce();
  });

  it('renders completed state without raw chain of thought', () => {
    render(<ThinkingInlineBar run={{ ...baseRun, status: 'completed', latency_ms: 2400 }} expanded={true} onOpen={() => {}} />);
    expect(screen.getByRole('button', { name: /close run trace/i })).toHaveTextContent('Completed');
    expect(screen.queryByText(/view run/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/chain-of-thought|reasoning_content/i)).not.toBeInTheDocument();
  });
});
