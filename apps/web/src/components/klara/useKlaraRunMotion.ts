import type { KlaraCapabilityChip, KlaraRunEvent, KlaraRunEventKind, KlaraVisualPhase, Run, RunEvent, RunStatus } from '../../types/domain';

export type KlaraRunView = {
  phase: KlaraVisualPhase;
  label: string;
  detail: string;
  capabilities: KlaraCapabilityChip[];
  events: KlaraRunEvent[];
  current?: KlaraRunEvent;
  aggregate?: { answerChars: number; duration?: string; tokens?: string };
};

const terminalStatuses: RunStatus[] = ['completed', 'failed', 'cancelled'];

export function useKlaraRunMotion(run?: Run | null): KlaraRunView {
  if (!run) {
    return { phase: 'idle', label: 'Idle', detail: 'Klara is waiting for your next question.', capabilities: ['model'], events: [] };
  }
  const events = adaptRunEvents(run);
  const current = events[events.length - 1] ?? synthesizeCurrentEvent(run);
  const phase = phaseForRun(run, current?.kind);
  const label = labelForRun(run, current);
  const capabilities = chooseCapabilities(run, current);
  return {
    phase,
    label,
    detail: current?.publicDetail ?? detailForRun(run),
    capabilities,
    events,
    current,
    aggregate: {
      answerChars: answerChars(run),
      duration: formatLatency(run.latency_ms) || (run.live?.elapsed_ms ? formatLatency(run.live.elapsed_ms) : undefined),
      tokens: tokenSummary(run)
    }
  };
}

export function isKlaraRunActive(run?: Run | null) {
  return Boolean(run && !terminalStatuses.includes(run.status));
}

export function adaptRunEvents(run: Run): KlaraRunEvent[] {
  const sorted = [...(run.events ?? [])].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const adapted: KlaraRunEvent[] = [];
  let answerStarted = false;
  sorted.forEach((event) => {
    const mapped = mapBackendEvent(run, event, adapted.length + 1, answerStarted);
    if (event.event_type === 'answer_streaming_started' || event.event_type === 'answer_delta') answerStarted = true;
    if (mapped) adapted.push(mapped);
  });
  if (adapted.length === 0) adapted.push(synthesizeCurrentEvent(run));
  return adapted;
}

function mapBackendEvent(run: Run, event: RunEvent, seq: number, answerStarted: boolean): KlaraRunEvent | null {
  const base = {
    runId: run.run_id,
    eventId: event.event_id,
    seq,
    timestamp: event.created_at,
    safePayload: sanitizePayload(event.payload)
  };
  switch (event.event_type) {
    case 'run_created':
      return { ...base, kind: 'run.started', status: 'started', publicLabel: 'Received question', publicDetail: 'The run was created for this question.', concept: 'Run' };
    case 'thinking_started':
      return { ...base, kind: 'ask.created', status: 'completed', publicLabel: 'Created AskState', publicDetail: 'Klara structured the user question as AskState.', concept: 'AskState', capabilities: ['model'] };
    case 'llm_call_started':
      return { ...base, kind: 'model.call.started', status: 'started', publicLabel: 'Calling model...', publicDetail: `${String(event.payload?.model ?? run.model ?? 'Selected model')} is generating a response.`, concept: 'LLMClient', capabilities: ['model'] };
    case 'answer_streaming_started':
      return { ...base, kind: 'answer.started', status: 'started', publicLabel: 'Writing answer...', publicDetail: 'The model started streaming the public answer.', concept: 'AnswerState', capabilities: ['model'] };
    case 'answer_delta':
      if (answerStarted) return null;
      return { ...base, kind: 'answer.started', status: 'progress', publicLabel: 'Writing answer...', publicDetail: 'The model is streaming answer tokens.', concept: 'AnswerState', capabilities: ['model'] };
    case 'llm_call_completed':
      return { ...base, kind: 'model.call.completed', status: 'completed', publicLabel: 'Model call completed', publicDetail: 'The selected model finished returning the answer.', concept: 'LLMClient', capabilities: ['model'] };
    case 'tool_call_started': {
      const toolCall = event.payload?.tool_call as { name?: string } | undefined;
      const name = toolCall?.name ?? 'tool';
      return { ...base, kind: 'tool.call.started', status: 'started', publicLabel: `Using ${name}...`, publicDetail: `Klara called ${name} and is waiting for the observation.`, concept: 'ToolExecutor', capabilities: ['tool'] };
    }
    case 'tool_call_completed': {
      const toolResult = event.payload?.tool_result as { name?: string; ok?: boolean } | undefined;
      const name = toolResult?.name ?? 'tool';
      return { ...base, kind: 'tool.call.completed', status: toolResult?.ok === false ? 'failed' : 'completed', publicLabel: `${name} returned`, publicDetail: `The ${name} observation was added to the loop.`, concept: 'ToolResult', capabilities: ['tool'] };
    }
    case 'run_completed':
      return { ...base, kind: 'run.completed', status: 'completed', publicLabel: 'Completed', publicDetail: 'Klara completed the public answer.', concept: 'AnswerState', capabilities: ['model'] };
    case 'run_failed':
      return { ...base, kind: 'run.error', status: 'failed', publicLabel: 'Run failed', publicDetail: String(run.error?.message ?? 'The run failed.'), capabilities: ['model'] };
    case 'run_cancelled':
      return { ...base, kind: 'run.error', status: 'failed', publicLabel: 'Stopped', publicDetail: 'The run was stopped and partial output was preserved.', capabilities: ['model'] };
    case 'module_started':
    case 'module_completed':
    case 'module_failed': {
      const moduleResult = event.payload?.module_result as { module_id?: string; module_name?: string; input_summary?: string; output_summary?: string } | undefined;
      const kind = kindForModule(moduleResult?.module_id, event.event_type);
      return {
        ...base,
        kind,
        status: event.event_type === 'module_failed' ? 'failed' : event.event_type === 'module_completed' ? 'completed' : 'progress',
        publicLabel: moduleResult?.module_name ?? 'Running module',
        publicDetail: moduleResult?.output_summary || moduleResult?.input_summary || event.message,
        concept: moduleResult?.module_name,
        capabilities: capabilitiesForModule(moduleResult?.module_id),
      };
    }
    default:
      return null;
  }
}

function kindForModule(moduleId?: string, eventType?: string): KlaraRunEventKind {
  if (moduleId === 'intent_router') return 'route.decided';
  if (moduleId?.includes('retrieval')) return 'retrieval.started';
  if (moduleId === 'reranking') return 'verification.started';
  if (moduleId === 'context_builder') return 'source.selected';
  if (moduleId === 'klara_writer') return eventType === 'module_completed' ? 'answer.completed' : 'answer.started';
  return 'run.started';
}

function capabilitiesForModule(moduleId?: string): KlaraCapabilityChip[] {
  if (moduleId === 'intent_router') return ['model'];
  if (moduleId === 'dense_retrieval' || moduleId === 'bm25_retrieval' || moduleId === 'hybrid_retrieval') return ['rag'];
  if (moduleId === 'reranking') return ['verify'];
  if (moduleId === 'context_builder') return ['rag'];
  if (moduleId === 'klara_writer') return ['model'];
  return ['model'];
}

function synthesizeCurrentEvent(run: Run): KlaraRunEvent {
  const kindByStatus: Record<RunStatus, KlaraRunEventKind> = {
    queued: 'run.started',
    thinking: 'model.call.started',
    streaming: 'answer.started',
    completed: 'run.completed',
    failed: 'run.error',
    cancelled: 'run.error'
  };
  return {
    runId: run.run_id,
    eventId: `${run.run_id}_current_${run.status}`,
    seq: 1,
    timestamp: run.completed_at ?? run.started_at ?? new Date().toISOString(),
    kind: kindByStatus[run.status],
    status: run.status === 'failed' || run.status === 'cancelled' ? 'failed' : run.status === 'completed' ? 'completed' : 'progress',
    publicLabel: labelForStatus(run.status),
    publicDetail: detailForRun(run),
    concept: run.status === 'completed' ? 'AnswerState' : 'LLMClient',
    capabilities: ['model']
  };
}

function phaseForRun(run: Run, kind?: KlaraRunEventKind): KlaraVisualPhase {
  if (run.status === 'completed') return 'completed';
  if (run.status === 'failed' || run.status === 'cancelled') return 'error';
  if (kind === 'trace.saved') return 'saving';
  if (kind === 'tool.call.started') return 'acting';
  if (kind === 'retrieval.started' || kind === 'chunk.retrieved') return 'searching';
  if (kind === 'web.search.started' || kind === 'web.page.read') return 'searching_web';
  if (kind === 'verification.started') return 'checking';
  if (run.status === 'streaming' || kind === 'answer.started' || kind === 'answer.token') return 'writing';
  if (run.status === 'queued' || run.status === 'thinking' || kind === 'run.started' || kind === 'model.call.started') return 'thinking';
  return 'idle';
}

function labelForRun(run: Run, current?: KlaraRunEvent) {
  if (run.status === 'completed') return 'Completed';
  if (run.status === 'failed') return 'Failed';
  if (run.status === 'cancelled') return 'Stopped';
  return current?.publicLabel ?? labelForStatus(run.status);
}

function labelForStatus(status: RunStatus) {
  if (status === 'queued') return 'Preparing run...';
  if (status === 'thinking') return 'Calling model...';
  if (status === 'streaming') return 'Writing answer...';
  if (status === 'completed') return 'Completed';
  if (status === 'failed') return 'Failed';
  return 'Stopped';
}

function detailForRun(run: Run) {
  if (run.status === 'queued') return 'Klara is preparing the observable run.';
  if (run.status === 'thinking') return `${run.model ?? 'The selected model'} is being called.`;
  if (run.status === 'streaming') return 'The answer is streaming into the chat.';
  if (run.status === 'completed') return 'The answer is ready in the conversation.';
  if (run.status === 'failed') return run.error?.message ?? 'The run failed.';
  return 'The run was stopped and partial output was preserved.';
}

function chooseCapabilities(run: Run, current?: KlaraRunEvent): KlaraCapabilityChip[] {
  const fallback: KlaraCapabilityChip[] = ['model'];
  const chips: KlaraCapabilityChip[] = current?.capabilities?.length ? current.capabilities : fallback;
  return Array.from(new Set<KlaraCapabilityChip>(chips)).slice(0, 2);
}

function sanitizePayload(payload?: Record<string, unknown>) {
  if (!payload) return undefined;
  const safe: Record<string, unknown> = {};
  Object.entries(payload).forEach(([key, value]) => {
    if (/reasoning|chain|scratchpad|cot/i.test(key)) return;
    if (key === 'delta') return;
    safe[key] = value;
  });
  return Object.keys(safe).length ? safe : undefined;
}

function answerChars(run: Run) {
  return run.events.filter((event) => event.event_type === 'answer_delta').reduce((count, event) => count + String(event.payload?.delta ?? '').length, 0);
}

function tokenSummary(run: Run) {
  const source = run.token_source === 'estimated' ? ' estimated' : '';
  if (run.total_tokens != null) return `${run.total_tokens}${source}`;
  if (run.prompt_tokens != null || run.completion_tokens != null) return `${run.prompt_tokens ?? '—'} in / ${run.completion_tokens ?? '—'} out${source}`;
  return undefined;
}

export function formatLatency(ms?: number | null) {
  return ms ? (ms >= 1000 ? `${(ms / 1000).toFixed(1)}s` : `${ms}ms`) : '';
}
