import type { ClientContext, DurableTaskDetail, DurableTaskList, EvaluationSummary, MemoryKind, MemoryList, MemoryRecord, MemorySensitivity, Message, ModelOption, PermissionEffect, PermissionGrantRecord, PermissionState, Run, RunEvent, Session, SkillsCatalog, TodoPlan } from '../types/domain';

const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';

type SessionDetail = { session: Session; messages: Message[]; runs: Omit<Run, 'events'>[]; events?: RunEvent[]; todo_plan?: TodoPlan | null };
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
  const response = await fetch(resolveApiUrl(path), {
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    ...init
  });
  if (!response.ok) throw new ApiError(response.status, await response.text());
  return response.json() as Promise<T>;
}

function resolveApiUrl(path: string) {
  if (API_BASE) return `${API_BASE}${path}`;
  if (
    typeof window !== 'undefined' &&
    window.location.hostname === '127.0.0.1' &&
    window.location.port === '5123'
  ) {
    return `http://127.0.0.1:8011${path}`;
  }
  return path;
}

export const api = {
  createSession: (signal?: AbortSignal) => request<Session>('/api/sessions', { method: 'POST', body: '{}', signal }),
  listSessions: (signal?: AbortSignal) => request<{ sessions: Session[] }>('/api/sessions', { signal }),
  getSession: (id: string, signal?: AbortSignal) => request<SessionDetail>(`/api/sessions/${id}`, { signal }),
  renameSession: (id: string, title: string, signal?: AbortSignal) => request<Session>(`/api/sessions/${id}`, { method: 'PATCH', body: JSON.stringify({ title }), signal }),
  deleteSession: (id: string, signal?: AbortSignal) => request<{ session_id: string; deleted: boolean; deleted_at: string }>(`/api/sessions/${id}`, { method: 'DELETE', signal }),
  listModels: (signal?: AbortSignal) => request<{ default_model: string; models: ModelOption[] }>('/api/models', { signal }),
  getEvaluationSummary: (signal?: AbortSignal) => request<EvaluationSummary>('/api/evaluations/summary', { signal }),
  listSkills: (signal?: AbortSignal) => request<SkillsCatalog>('/api/skills', { signal }),
  listMemories: (signal?: AbortSignal) => request<MemoryList>('/api/memory', { signal }),
  searchMemories: (query: string, signal?: AbortSignal) => request<{ results: MemoryRecord[] }>(`/api/memory/search?q=${encodeURIComponent(query)}`, { signal }),
  createMemory: (content: string, kind: MemoryKind, sensitivity: MemorySensitivity = 'standard', signal?: AbortSignal) => request<MemoryRecord>('/api/memory', { method: 'POST', body: JSON.stringify({ content, kind, sensitivity }), signal }),
  updateMemory: (memoryId: string, content: string, signal?: AbortSignal) => request<MemoryRecord>(`/api/memory/${memoryId}`, { method: 'PATCH', body: JSON.stringify({ content }), signal }),
  forgetMemory: (memoryId: string, signal?: AbortSignal) => request<MemoryRecord>(`/api/memory/${memoryId}/forget`, { method: 'POST', body: '{}', signal }),
  deleteMemory: (memoryId: string, signal?: AbortSignal) => request<{ memory_id: string; deleted: boolean; deletion_verified: boolean }>(`/api/memory/${memoryId}`, { method: 'DELETE', signal }),
  listPermissions: (signal?: AbortSignal) => request<PermissionState>('/api/permissions', { signal }),
  decidePermission: (requestId: string, effect: PermissionEffect, expiresSeconds: number, signal?: AbortSignal) => request<PermissionGrantRecord>(`/api/permissions/requests/${requestId}/decision`, { method: 'POST', body: JSON.stringify({ effect, expires_seconds: expiresSeconds }), signal }),
  revokePermission: (grantId: string, signal?: AbortSignal) => request<PermissionGrantRecord>(`/api/permissions/grants/${grantId}/revoke`, { method: 'POST', body: '{}', signal }),
  listTasks: (signal?: AbortSignal) => request<DurableTaskList>('/api/tasks', { signal }),
  getTask: (taskId: string, signal?: AbortSignal) => request<DurableTaskDetail>(`/api/tasks/${taskId}`, { signal }),
  createTask: (title: string, description = '', signal?: AbortSignal) => request<{ task: DurableTaskDetail['task'] }>('/api/tasks', { method: 'POST', body: JSON.stringify({ title, description }), signal }),
  resumeTask: (taskId: string, signal?: AbortSignal) => request<{ task: DurableTaskDetail['task'] }>(`/api/tasks/${taskId}/resume`, { method: 'POST', body: '{}', signal }),
  retryTask: (taskId: string, signal?: AbortSignal) => request<{ task: DurableTaskDetail['task'] }>(`/api/tasks/${taskId}/retry`, { method: 'POST', body: '{}', signal }),
  cancelTask: (taskId: string, signal?: AbortSignal) => request<{ task: DurableTaskDetail['task'] }>(`/api/tasks/${taskId}/cancel`, { method: 'POST', body: '{}', signal }),
  createRun: (
    session_id: string,
    question: string,
    model?: string | null,
    thinking_enabled?: boolean | null,
    client_context?: ClientContext | null,
    signal?: AbortSignal,
  ) =>
    request<CreateRunResponse>('/api/runs', {
      method: 'POST',
      body: JSON.stringify({
        session_id,
        question,
        model: model || undefined,
        thinking_enabled: thinking_enabled ?? undefined,
        client_context: client_context ?? undefined,
      }),
      signal,
    }),
  getRun: (id: string, signal?: AbortSignal) => request<RunDetail>(`/api/runs/${id}`, { signal }),
  cancelRun: (id: string, signal?: AbortSignal) => request<{ run_id: string; status: Run['status'] }>(`/api/runs/${id}/cancel`, { method: 'POST', body: '{}', signal }),
  subscribeRunEvents(runId: string, onEvent: (event: RunEvent) => void, onClose?: () => void) {
    const source = new EventSource(resolveApiUrl(`/api/runs/${runId}/events/stream`));
    const eventTypes: RunEvent['event_type'][] = [
      'run_created',
      'run_profile_frozen',
      'todo_plan_updated',
      'thinking_started',
      'thinking_summary_started',
      'thinking_summary_completed',
      'provider_reasoning_delta',
      'provider_reasoning_completed',
      'assistant_activity_delta',
      'assistant_activity_completed',
      'activity_fact_recorded',
      'web_research.started',
      'web_research.state_updated',
      'web_research.no_viable_action',
      'web_search.started',
      'web_search.completed',
      'web_search.failed',
      'web_fetch.started',
      'web_fetch.completed',
      'web_fetch.failed',
      'evidence.candidate_recorded',
      'evidence.source_recorded',
      'evidence.readiness_evaluated',
      'evidence.answer_submitted',
      'evidence.submission_rejected',
      'evidence.verification_completed',
      'evidence.verification_failed',
      'final_answer.blocked',
      'final_answer.allowed',
      'final_answer.no_progress_stopped',
      'context.compacted',
      'context.assembled',
      'context.budget_evaluated',
      'context.prompt_recovery_applied',
      'provider.attempt_started',
      'provider.attempt_completed',
      'provider.attempt_failed',
      'provider.retry_scheduled',
      'model_route.candidate_started',
      'model_route.candidate_failed',
      'model_route.fallback_started',
      'model_route.candidate_completed',
      'model_call.failed',
      'prompt_recovery.started',
      'prompt_recovery.completed',
      'skills.catalog_ready',
      'skills.selected',
      'skills.loaded',
      'skills.load_rejected',
      'memory.review_completed',
      'memory.remembered',
      'memory.retrieved',
      'memory.updated',
      'memory.forgotten',
      'memory.deleted',
      'permission.requested',
      'permission.allowed',
      'permission.denied',
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
