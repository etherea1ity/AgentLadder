export type RunStatus = 'queued' | 'thinking' | 'streaming' | 'completed' | 'failed' | 'cancelled';
export type MessageStatus = 'idle' | 'running' | 'completed' | 'failed' | 'cancelled';
export type Role = 'user' | 'assistant';

export type Session = {
  session_id: string;
  title: string;
  created_at: string;
  updated_at: string;
  deleted_at?: string | null;
  message_ids: string[];
};

export type TodoStatus = 'pending' | 'in_progress' | 'completed';
export type TodoItem = { id: string; title: string; status: TodoStatus };
export type TodoPlan = {
  schema_version: 'klara.todo-plan.v1';
  session_id: string;
  version: number;
  items: TodoItem[];
  updated_at: string;
};

export type Message = {
  message_id: string;
  session_id: string;
  role: Role;
  content: string;
  run_id?: string | null;
  status?: MessageStatus;
  created_at: string;
  updated_at?: string | null;
  client_created_at?: string | null;
  client_timezone?: string | null;
  client_utc_offset_minutes?: number | null;
};

export type RunEventType =
  | 'run_created'
  | 'run_profile_frozen'
  | 'todo_plan_updated'
  | 'thinking_started'
  | 'thinking_summary_started'
  | 'thinking_summary_completed'
  | 'provider_reasoning_delta'
  | 'provider_reasoning_completed'
  | 'assistant_activity_delta'
  | 'assistant_activity_completed'
  | 'activity_fact_recorded'
  | 'web_research.started'
  | 'web_research.state_updated'
  | 'web_research.no_viable_action'
  | 'web_search.started'
  | 'web_search.completed'
  | 'web_search.failed'
  | 'web_fetch.started'
  | 'web_fetch.completed'
  | 'web_fetch.failed'
  | 'evidence.candidate_recorded'
  | 'evidence.source_recorded'
  | 'evidence.readiness_evaluated'
  | 'evidence.answer_submitted'
  | 'evidence.submission_rejected'
  | 'evidence.verification_completed'
  | 'evidence.verification_failed'
  | 'final_answer.blocked'
  | 'final_answer.allowed'
  | 'final_answer.no_progress_stopped'
  | 'context.compacted'
  | 'context.assembled'
  | 'context.budget_evaluated'
  | 'context.prompt_recovery_applied'
  | 'provider.attempt_started'
  | 'provider.attempt_completed'
  | 'provider.attempt_failed'
  | 'provider.retry_scheduled'
  | 'model_route.candidate_started'
  | 'model_route.candidate_failed'
  | 'model_route.fallback_started'
  | 'model_route.candidate_completed'
  | 'model_call.failed'
  | 'prompt_recovery.started'
  | 'prompt_recovery.completed'
  | 'skills.catalog_ready'
  | 'skills.selected'
  | 'skills.loaded'
  | 'skills.load_rejected'
  | 'memory.review_completed'
  | 'memory.remembered'
  | 'memory.retrieved'
  | 'memory.updated'
  | 'memory.forgotten'
  | 'memory.deleted'
  | 'permission.requested'
  | 'permission.allowed'
  | 'permission.denied'
  | 'llm_call_started'
  | 'answer_streaming_started'
  | 'answer_delta'
  | 'llm_call_completed'
  | 'tool_call_started'
  | 'tool_call_completed'
  | 'tool_call_failed'
  | 'policy_stop'
  | 'hook_placement_started'
  | 'hook_placement_completed'
  | 'run_completed'
  | 'run_failed'
  | 'run_cancelled'
  | 'module_started'
  | 'module_completed'
  | 'module_failed'
  | 'trace_saved';


export type ModuleStatus = 'pending' | 'running' | 'completed' | 'failed' | 'skipped';

export type ModuleResult = {
  module_id: string;
  module_name: string;
  status: ModuleStatus;
  started_at?: string | null;
  completed_at?: string | null;
  latency_ms?: number | null;
  input_summary: string;
  output_summary: string;
  input_payload?: Record<string, unknown>;
  output_payload?: Record<string, unknown>;
  error?: string | null;
};

export type RunEvent = {
  event_id: string;
  run_id: string;
  event_type: RunEventType;
  message: string;
  payload?: Record<string, unknown>;
  created_at: string;
};

export type ThinkingActivityStatus = 'running' | 'completed' | 'failed';
export type ThinkingActivityKind =
  | 'orientation'
  | 'evidence'
  | 'tool_activity'
  | 'composition'
  | 'finalization'
  | 'error';
export type ThinkingActivitySource =
  | 'provider_reasoning'
  | 'main_model_commentary'
  | 'runtime_action';

export type ThinkingActivityItem = {
  id: string;
  title: string;
  body: string;
  status: ThinkingActivityStatus;
  kind: ThinkingActivityKind;
  source: ThinkingActivitySource;
  sequence?: number;
  evidence_fact_ids?: string[];
  evidence_event_ids: string[];
  confidence?: number;
};

export type ActivityFact = {
  id: string;
  kind: string;
  status: 'started' | 'completed' | 'failed';
  source_event_type: RunEventType;
  evidence_event_ids: string[];
  tool?: Record<string, unknown>;
  llm?: Record<string, unknown>;
  web?: Record<string, unknown>;
  image?: Record<string, unknown>;
  request?: Record<string, unknown>;
  metrics?: Record<string, unknown>;
  observation_preview?: string;
  error_preview?: string;
  content_length?: number | null;
};

export type Run = {
  run_id: string;
  session_id: string;
  user_message_id: string;
  assistant_message_id: string;
  status: RunStatus;
  model?: string | null;
  started_at?: string | null;
  completed_at?: string | null;
  latency_ms?: number | null;
  prompt_tokens?: number | null;
  completion_tokens?: number | null;
  total_tokens?: number | null;
  token_source?: 'reported' | 'estimated' | 'unknown' | null;
  trace_saved?: boolean;
  thinking_enabled?: boolean | null;
  error?: { code?: string | null; message: string; stage?: string | null } | null;
  events: RunEvent[];
  live?: { elapsed_ms?: number; streamed_chars: number; current_label: string };
};

export type UIState = {
  activeSessionId: string | null;
  sidebarCollapsed: boolean;
  inputFocused: boolean;
  activeSseRunId: string | null;
};

export type ModelOption = {
  id: string;
  model: string;
  label: string;
  use_when?: string | null;
  capabilities?: string[];
  supports_thinking?: boolean;
  default_thinking?: boolean;
};

export type ClientContext = {
  timestamp: string;
  timezone?: string | null;
  utc_offset_minutes: number;
};

export type EvaluationSummary = {
  available: boolean;
  status: 'passed' | 'failed' | 'not_run';
  gate_kind: string;
  interpretation: string;
  scorer_version?: string | null;
  evaluated_at?: string | null;
  counts: Record<string, number>;
  metrics: Record<string, number>;
  checks: Record<string, boolean>;
  split_hashes: Record<string, string>;
};

export type SkillOption = {
  name: string;
  description: string;
  version: string;
  scope: 'built_in' | 'user' | 'project';
  source: string;
  sha256: string;
  tools: string[];
  permissions: string[];
  dependencies: string[];
  references: string[];
  shadowed_scopes: string[];
};

export type SkillsCatalog = {
  schema_version: 'klara.skills-catalog.v1';
  precedence: string[];
  body_loading: 'on_demand';
  skills: SkillOption[];
};

export type MemoryKind = 'user_preference' | 'stable_fact' | 'episodic' | 'task' | 'agent_learning';
export type MemorySensitivity = 'standard' | 'personal' | 'sensitive' | 'restricted';

export type MemoryRecord = {
  memory_id: string;
  scope: { tenant_id: string; user_id: string; agent_id?: string | null; session_id?: string | null };
  kind: MemoryKind;
  content: string;
  sensitivity: MemorySensitivity;
  provenance: { source_type: string; actor_id: string; source_id?: string | null; note?: string | null };
  created_at: string;
  updated_at: string;
  confidence: number;
  valid_from?: string | null;
  valid_to?: string | null;
  expires_at?: string | null;
  supersedes_id?: string | null;
  superseded_by_id?: string | null;
  status: 'active' | 'superseded' | 'forgotten';
  metadata: Record<string, unknown>;
};

export type MemoryList = {
  schema_version: 'klara.memory-list.v1';
  records: MemoryRecord[];
  counts_by_kind: Record<string, number>;
};

export type PermissionEffect = 'deny' | 'allow_once' | 'allow_task' | 'allow_standing';
export type PermissionRequestStatus = 'pending' | 'approved' | 'denied' | 'expired';
export type PermissionGrantStatus = 'active' | 'consumed' | 'revoked' | 'expired';
export type PermissionScope = { tenant_id: string; actor_id: string; agent_id: string; task_id?: string | null };
export type PermissionAction = {
  tool_name: string;
  capability: string;
  side_effect: 'none' | 'read' | 'write' | 'network' | 'control';
  resource_type: string;
  resource: string;
  risk: 'low' | 'medium' | 'high' | 'critical';
  destructive: boolean;
  externally_consequential: boolean;
  arguments_sha256: string;
};
export type PermissionRequestRecord = {
  request_id: string;
  fingerprint: string;
  scope: PermissionScope;
  action: PermissionAction;
  status: PermissionRequestStatus;
  created_at: string;
  updated_at: string;
  expires_at: string;
  repeated_count: number;
  decision_effect?: PermissionEffect | null;
};
export type PermissionGrantRecord = {
  grant_id: string;
  request_id?: string | null;
  effect: PermissionEffect;
  status: PermissionGrantStatus;
  scope: PermissionScope;
  action: PermissionAction;
  created_at: string;
  expires_at: string;
  remaining_uses?: number | null;
  parent_grant_id?: string | null;
  revoked_at?: string | null;
};
export type PermissionAuditRecord = {
  audit_id: string;
  operation: string;
  decision: string;
  occurred_at: string;
  request_id?: string | null;
  grant_id?: string | null;
  tool_name?: string | null;
  resource?: string | null;
};
export type PermissionState = {
  schema_version: 'klara.permissions-state.v1';
  requests: PermissionRequestRecord[];
  grants: PermissionGrantRecord[];
  audit: PermissionAuditRecord[];
};

export type DurableTaskState = 'waiting' | 'ready' | 'running' | 'paused' | 'blocked' | 'completed' | 'failed' | 'cancelled';
export type DurableTask = {
  task_id: string;
  scope: { tenant_id: string; owner_id: string; agent_id: string };
  title: string;
  description: string;
  state: DurableTaskState;
  dependency_ids: string[];
  parent_task_id?: string | null;
  required_artifacts: string[];
  required_evidence: string[];
  active_attempt_id?: string | null;
  attempt_count: number;
  max_attempts: number;
  progress: number;
  current_step?: string | null;
  block_reason?: string | null;
  lease_worker_id?: string | null;
  lease_expires_at?: string | null;
  heartbeat_at?: string | null;
  checkpoint_sequence: number;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
  cancelled_at?: string | null;
};
export type DurableTaskAttempt = {
  attempt_id: string;
  task_id: string;
  number: number;
  worker_id: string;
  outcome: 'running' | 'completed' | 'paused' | 'blocked' | 'failed' | 'cancelled' | 'abandoned';
  started_at: string;
  ended_at?: string | null;
  failure_code?: string | null;
  failure_message?: string | null;
};
export type DurableTaskArtifact = {
  artifact_id: string;
  task_id: string;
  name: string;
  uri: string;
  media_type: string;
  sha256: string;
  is_evidence: boolean;
  attempt_id: string;
  created_at: string;
};
export type DurableTaskList = {
  schema_version: 'klara.durable-task-list.v1';
  tasks: DurableTask[];
  counts_by_state: Record<string, number>;
};
export type DurableTaskDetail = {
  schema_version: 'klara.durable-task-detail.v1';
  task: DurableTask;
  attempts: DurableTaskAttempt[];
  artifacts: DurableTaskArtifact[];
  latest_checkpoint?: { checkpoint_id: string; sequence: number; summary: string; payload_sha256: string; payload_field_count: number } | null;
  events: { event_id: string; operation: string; from_state?: string | null; to_state: string; occurred_at: string }[];
};

export type ScheduleKind = 'once' | 'interval' | 'daily' | 'weekly';
export type ScheduleStatus = 'active' | 'paused' | 'completed' | 'cancelled';
export type ScheduleRecord = {
  schedule_id: string;
  scope: { tenant_id: string; owner_id: string; agent_id: string };
  title: string;
  task_description: string;
  session_id?: string | null;
  kind: ScheduleKind;
  timezone: string;
  status: ScheduleStatus;
  run_at?: string | null;
  local_time?: string | null;
  weekdays: number[];
  interval_seconds?: number | null;
  misfire_policy: 'fire_once' | 'skip';
  misfire_grace_seconds: number;
  overlap_policy: 'skip' | 'queue_one';
  next_run_at?: string | null;
  last_scheduled_at?: string | null;
  last_result?: string | null;
  queued_overlap: boolean;
  created_at: string;
  updated_at: string;
};
export type ScheduleOccurrence = {
  occurrence_id: string;
  schedule_id: string;
  task_id?: string | null;
  scheduled_for: string;
  status: 'reserved' | 'enqueued' | 'skipped_misfire' | 'skipped_overlap' | 'completed' | 'failed' | 'cancelled';
  trigger: string;
  result?: string | null;
  created_at: string;
  updated_at: string;
  completed_at?: string | null;
};
export type ScheduleNotification = {
  notification_id: string;
  schedule_id: string;
  occurrence_id: string;
  task_id: string;
  session_id?: string | null;
  result: string;
  title: string;
  message: string;
  created_at: string;
  read_at?: string | null;
  delivered_at?: string | null;
};
export type SchedulerState = {
  schema_version: 'klara.scheduler-state.v1';
  schedules: ScheduleRecord[];
  occurrences: ScheduleOccurrence[];
  notifications: ScheduleNotification[];
};

// Klara Presence public event model. This is intentionally separate from the
// current backend RunEvent DTO above so the UI can grow without coupling presentation motion to transport events.
export type KlaraVisualPhase =
  | 'idle'
  | 'listening'
  | 'thinking'
  | 'searching'
  | 'searching_web'
  | 'reading'
  | 'acting'
  | 'checking'
  | 'writing'
  | 'saving'
  | 'completed'
  | 'error';

export type KlaraCapability =
  | 'runtime'
  | 'rag'
  | 'agentic_rag'
  | 'memory'
  | 'research'
  | 'mcp'
  | 'production'
  | 'eval'
  | 'rl';

export type KlaraCapabilityChip =
  | 'model'
  | 'tool'
  | 'rag'
  | 'web'
  | 'memory'
  | 'verify'
  | 'trace'
  | 'eval'
  | 'policy';

export type RunEventStatus = 'started' | 'progress' | 'completed' | 'failed';

export type KlaraRunEventKind =
  | 'run.started'
  | 'run.profile.frozen'
  | 'ask.created'
  | 'route.decided'
  | 'loop.started'
  | 'model.call.started'
  | 'model.call.completed'
  | 'thinking.summary.started'
  | 'thinking.summary.completed'
  | 'answer.started'
  | 'answer.token'
  | 'answer.completed'
  | 'tool.call.started'
  | 'tool.call.completed'
  | 'tool.call.failed'
  | 'hook.placement.started'
  | 'hook.placement.completed'
  | 'policy.stopped'
  | 'observation.created'
  | 'retrieval.started'
  | 'chunk.retrieved'
  | 'source.selected'
  | 'sourcecard.created'
  | 'citation.created'
  | 'web.search.started'
  | 'web.page.read'
  | 'memory.loaded'
  | 'reference.resolved'
  | 'verification.started'
  | 'verification.completed'
  | 'runlog.created'
  | 'trace.saved'
  | 'run.completed'
  | 'run.error';

export type KlaraRunEvent = {
  runId: string;
  eventId: string;
  seq: number;
  timestamp: string;
  kind: KlaraRunEventKind;
  status: RunEventStatus;
  publicLabel: string;
  publicDetail?: string;
  concept?: string;
  iteration?: number;
  capabilities?: KlaraCapabilityChip[];
  safePayload?: Record<string, unknown>;
};
