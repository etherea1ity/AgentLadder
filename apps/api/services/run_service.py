from __future__ import annotations

import hashlib
import hmac
import json
import re
import threading
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from time import perf_counter, sleep
from typing import Any

from apps.api.schemas import (
    ClientContext,
    CreateRunResponse,
    MessageRecord,
    RunError,
    RunEventRecord,
    RunRecord,
    TokenSource,
    now_iso,
)
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.run_event_projector import (
    RunEventProjector,
    project_assistant_activity,
    project_activity_fact,
    project_provider_reasoning,
)
from apps.api.services.sse_bus import SSEBus
from klara.app.user_context import UserContext
from klara.context.history import prepare_conversation_history
from klara.context.policy import ContextPolicy
from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.context.timestamps import parse_prompt_datetime, stamp_user_message_content
from klara.core.events import KlaraEvent
from klara.core.loop import KlaraRunCheckpoint, LlmClient
from klara.core.messages import KlaraMessage, ModelCallError
from klara.core.policies import LoopPolicy
from klara.infra.config.models import ModelsConfig
from klara.infra.config.runtime import CapabilityProfile, ProviderRecoveryPolicy
from klara.planning.todo import TodoPlan
from klara.planning.tool import TodoWriteTool
from klara.tools.registry import ToolRegistry
from klara.tasks import (
    DurableTaskService,
    TaskLeaseError,
    TaskNotFoundError,
    TaskScope,
    TaskState,
    TaskTransitionError,
    TaskWriteConflict,
)
from klara.mcp import McpService
from klara.memory import (
    EmbeddingProvider,
    LlmMemoryFactExtractor,
    MemoryFormationMode,
    MemoryFormationService,
)
from klara.permissions import PermissionScope
from klara.scheduler import SchedulerService
from klara.teams import TeamScope, TeamService


_TERMINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
_TERMINAL_RUN_EVENTS = {"run_completed", "run_failed", "run_cancelled"}


class RunService:
    """Project Klara loop runs into the local chat API and SSE event stream."""

    def __init__(
        self,
        store: JsonlAppStore,
        bus: SSEBus,
        llm_client: LlmClient,
        trace_path: str = "data/traces/runs.jsonl",
        allowed_models: set[str] | None = None,
        thinking_support: dict[str, bool] | None = None,
        default_thinking: dict[str, bool] | None = None,
        default_model: str | None = None,
        loop_policy: LoopPolicy | None = None,
        user_context: UserContext | None = None,
        answer_chunking_enabled: bool = True,
        answer_chunk_delay_ms: int = 15,
        models_config: ModelsConfig | None = None,
        capability_profile: CapabilityProfile | None = None,
        context_policy: ContextPolicy | None = None,
        provider_recovery_policy: ProviderRecoveryPolicy | None = None,
        task_service: DurableTaskService | None = None,
        task_scope: TaskScope | None = None,
        mcp_service: McpService | None = None,
        scheduler_service: SchedulerService | None = None,
        team_service: TeamService | None = None,
        team_scope: TeamScope | None = None,
        permission_scope: PermissionScope | None = None,
        memory_embedding_provider: EmbeddingProvider | None = None,
        memory_formation_mode: MemoryFormationMode = MemoryFormationMode.DISABLED,
    ) -> None:
        """Create the local run service.

        Args:
            store: JSONL-backed app store for sessions, messages, runs, events.
            bus: In-process SSE fanout for live frontend updates.
            llm_client: Klara-compatible model client.
            trace_path: Optional JSONL lifecycle trace destination.
            allowed_models: Model refs accepted from the UI.
            thinking_support: Model refs that can accept thinking mode.
            default_thinking: Default thinking mode per model ref.
            default_model: Model ref used when a run does not select one.
            loop_policy: Bounded execution policy for loop safety.
            user_context: Local user partition and prompt timezone context.
            answer_chunking_enabled: Whether blocking answers should emit chunks.
            answer_chunk_delay_ms: Delay between answer chunks for live UX.
        """

        self.store = store
        self.bus = bus
        self.llm_client = llm_client
        self.allowed_models = allowed_models or set()
        self.thinking_support = thinking_support or {}
        self.default_thinking = default_thinking or {}
        self.default_model = default_model
        self.loop_policy = loop_policy or LoopPolicy()
        self.user_context = user_context or UserContext.local_default()
        self.answer_chunking_enabled = answer_chunking_enabled
        self.answer_chunk_delay_ms = max(0, answer_chunk_delay_ms)
        self.models_config = models_config
        self.capability_profile = capability_profile or CapabilityProfile(
            id="agent",
            hooks=("run_projection", "jsonl_trace"),
            trace_sink="jsonl",
        )
        self.context_policy = context_policy or ContextPolicy()
        self.provider_recovery_policy = (
            provider_recovery_policy or ProviderRecoveryPolicy()
        )
        self.trace_path = trace_path
        self.task_service = task_service
        self.task_scope = task_scope
        self.mcp_service = mcp_service
        self.scheduler_service = scheduler_service
        self.team_service = team_service
        self.team_scope = team_scope
        self.permission_scope = permission_scope
        self.memory_embedding_provider = memory_embedding_provider
        self.memory_formation_mode = memory_formation_mode
        self._cancel_requested: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}
        self._task_leases: dict[str, str] = {}
        self._restored_loop_checkpoints: dict[str, KlaraRunCheckpoint] = {}
        self._restored_run_profile_sha256: dict[str, str] = {}
        self._restored_checkpoint_errors: dict[str, str] = {}
        self._heartbeat_stops: dict[str, threading.Event] = {}
        self._heartbeat_threads: dict[str, threading.Thread] = {}
        self._terminal_lock = threading.RLock()

    def create_run(
        self,
        session_id: str,
        question: str,
        model: str | None = None,
        thinking_enabled: bool | None = None,
        client_context: ClientContext | None = None,
    ) -> CreateRunResponse:
        """Create user/assistant messages and start a background Klara loop."""

        session = self.store.get_visible_session(session_id)
        if session is None:
            raise KeyError("session_not_found")
        selected_model = self._select_model(model)
        selected_thinking_enabled = self._select_thinking_enabled(
            selected_model,
            thinking_enabled,
        )

        title = _title_from_question(question)
        if session.title == "Untitled":
            self.store.rename_session(session_id, title)

        user_message = MessageRecord(
            session_id=session_id,
            role="user",
            content=question,
            status="completed",
            client_created_at=client_context.timestamp if client_context else None,
            client_timezone=_client_timezone_name(client_context),
            client_utc_offset_minutes=(
                client_context.utc_offset_minutes if client_context else None
            ),
        )
        run = RunRecord(
            session_id=session_id,
            user_message_id=user_message.message_id,
            assistant_message_id="pending",
            status="queued",
            model=selected_model,
            thinking_enabled=selected_thinking_enabled,
        )
        assistant_message = MessageRecord(
            session_id=session_id,
            role="assistant",
            content="",
            run_id=run.run_id,
            status="running",
        )
        run = run.model_copy(update={"assistant_message_id": assistant_message.message_id})
        if self.task_service is not None and self.task_scope is not None:
            self.task_service.create(
                scope=self.task_scope,
                task_id=run.run_id,
                title=title,
                description=question,
                max_attempts=3,
            )
        self.store.save_message(user_message)
        self.store.save_message(assistant_message)
        self.store.save_run(run)
        self._emit(
            run.run_id,
            "run_created",
            "Run created.",
            {
                "session_id": session_id,
                "thinking_enabled": selected_thinking_enabled,
            },
        )

        thread = threading.Thread(
            target=self._run_thread,
            args=(run.run_id,),
            daemon=False,
            name=f"klara-run-{run.run_id[:12]}",
        )
        self._threads[run.run_id] = thread
        thread.start()

        return CreateRunResponse(
            run_id=run.run_id,
            session_id=session_id,
            user_message_id=user_message.message_id,
            assistant_message_id=assistant_message.message_id,
            status="queued",
            events_url=f"/api/runs/{run.run_id}/events/stream",
        )

    def create_scheduled_run(
        self,
        *,
        session_id: str,
        task_id: str,
        question: str,
        schedule_title: str,
    ) -> CreateRunResponse:
        """Start or safely resume one scheduler-owned durable task as a chat run."""

        if self.store.get_visible_session(session_id) is None:
            raise KeyError("session_not_found")
        existing = self.store.get_run(task_id)
        if existing is not None:
            live_thread = self._threads.get(task_id)
            if existing.status in {"completed", "cancelled"} or (
                live_thread is not None and live_thread.is_alive()
            ):
                return self._run_response(existing)
            if existing.status == "failed":
                if not self._scheduled_retry_is_ready(task_id):
                    return self._run_response(existing)
                assistant = self.store.get_message(existing.assistant_message_id)
                if assistant is not None:
                    self.store.update_message(
                        assistant.model_copy(update={"content": "", "status": "running"})
                    )
                run = existing.model_copy(
                    update={
                        "status": "queued",
                        "started_at": None,
                        "completed_at": None,
                        "error": None,
                    }
                )
                self.store.save_run(run)
            else:
                # The app process died after persisting a queued run. Its durable
                # task lease determines whether execution can be reclaimed.
                run = existing
        else:
            suffix = hashlib.sha256(task_id.encode("utf-8")).hexdigest()[:24]
            user_message = MessageRecord(
                message_id=f"msg_schedule_user_{suffix}",
                session_id=session_id,
                role="user",
                content=f"[Scheduled: {schedule_title}]\n{question}".strip(),
                status="completed",
            )
            assistant_message = MessageRecord(
                message_id=f"msg_schedule_assistant_{suffix}",
                session_id=session_id,
                role="assistant",
                content="",
                run_id=task_id,
                status="running",
            )
            run = RunRecord(
                run_id=task_id,
                session_id=session_id,
                user_message_id=user_message.message_id,
                assistant_message_id=assistant_message.message_id,
                status="queued",
                model=self._select_model(None),
                thinking_enabled=self._select_thinking_enabled(
                    self._select_model(None), None
                ),
            )
            self.store.save_message(user_message)
            self.store.save_message(assistant_message)
            self.store.save_run(run)
            self._emit(
                run.run_id,
                "run_created",
                "Scheduled run created.",
                {"session_id": session_id, "scheduled": True},
            )
        thread = threading.Thread(
            target=self._run_thread,
            args=(run.run_id,),
            daemon=False,
            name=f"klara-run-{run.run_id[:12]}",
        )
        self._threads[run.run_id] = thread
        thread.start()
        return self._run_response(run)

    def recover_incomplete_runs(self) -> int:
        """Resume persisted non-terminal runs after an API process restart."""

        recovered = 0
        for session in self.store.list_sessions():
            for run in self.store.list_runs(session.session_id):
                if run.status not in {"queued", "thinking"} or run.run_id in self._threads:
                    continue
                delay = self._durable_claim_delay_seconds(run.run_id)
                thread = threading.Thread(
                    target=self._resume_after_delay,
                    args=(run.run_id, delay),
                    daemon=False,
                    name=f"klara-recover-{run.run_id[:12]}",
                )
                self._threads[run.run_id] = thread
                thread.start()
                recovered += 1
        return recovered

    def _resume_after_delay(self, run_id: str, delay_seconds: float) -> None:
        """Respect an unexpired prior lease, then enter the normal worker path."""

        if delay_seconds > 0:
            sleep(delay_seconds)
        self._run_thread(run_id)

    def _durable_claim_delay_seconds(self, run_id: str) -> float:
        if self.task_service is None or self.task_scope is None:
            return 0.0
        try:
            task = self.task_service.get(scope=self.task_scope, task_id=run_id)
        except TaskNotFoundError:
            return 0.0
        if task.state is not TaskState.RUNNING or not task.lease_expires_at:
            return 0.0
        expires = datetime.fromisoformat(task.lease_expires_at.replace("Z", "+00:00"))
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=UTC)
        return max(0.0, (expires - datetime.now(UTC)).total_seconds() + 0.05)

    def inject_schedule_notification(
        self, *, notification_id: str, session_id: str | None, message: str
    ) -> None:
        """Project completion into chat without adding it to future model context."""

        if session_id is None or self.store.get_visible_session(session_id) is None:
            return
        message_id = f"msg_{notification_id}"
        if self.store.get_message(message_id) is not None:
            return
        self.store.save_message(
            MessageRecord(
                message_id=message_id,
                session_id=session_id,
                role="assistant",
                content=message,
                status="completed",
                model_visible=False,
            )
        )

    @staticmethod
    def _run_response(run: RunRecord) -> CreateRunResponse:
        return CreateRunResponse(
            run_id=run.run_id,
            session_id=run.session_id,
            user_message_id=run.user_message_id,
            assistant_message_id=run.assistant_message_id,
            status=run.status,
            events_url=f"/api/runs/{run.run_id}/events/stream",
        )

    def cancel_run(self, run_id: str) -> RunRecord | None:
        """Request cancellation and immediately mark the visible run stopped."""

        with self._terminal_lock:
            run = self.store.get_run(run_id)
            if run is None:
                return None
            if run.status in {"completed", "failed", "cancelled"}:
                return run
            self._cancel_requested.add(run_id)
            self._cancel_durable_task(run_id)
            cancelled = run.model_copy(update={"status": "cancelled", "completed_at": now_iso()})
            self.store.save_run(cancelled)
            message = self.store.get_message(run.assistant_message_id)
            if message:
                self.store.update_message(message.model_copy(update={"status": "cancelled"}))
            self._emit(run_id, "run_cancelled", "Run cancelled.", {})
            return cancelled

    def cancel_active_runs_for_session(self, session_id: str) -> None:
        """Cancel all non-terminal runs before deleting a conversation."""

        for run in self.store.list_runs(session_id):
            if run.status not in {"completed", "failed", "cancelled"}:
                self.cancel_run(run.run_id)

    def _run_thread(self, run_id: str) -> None:
        """Execute one run on a worker thread and persist public projections."""

        started = perf_counter()
        run = self.store.get_run(run_id)
        if run is None:
            self._cleanup_run_runtime(run_id)
            return
        user_message = self.store.get_message(run.user_message_id)
        assistant_message = self.store.get_message(run.assistant_message_id)
        if user_message is None or assistant_message is None:
            self._cleanup_run_runtime(run_id)
            return

        if run.status == "cancelled" or run_id in self._cancel_requested:
            self._cleanup_run_runtime(run_id)
            return
        if not self._claim_durable_task(run_id):
            self._cleanup_run_runtime(run_id)
            return
        if run_id in self._cancel_requested:
            self._cleanup_run_runtime(run_id)
            return
        current = run.model_copy(update={"status": "thinking", "started_at": now_iso()})
        self.store.save_run(current)
        self._progress_durable_task(run_id, 5, "Runtime started")
        selected_model = current.model or self.default_model or "fake-model"
        thinking_enabled = current.thinking_enabled
        run_user_context = replace(
            self.user_context,
            timezone=_message_timezone_name(user_message, self.user_context.timezone),
        )
        run_now = _message_client_datetime(user_message)
        self._emit(run_id, "thinking_started", "Klara is preparing the runtime loop.", {})
        self._emit(
            run_id,
            "thinking_summary_started",
            "Klara is thinking.",
            {
                "started_at": now_iso(),
                "presentation": "gpt_style_collapsible",
                "request": {
                    "preview": _request_preview(user_message.content),
                    "language": _detect_language(user_message.content),
                },
            },
        )
        projector = RunEventProjector(selected_model=selected_model)

        try:
            harness = KlaraHarness(
                llm=self.llm_client,
                registry=self._registry_for_run(run.session_id),
                config=KlaraHarnessConfig(
                    model=selected_model,
                    thinking_enabled=thinking_enabled,
                    capability_profile=self.capability_profile,
                    trace_path=Path(self.trace_path) if self.trace_path else None,
                    loop_policy=self.loop_policy,
                    context_policy=self.context_policy,
                    provider_recovery_policy=self.provider_recovery_policy,
                    user_context=run_user_context,
                    workspace_root=Path.cwd(),
                    session_id=run.session_id,
                    memory_path=self.store.root / "memory.sqlite3",
                    permission_path=self.store.root / "permissions.sqlite3",
                    task_service=self.task_service,
                    task_scope=self.task_scope,
                    scheduler_service=self.scheduler_service,
                    scheduler_scope=self.task_scope,
                    team_service=self.team_service,
                    team_scope=self.team_scope,
                    team_permission_scope=self.permission_scope,
                    durable_task_id=run_id,
                    durable_task_lease_token=self._task_leases.get(run_id),
                    memory_embedding_provider=self.memory_embedding_provider,
                ),
                models=self.models_config,
                hooks=(RunProjectionHook(self, run_id, projector),),
            )
            checkpoint_error = self._restored_checkpoint_errors.get(run_id)
            if checkpoint_error is not None:
                raise RuntimeError(checkpoint_error)
            restored_profile_sha256 = self._restored_run_profile_sha256.get(run_id)
            if restored_profile_sha256 is not None and not hmac.compare_digest(
                restored_profile_sha256,
                harness.run_profile.profile_sha256,
            ):
                raise RuntimeError("agent_run_profile_mismatch")
            self._emit(
                run_id,
                "run_profile_frozen",
                "Run configuration frozen.",
                harness.run_profile.to_public_dict(),
            )
            model_visible_user_input = self._model_visible_content(user_message)
            result = harness.run(
                model_visible_user_input,
                run_id=run_id,
                prior_messages=self._conversation_history(
                    run.session_id,
                    before_message_id=user_message.message_id,
                ),
                now=run_now,
                checkpoint=self._restored_loop_checkpoints.get(run_id),
                checkpoint_sink=lambda checkpoint: self._checkpoint_agent_run(
                    run_id,
                    checkpoint,
                    run_profile_sha256=harness.run_profile.profile_sha256,
                ),
            )
            if run_id in self._cancel_requested:
                return

            self._progress_durable_task(run_id, 82, "Preparing verified answer")

            thinking_duration_ms = int((perf_counter() - started) * 1000)
            self._emit(
                run_id,
                "thinking_summary_completed",
                "Thinking summary completed.",
                {
                    "duration_ms": thinking_duration_ms,
                    "has_summary": False,
                },
            )
            final_text = result.final_answer
            self._capture_memory_formation(
                run_id=run_id,
                harness=harness,
                user_content=user_message.content,
                assistant_content=final_text,
                model=selected_model,
            )
            self._emit(run_id, "answer_streaming_started", "Klara is writing the final answer.", {})
            self._stream_answer_chunks(
                run_id=run_id,
                assistant_message=assistant_message,
                final_text=final_text,
            )
            if run_id in self._cancel_requested:
                return

            latency_ms = int((perf_counter() - started) * 1000)
            usage_totals = projector.usage_totals
            token_source: TokenSource = "reported" if usage_totals.has_reported else "unknown"
            completed_metrics = {
                "latency_ms": latency_ms,
                "prompt_tokens": usage_totals.prompt_tokens,
                "completion_tokens": usage_totals.completion_tokens,
                "total_tokens": usage_totals.total_tokens,
                "token_source": token_source,
            }
            trace_saved = self._trace_has_run_events(run_id)
            completed = current.model_copy(
                update={
                    "status": "completed",
                    "completed_at": now_iso(),
                    "latency_ms": latency_ms,
                    "prompt_tokens": usage_totals.prompt_tokens,
                    "completion_tokens": usage_totals.completion_tokens,
                    "total_tokens": usage_totals.total_tokens,
                    "token_source": token_source,
                    "trace_saved": trace_saved,
                }
            )
            with self._terminal_lock:
                latest = self.store.get_run(run_id)
                if run_id in self._cancel_requested or latest is None or latest.status == "cancelled":
                    return
                self._complete_durable_task(run_id)
                self.store.save_run(completed)
                self.store.update_message(assistant_message.model_copy(update={"status": "completed", "content": final_text}))
                self._emit(
                    run_id,
                    "run_completed",
                    "Run completed.",
                    {
                        "latency_ms": latency_ms,
                        "prompt_tokens": usage_totals.prompt_tokens,
                        "completion_tokens": usage_totals.completion_tokens,
                        "total_tokens": usage_totals.total_tokens,
                        "token_source": token_source,
                        "stop_reason": result.stop_reason.value,
                        "hook_failures": result.hook_failures,
                        "trace_saved": trace_saved,
                        "metrics": completed_metrics,
                    },
                )
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            error = RunError(
                code=_error_code(exc),
                message=_public_error_message(exc),
                stage="runtime_loop",
            )
            with self._terminal_lock:
                latest = self.store.get_run(run_id)
                if run_id in self._cancel_requested or latest is None or latest.status == "cancelled":
                    return
                failed = current.model_copy(update={"status": "failed", "completed_at": now_iso(), "latency_ms": latency_ms, "error": error})
                self._fail_durable_task(run_id, exc)
                self.store.save_run(failed)
                self.store.update_message(assistant_message.model_copy(update={"status": "failed"}))
                self._emit(
                    run_id,
                    "run_failed",
                    "Run failed.",
                    {
                        "error": error.model_dump(mode="json"),
                        "latency_ms": latency_ms,
                    },
                )
        finally:
            self._cleanup_run_runtime(run_id)

    def _emit(
        self,
        run_id: str,
        event_type,
        message: str,
        payload: dict[str, Any],
    ) -> RunEventRecord | None:
        """Persist and publish one API-level run event."""

        if event_type not in _TERMINAL_RUN_EVENTS:
            run = self.store.get_run(run_id)
            if (
                run is None
                or run.status in _TERMINAL_RUN_STATUSES
                or run_id in self._cancel_requested
            ):
                return None
        event = RunEventRecord(run_id=run_id, event_type=event_type, message=message, payload=payload)
        self.store.append_event(event)
        self.bus.publish(event)
        self._emit_projected_provider_reasoning(event)
        self._emit_projected_assistant_activity(event)
        self._emit_projected_activity_fact(event)
        return event

    def _emit_projected_provider_reasoning(self, event: RunEventRecord) -> None:
        """Persist and publish provider reasoning summaries derived from an event."""

        for projected in project_provider_reasoning(event):
            reasoning_event = RunEventRecord(
                run_id=event.run_id,
                event_type=projected.event_type,
                message=projected.message,
                payload=projected.payload,
            )
            self.store.append_event(reasoning_event)
            self.bus.publish(reasoning_event)

    def _emit_projected_assistant_activity(self, event: RunEventRecord) -> None:
        """Persist and publish main-model public activity commentary."""

        for projected in project_assistant_activity(event):
            activity_event = RunEventRecord(
                run_id=event.run_id,
                event_type=projected.event_type,
                message=projected.message,
                payload=projected.payload,
            )
            self.store.append_event(activity_event)
            self.bus.publish(activity_event)

    def _emit_projected_activity_fact(self, event: RunEventRecord) -> None:
        """Persist and publish one structured activity fact derived from an event."""

        projected = project_activity_fact(event)
        if projected is None:
            return
        fact_event = RunEventRecord(
            run_id=event.run_id,
            event_type=projected.event_type,
            message=projected.message,
            payload=projected.payload,
        )
        self.store.append_event(fact_event)
        self.bus.publish(fact_event)

    def _trace_has_run_events(self, run_id: str) -> bool:
        """Return whether the local JSONL trace contains events for this run."""

        path = Path(self.trace_path)
        if not path.exists():
            return False
        with path.open("r", encoding="utf-8") as file:
            for line in file:
                if not line.strip():
                    continue
                try:
                    record = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if record.get("run_id") == run_id:
                    return True
        return False

    def _stream_answer_chunks(
        self,
        *,
        run_id: str,
        assistant_message: MessageRecord,
        final_text: str,
    ) -> None:
        """Emit answer_delta chunks while keeping final message content exact."""

        chunks = tuple(_answer_chunks(final_text, enabled=self.answer_chunking_enabled))
        if not chunks:
            chunks = ("",)
        streamed_chars = 0
        accumulated: list[str] = []
        for index, chunk in enumerate(chunks):
            if run_id in self._cancel_requested:
                return
            streamed_chars += len(chunk)
            accumulated.append(chunk)
            self.store.update_message(
                assistant_message.model_copy(
                    update={"content": "".join(accumulated), "status": "running"}
                )
            )
            self._emit(
                run_id,
                "answer_delta",
                "",
                {
                    "delta": chunk,
                    "streamed_chars": streamed_chars,
                    "stream_mode": "display_chunked"
                    if self.answer_chunking_enabled
                    else "single_payload",
                },
            )
            if (
                index < len(chunks) - 1
                and self.answer_chunking_enabled
                and self.answer_chunk_delay_ms > 0
            ):
                sleep(self.answer_chunk_delay_ms / 1000)

    def _cleanup_run_runtime(self, run_id: str) -> None:
        """Remove per-run cancellation and thread bookkeeping."""

        stop = self._heartbeat_stops.pop(run_id, None)
        if stop is not None:
            stop.set()
        heartbeat = self._heartbeat_threads.pop(run_id, None)
        if heartbeat is not None and heartbeat is not threading.current_thread():
            heartbeat.join(timeout=1)
        self._cancel_requested.discard(run_id)
        self._threads.pop(run_id, None)
        self._task_leases.pop(run_id, None)
        self._restored_loop_checkpoints.pop(run_id, None)
        self._restored_run_profile_sha256.pop(run_id, None)
        self._restored_checkpoint_errors.pop(run_id, None)

    def _scheduled_retry_is_ready(self, run_id: str) -> bool:
        """Allow a failed scheduler run to restart only after an explicit task retry."""

        if self.task_service is None or self.task_scope is None:
            return False
        try:
            task = self.task_service.get(scope=self.task_scope, task_id=run_id)
        except TaskNotFoundError:
            return False
        return task.state is TaskState.READY

    def _claim_durable_task(self, run_id: str) -> bool:
        if self.task_service is None or self.task_scope is None:
            return True
        try:
            claim = self.task_service.claim(
                scope=self.task_scope,
                task_id=run_id,
                worker_id=f"api-thread:{threading.get_ident()}",
                lease_seconds=90,
            )
        except (
            TaskLeaseError,
            TaskNotFoundError,
            TaskTransitionError,
            TaskWriteConflict,
        ):
            return False
        self._task_leases[run_id] = claim.lease_token
        stop = threading.Event()
        heartbeat = threading.Thread(
            target=self._heartbeat_durable_task,
            args=(run_id, claim.lease_token, stop),
            daemon=False,
            name=f"klara-heartbeat-{run_id[:12]}",
        )
        self._heartbeat_stops[run_id] = stop
        self._heartbeat_threads[run_id] = heartbeat
        heartbeat.start()
        if claim.restored_checkpoint is not None:
            payload = self.task_service.repository.checkpoint_payload(
                self.task_scope, claim.restored_checkpoint.checkpoint_id
            )
            try:
                if not isinstance(payload, dict):
                    raise ValueError("agent_checkpoint_payload_invalid")
                if payload.get("schema_version") != "klara.agent-run-checkpoint.v1":
                    raise ValueError("agent_checkpoint_schema_invalid")
                profile_sha256 = payload.get("run_profile_sha256")
                if not isinstance(profile_sha256, str) or not re.fullmatch(
                    r"[0-9a-f]{64}", profile_sha256
                ):
                    raise ValueError("agent_checkpoint_profile_hash_invalid")
                agent_loop = payload.get("agent_loop")
                if not isinstance(agent_loop, dict):
                    raise ValueError("agent_checkpoint_loop_invalid")
                self._restored_run_profile_sha256[run_id] = profile_sha256
                self._restored_loop_checkpoints[run_id] = (
                    KlaraRunCheckpoint.from_private_dict(agent_loop)
                )
            except (KeyError, TypeError, ValueError) as exc:
                self._restored_checkpoint_errors[run_id] = str(exc)
        return True

    def _heartbeat_durable_task(
        self, run_id: str, lease_token: str, stop: threading.Event
    ) -> None:
        """Renew the worker lease while a blocking model/tool step is in flight."""

        if self.task_service is None or self.task_scope is None:
            return
        while not stop.wait(30):
            try:
                self.task_service.heartbeat(
                    scope=self.task_scope,
                    task_id=run_id,
                    lease_token=lease_token,
                    lease_seconds=90,
                )
            except (TaskLeaseError, TaskNotFoundError, TaskTransitionError, TaskWriteConflict):
                return

    def _checkpoint_agent_run(
        self,
        run_id: str,
        checkpoint: KlaraRunCheckpoint,
        *,
        run_profile_sha256: str,
    ) -> None:
        """Persist one safe loop boundary under the active durable-task lease."""

        if self.task_service is None or self.task_scope is None:
            return
        token = self._task_leases.get(run_id)
        if token is None:
            return
        self.task_service.checkpoint(
            scope=self.task_scope,
            task_id=run_id,
            lease_token=token,
            summary=f"Agent loop ready for turn {checkpoint.next_turn_index}",
            payload={
                "schema_version": "klara.agent-run-checkpoint.v1",
                "run_profile_sha256": run_profile_sha256,
                "agent_loop": checkpoint.to_private_dict(),
            },
        )

    def _capture_memory_formation(
        self,
        *,
        run_id: str,
        harness: KlaraHarness,
        user_content: str,
        assistant_content: str,
        model: str,
    ) -> None:
        """Run one optional ADD-only formation pass without failing the answer."""

        if self.memory_formation_mode is MemoryFormationMode.DISABLED:
            return
        try:
            result = MemoryFormationService(
                harness.memory_service,
                LlmMemoryFactExtractor(self.llm_client, model=model),
                mode=self.memory_formation_mode,
            ).capture_turn(
                scope=harness.memory_scope,
                user_content=user_content,
                assistant_content=assistant_content,
                source_id=run_id,
            )
        except Exception as exc:
            self._emit(
                run_id,
                "memory_formation_failed",
                "Memory formation was skipped after a validation or provider failure.",
                {"error_code": _error_code(exc)},
            )
            return
        self._emit(
            run_id,
            "memory_formation_completed",
            "Memory formation completed.",
            result.to_public_dict(),
        )

    def _progress_durable_task(self, run_id: str, progress: int, step: str) -> None:
        if self.task_service is None or self.task_scope is None:
            return
        token = self._task_leases.get(run_id)
        if token is None:
            return
        self.task_service.progress(
            scope=self.task_scope,
            task_id=run_id,
            lease_token=token,
            progress=progress,
            current_step=step,
        )

    def _complete_durable_task(self, run_id: str) -> None:
        if self.task_service is None or self.task_scope is None:
            return
        token = self._task_leases.get(run_id)
        if token is not None:
            self.task_service.complete(
                scope=self.task_scope, task_id=run_id, lease_token=token
            )

    def _fail_durable_task(self, run_id: str, error: Exception) -> None:
        if self.task_service is None or self.task_scope is None:
            return
        token = self._task_leases.get(run_id)
        if token is None:
            return
        try:
            self.task_service.fail(
                scope=self.task_scope,
                task_id=run_id,
                lease_token=token,
                code=_error_code(error),
                message=_public_error_message(error),
            )
        except (TaskLeaseError, TaskTransitionError, TaskWriteConflict):
            return

    def _cancel_durable_task(self, run_id: str) -> None:
        if self.task_service is None or self.task_scope is None:
            return
        try:
            task = self.task_service.get(scope=self.task_scope, task_id=run_id)
            if task.state not in {TaskState.COMPLETED, TaskState.CANCELLED}:
                self.task_service.cancel(scope=self.task_scope, task_id=run_id)
        except LookupError:
            return

    def _select_model(self, requested_model: str | None) -> str | None:
        """Validate the requested model against the configured local registry."""

        model = requested_model or self.default_model
        if model and self.allowed_models and model not in self.allowed_models:
            raise ValueError("model_not_allowed")
        return model

    def _select_thinking_enabled(
        self,
        model: str | None,
        requested: bool | None,
    ) -> bool | None:
        """Return the per-run thinking switch after model capability checks."""

        if model is None:
            return requested
        supports_thinking = self.thinking_support.get(model, False)
        if requested is True and not supports_thinking:
            raise ValueError("thinking_not_supported")
        if not supports_thinking:
            return False
        if requested is None:
            return self.default_thinking.get(model, False)
        return requested

    def _conversation_history(
        self,
        session_id: str,
        *,
        before_message_id: str,
    ) -> tuple[KlaraMessage, ...]:
        """Return completed user/assistant messages before the current turn."""

        history: list[KlaraMessage] = []
        for message in self.store.list_messages(session_id):
            if message.message_id == before_message_id:
                break
            if (
                message.status != "completed"
                or not message.content.strip()
                or not message.model_visible
            ):
                continue
            if message.role not in {"user", "assistant"}:
                continue
            history.append(
                KlaraMessage(
                    role=message.role,
                    content=self._model_visible_content(message),
                )
            )
        return prepare_conversation_history(history)

    def _model_visible_content(self, message: MessageRecord) -> str:
        """Return stored message text translated for the model boundary."""

        if message.role != "user":
            return message.content
        return stamp_user_message_content(
            message.content,
            created_at=message.client_created_at or message.created_at,
            timezone_name=_message_timezone_name(message, self.user_context.timezone),
        )

    def _registry_for_run(self, session_id: str) -> ToolRegistry:
        """Return default tools plus current-session planning capability."""

        registry = ToolRegistry.with_default_tools()
        registry.register_tool(TodoWriteTool(session_id=session_id, store=self.store))
        if self.mcp_service is not None:
            scope = PermissionScope(
                tenant_id=self.user_context.tenant_id,
                actor_id=self.user_context.user_id,
                agent_id="klara",
                task_id=session_id,
            )
            for tool in self.mcp_service.visible_tools(scope=scope):
                registry.register_tool(tool)
        return registry


class RunProjectionHook:
    """Thin hook adapter that emits projected API run events."""

    def __init__(
        self,
        service: RunService,
        run_id: str,
        projector: RunEventProjector,
    ) -> None:
        """Create a projection hook bound to one app run."""

        self.service = service
        self.run_id = run_id
        self.projector = projector

    def on_event(self, event: KlaraEvent) -> None:
        """Project selected core events into the SSE stream."""

        for projected in self.projector.project(event):
            self.service._emit(
                self.run_id,
                projected.event_type,
                projected.message,
                projected.payload,
            )
        if event.type == "tool.completed":
            tool_result = event.payload.get("tool_result")
            if isinstance(tool_result, dict) and tool_result.get("name") == "todo_write" and tool_result.get("ok") is not False:
                try:
                    plan = TodoPlan.model_validate_json(str(tool_result.get("content", "")))
                except ValueError:
                    plan = None
                if plan is not None:
                    self.service._emit(
                        self.run_id,
                        "todo_plan_updated",
                        "Plan updated.",
                        plan.model_dump(mode="json"),
                    )


def _client_timezone_name(client_context: ClientContext | None) -> str | None:
    """Return the best prompt timezone name from browser context."""

    if client_context is None:
        return None
    if client_context.timezone:
        return client_context.timezone
    if client_context.utc_offset_minutes is None:
        return None
    return _offset_timezone_name(client_context.utc_offset_minutes)


def _message_timezone_name(message: MessageRecord, fallback: str) -> str:
    """Return the timezone to use for one model-visible user message."""

    if message.client_timezone:
        return message.client_timezone
    if message.client_utc_offset_minutes is not None:
        return _offset_timezone_name(message.client_utc_offset_minutes)
    return fallback


def _message_client_datetime(message: MessageRecord) -> datetime | None:
    """Return browser send time when the client supplied a valid timestamp."""

    if not message.client_created_at:
        return None
    return parse_prompt_datetime(message.client_created_at)


def _offset_timezone_name(offset_minutes: int) -> str:
    """Convert a JavaScript UTC offset minute count into a timezone label."""

    sign = "+" if offset_minutes >= 0 else "-"
    absolute = abs(offset_minutes)
    hours, minutes = divmod(absolute, 60)
    return f"UTC{sign}{hours:02d}:{minutes:02d}"


def _answer_chunks(
    text: str,
    *,
    enabled: bool,
    target_chars: int | None = None,
) -> tuple[str, ...]:
    """Split a final answer into display chunks without changing content."""

    if not enabled:
        return (text,)
    if not text:
        return ("",)
    target = target_chars or _answer_chunk_target(text)
    chunks: list[str] = []
    buffer = ""
    for piece in _answer_chunk_units(text):
        if not piece:
            continue
        if buffer and len(buffer) + len(piece) > target:
            chunks.append(buffer)
            buffer = piece
            continue
        buffer += piece
    if buffer:
        chunks.append(buffer)
    if len(chunks) == 1 and len(text) > 1 and not _is_markdown_atomic(text):
        chunks = list(_split_short_answer(text, target))
    return tuple(chunks) or (text,)


def _answer_chunk_target(text: str) -> int:
    """Return a display chunk target tuned for readable short-answer streaming."""

    if re.search(r"[\u4e00-\u9fff]", text):
        return 14
    if len(text) <= 80:
        return 24
    return 72


def _answer_chunk_units(text: str) -> tuple[str, ...]:
    """Tokenize answer text while keeping Markdown links and code fences intact."""

    pattern = re.compile(r"(```[\s\S]*?```|\[[^\]\n]+\]\([^)]+\)|\s+)")
    units: list[str] = []
    cursor = 0
    for match in pattern.finditer(text):
        if match.start() > cursor:
            units.extend(_split_non_special_text(text[cursor : match.start()]))
        units.append(match.group(0))
        cursor = match.end()
    if cursor < len(text):
        units.extend(_split_non_special_text(text[cursor:]))
    return tuple(units)


def _split_non_special_text(text: str) -> tuple[str, ...]:
    """Split ordinary text around whitespace before language-aware chunking."""

    pieces: list[str] = []
    for piece in re.split(r"(\s+)", text):
        if not piece:
            continue
        if piece.isspace():
            pieces.append(piece)
        else:
            pieces.extend(_split_plain_answer_unit(piece))
    return tuple(pieces)


def _split_plain_answer_unit(unit: str) -> tuple[str, ...]:
    """Split long plain-language units into small display-safe pieces."""

    if not re.search(r"[\u4e00-\u9fff]", unit):
        return (unit,)
    pieces: list[str] = []
    buffer = ""
    for char in unit:
        buffer += char
        if char in "，。！？；：、,.!?;:":
            pieces.append(buffer)
            buffer = ""
    if buffer:
        pieces.append(buffer)
    return tuple(pieces)


def _split_short_answer(text: str, target: int) -> tuple[str, ...]:
    """Force very short answers to show progressive display chunks."""

    midpoint = max(1, min(len(text) - 1, target))
    if re.search(r"[\u4e00-\u9fff]", text):
        punctuation_index = _last_punctuation_before(text, midpoint)
        if punctuation_index > 0:
            midpoint = punctuation_index + 1
    return (text[:midpoint], text[midpoint:])


def _last_punctuation_before(text: str, index: int) -> int:
    """Return the last natural split point before index, or -1 when absent."""

    candidates = [text.rfind(mark, 0, index) for mark in "，。！？；：、,.!?;:"]
    return max(candidates)


def _is_markdown_atomic(text: str) -> bool:
    """Return whether text should be preserved as one Markdown unit."""

    return text.startswith("```") or bool(re.fullmatch(r"\[[^\]\n]+\]\([^)]+\)", text))


def _request_preview(text: str, *, max_chars: int = 120) -> str:
    """Return a short redacted preview of the user's request for activity facts."""

    compact = " ".join(text.split())
    compact = re.sub(r"https?://\S+", "[url]", compact)
    compact = re.sub(
        r"(?i)\b(api[_-]?key|token|secret|password)\s*[:=]\s*\S+",
        r"\1=[redacted]",
        compact,
    )
    compact = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "sk-[redacted]", compact)
    return compact[:max_chars]


def _detect_language(text: str) -> str:
    """Return a compact language hint for public run metadata."""

    if re.search(r"[\u4e00-\u9fff]", text):
        return "zh"
    if re.search(r"[A-Za-z]", text):
        return "en"
    return "unknown"


def _title_from_question(question: str) -> str:
    text = " ".join(question.split())
    if not text:
        return "Untitled"
    title = " ".join(text.split()[:8])
    return title[:40]


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ModelCallError):
        return exc.code
    text = str(exc).lower()
    if "api_key" in text or "api key" in text or "missing api key" in text:
        return "missing_api_key"
    if "provider http" in text or "provider request" in text:
        return "provider_error"
    return "run_failed"


def _public_error_message(exc: Exception) -> str:
    """Return a useful app error without exposing provider response bodies."""

    if not isinstance(exc, ModelCallError):
        return str(exc)
    messages = {
        "provider_credentials_missing": "The selected model provider is not configured.",
        "provider_authentication_failed": "The model provider rejected authentication.",
        "provider_timeout": "The model provider timed out.",
        "provider_rate_limited": "The model provider is temporarily rate limited.",
        "provider_unavailable": "The model provider is temporarily unavailable.",
        "context_length_exceeded": "The request remained too large after context recovery.",
        "all_model_candidates_failed": "All configured model routes failed.",
        "model_configuration_error": "The selected model route is not configured correctly.",
        "provider_tool_protocol_invalid": "The model provider returned an invalid tool-call protocol. No protocol markup was shown.",
    }
    return messages.get(exc.code, "The model call failed.")
