import type { Run } from '../types/domain';

type Props = {
  run: Run;
  expanded: boolean;
  onOpen: () => void;
};

export function ThinkingInlineBar({ run, expanded, onOpen }: Props) {
  const { label, meta } = getRunLabel(run);
  const terminal = run.status === 'completed' || run.status === 'failed' || run.status === 'cancelled';
  return (
    <button
      className={`thinking-line thinking-${run.status} ${expanded ? 'is-expanded' : ''}`}
      onClick={onOpen}
      aria-expanded={expanded}
      aria-controls="run-margin-panel"
      aria-label={expanded ? 'Close run trace for this answer' : 'Open run trace for this answer'}
    >
      <span className="thinking-glyph" aria-hidden="true">{terminal ? terminalGlyph(run.status) : ''}</span>
      <span className="thinking-copy">{label}</span>
      {meta ? <span className="thinking-meta">{meta}</span> : null}
    </button>
  );
}

export function getRunLabel(run: Run): { label: string; meta?: string } {
  if (run.status === 'failed') return { label: 'Failed · Open details' };
  if (run.status === 'cancelled') return { label: 'Stopped · Partial answer saved' };
  if (run.status === 'completed') return { label: 'Completed · View run', meta: formatLatency(run.latency_ms) };
  if (run.status === 'streaming') return { label: 'Writing · Streaming answer...' };
  if (run.status === 'queued') return { label: 'Queued · Preparing LLM call...' };
  return { label: 'Thinking · Calling the language model...' };
}

function terminalGlyph(status: Run['status']) {
  if (status === 'completed') return '✓';
  if (status === 'failed') return '!';
  return '□';
}

function formatLatency(latency?: number | null) {
  if (latency == null) return undefined;
  return latency >= 1000 ? `${(latency / 1000).toFixed(1)}s` : `${latency}ms`;
}
