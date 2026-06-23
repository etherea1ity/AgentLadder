import type { Message, ModelOption, Run, RunEvent, Session } from '../types/domain';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

type SessionDetail = { session: Session; messages: Message[]; runs: Omit<Run, 'events'>[]; events?: RunEvent[] };
type CreateRunResponse = { run_id: string; session_id: string; user_message_id: string; assistant_message_id: string; status: Run['status']; events_url: string };
type RunDetail = { run: Omit<Run, 'events'>; events: RunEvent[]; trace: Record<string, unknown> | null };
export type RunEventSubscription = { runId: string; close: () => void };

export class ApiError extends Error {
  status: number;
  body: string;
  code?: string;

  constructor(status: number, body: string) {
    const parsed = parseErrorBody(body);
    super(parsed.message || `${status} ${body}`);
    this.name = 'ApiError';
    this.status = status;
    this.body = body;
    this.code = parsed.code;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json() as Promise<T>;
}

export const api = {
  createSession: (signal?: AbortSignal) => request<Session>('/api/sessions', { method: 'POST', body: '{}', signal }),
  listSessions: (signal?: AbortSignal) => request<{ sessions: Session[] }>('/api/sessions', { signal }),
  getSession: (id: string, signal?: AbortSignal) => request<SessionDetail>(`/api/sessions/${id}`, { signal }),
  renameSession: (id: string, title: string, signal?: AbortSignal) => request<Session>(`/api/sessions/${id}`, { method: 'PATCH', body: JSON.stringify({ title }), signal }),
  deleteSession: (id: string, signal?: AbortSignal) => request<{ session_id: string; deleted: boolean; deleted_at: string }>(`/api/sessions/${id}`, { method: 'DELETE', signal }),
  listModels: (signal?: AbortSignal) => request<{ default_model: string; models: ModelOption[] }>('/api/models', { signal }),
  createRun: (session_id: string, question: string, model?: string | null, signal?: AbortSignal) => request<CreateRunResponse>('/api/runs', { method: 'POST', body: JSON.stringify({ session_id, question, model: model || undefined }), signal }),
  getRun: (id: string, signal?: AbortSignal) => request<RunDetail>(`/api/runs/${id}`, { signal }),
  cancelRun: (id: string, signal?: AbortSignal) => request<{ run_id: string; status: Run['status'] }>(`/api/runs/${id}/cancel`, { method: 'POST', body: '{}', signal }),
  subscribeRunEvents(runId: string, onEvent: (event: RunEvent) => void, onClose?: () => void) {
    const source = new EventSource(`${API_BASE}/api/runs/${runId}/events/stream`);
    const eventTypes: RunEvent['event_type'][] = [
      'run_created',
      'thinking_started',
      'thinking_summary_started',
      'thinking_preamble_started',
      'thinking_preamble_delta',
      'thinking_preamble_completed',
      'thinking_preamble_failed',
      'thinking_summary_delta',
      'thinking_summary_completed',
      'provider_reasoning_delta',
      'provider_reasoning_completed',
      'activity_fact_recorded',
      'narrator_started',
      'narrator_completed',
      'narrator_failed',
      'narrator_rejected',
      'llm_call_started',
      'answer_streaming_started',
      'answer_delta',
      'llm_call_completed',
      'tool_call_started',
      'tool_call_completed',
      'tool_call_failed',
      'policy_stop',
      'hook_placement_started',
      'hook_placement_completed',
      'workstream_note',
      'run_completed',
      'run_failed',
      'run_cancelled',
      'module_started',
      'module_completed',
      'module_failed',
      'trace_saved'
    ];
    eventTypes.forEach((type) => {
      source.addEventListener(type, (message) => onEvent(JSON.parse((message as MessageEvent).data) as RunEvent));
    });
    source.onerror = () => {
      source.close();
      onClose?.();
    };
    return { runId, close: () => source.close() } satisfies RunEventSubscription;
  }
};

function parseErrorBody(body: string): { message: string; code?: string } {
  try {
    const value = JSON.parse(body) as { detail?: unknown; code?: string };
    if (typeof value.detail === 'string') return { message: value.detail, code: value.code ?? value.detail };
    if (value.detail && typeof value.detail === 'object') return { message: JSON.stringify(value.detail), code: value.code };
  } catch {
    // fall through to raw body
  }
  return { message: body };
}
