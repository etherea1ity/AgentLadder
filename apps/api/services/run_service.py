from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from time import perf_counter
from typing import Any

from apps.api.schemas import (
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
    project_activity_fact,
    project_provider_reasoning,
)
from apps.api.services.sse_bus import SSEBus
from apps.api.services.workstream_narrator import (
    ThinkingActivityInput,
    ThinkingActivityNarrator,
    ThinkingActivityResult,
)
from klara.app.user_context import UserContext
from klara.context.history import prepare_conversation_history
from klara.context.runtime import build_system_prompt
from klara.context.timestamps import stamp_user_message_content
from klara.core.events import KlaraEvent
from klara.core.hooks import HookManager, JsonlTraceHook
from klara.core.loop import KlaraLoop, LlmClient
from klara.core.messages import KlaraMessage
from klara.core.policies import LoopPolicy
from klara.tools.executor import ToolExecutor
from klara.tools.registry import ToolRegistry

MAX_HISTORY_MESSAGES = 12


class RunService:
    """Project Klara loop runs into the local chat API and SSE event stream."""

    def __init__(
        self,
        store: JsonlAppStore,
        bus: SSEBus,
        llm_client: LlmClient,
        trace_path: str = "data/traces/runs.jsonl",
        allowed_models: set[str] | None = None,
        default_model: str | None = None,
        loop_policy: LoopPolicy | None = None,
        user_context: UserContext | None = None,
        narrator_client: LlmClient | None = None,
        narrator_model: str | None = None,
        enable_workstream_narrator: bool = False,
    ) -> None:
        """Create the local run service.

        Args:
            store: JSONL-backed app store for sessions, messages, runs, events.
            bus: In-process SSE fanout for live frontend updates.
            llm_client: Klara-compatible model client.
            trace_path: Optional JSONL lifecycle trace destination.
            allowed_models: Model refs accepted from the UI.
            default_model: Model ref used when a run does not select one.
            loop_policy: Bounded execution policy for loop safety.
            user_context: Local user partition and prompt timezone context.
            narrator_client: Optional second model client for runtime notes.
            narrator_model: Model ref used by the optional narrator.
            enable_workstream_narrator: Whether runtime notes should emit.
        """

        self.store = store
        self.bus = bus
        self.llm_client = llm_client
        self.allowed_models = allowed_models or set()
        self.default_model = default_model
        self.loop_policy = loop_policy or LoopPolicy()
        self.user_context = user_context or UserContext.local_default()
        self.narrator_client = narrator_client
        self.narrator_model = narrator_model
        self.enable_workstream_narrator = enable_workstream_narrator
        self.trace_path = trace_path
        self._cancel_requested: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}

    def create_run(self, session_id: str, question: str, model: str | None = None) -> CreateRunResponse:
        """Create user/assistant messages and start a background Klara loop."""

        session = self.store.get_visible_session(session_id)
        if session is None:
            raise KeyError("session_not_found")
        selected_model = self._select_model(model)

        title = _title_from_question(question)
        if session.title == "Untitled":
            self.store.rename_session(session_id, title)

        user_message = MessageRecord(session_id=session_id, role="user", content=question, status="completed")
        self.store.save_message(user_message)

        run = RunRecord(
            session_id=session_id,
            user_message_id=user_message.message_id,
            assistant_message_id="pending",
            status="queued",
            model=selected_model,
        )
        assistant_message = MessageRecord(
            session_id=session_id,
            role="assistant",
            content="",
            run_id=run.run_id,
            status="running",
        )
        run = run.model_copy(update={"assistant_message_id": assistant_message.message_id})
        self.store.save_message(assistant_message)
        self.store.save_run(run)
        self._emit(run.run_id, "run_created", "Run created.", {"session_id": session_id})

        thread = threading.Thread(target=self._run_thread, args=(run.run_id,), daemon=True)
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

    def cancel_run(self, run_id: str) -> RunRecord | None:
        """Request cancellation and immediately mark the visible run stopped."""

        run = self.store.get_run(run_id)
        if run is None:
            return None
        if run.status in {"completed", "failed", "cancelled"}:
            return run
        self._cancel_requested.add(run_id)
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

        current = run.model_copy(update={"status": "thinking", "started_at": now_iso()})
        self.store.save_run(current)
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

        selected_model = current.model or self.default_model or "fake-model"
        projector = RunEventProjector(selected_model=selected_model)
        hooks = HookManager(
            [RunProjectionHook(self, run_id, projector), JsonlTraceHook(Path(self.trace_path))]
        )
        narrator_stop: threading.Event | None = None
        narrator_thread: threading.Thread | None = None

        try:
            registry = ToolRegistry.with_default_tools()
            loop = KlaraLoop(
                llm=self.llm_client,
                tool_executor=ToolExecutor(list(registry.visible_tools())),
                hooks=hooks,
                policy=self.loop_policy,
                model=selected_model,
                system_prompt=_system_prompt(self.user_context),
            )
            narrator_stop, narrator_thread = self._start_live_activity_narrator(
                run_id=run_id,
                user_request=user_message.content,
                selected_model=selected_model,
                started=started,
            )
            model_visible_user_input = self._model_visible_content(user_message)
            result = loop.run(
                model_visible_user_input,
                run_id=run_id,
                prior_messages=self._conversation_history(
                    run.session_id,
                    before_message_id=user_message.message_id,
                ),
            )
            if run_id in self._cancel_requested:
                return

            self._stop_live_activity_narrator(narrator_stop, narrator_thread)
            summary = self._create_thinking_summary(
                run_id=run_id,
                user_request=user_message.content,
                selected_model=selected_model,
                duration_ms=int((perf_counter() - started) * 1000),
            )
            if summary is not None:
                self._emit(
                    run_id,
                    "thinking_summary_delta",
                    "Thinking summary generated.",
                    {
                        "text": summary.summary,
                        "items": list(summary.items),
                        "source": "narrator_model",
                        "evidence_event_ids": list(summary.evidence_event_ids),
                        "confidence": summary.confidence,
                    },
                )
            thinking_duration_ms = int((perf_counter() - started) * 1000)
            self._emit(
                run_id,
                "thinking_summary_completed",
                "Thinking summary completed.",
                {
                    "duration_ms": thinking_duration_ms,
                    "has_summary": summary is not None,
                },
            )
            final_text = result.final_answer
            self._emit(run_id, "answer_streaming_started", "Klara is writing the final answer.", {})
            self.store.update_message(assistant_message.model_copy(update={"content": final_text, "status": "running"}))
            self._emit(run_id, "answer_delta", "", {"delta": final_text, "streamed_chars": len(final_text)})

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
            self._stop_live_activity_narrator(narrator_stop, narrator_thread)
            latency_ms = int((perf_counter() - started) * 1000)
            error = RunError(code=_error_code(exc), message=str(exc), stage="runtime_loop")
            failed = current.model_copy(update={"status": "failed", "completed_at": now_iso(), "latency_ms": latency_ms, "error": error})
            self.store.save_run(failed)
            self.store.update_message(assistant_message.model_copy(update={"status": "failed"}))
            self._emit(run_id, "run_failed", "Run failed.", {"error": error.model_dump(mode="json")})
        finally:
            self._stop_live_activity_narrator(narrator_stop, narrator_thread)
            self._cleanup_run_runtime(run_id)

    def _emit(
        self,
        run_id: str,
        event_type,
        message: str,
        payload: dict[str, Any],
    ) -> RunEventRecord:
        """Persist and publish one API-level run event."""

        event = RunEventRecord(run_id=run_id, event_type=event_type, message=message, payload=payload)
        self.store.append_event(event)
        self.bus.publish(event)
        self._emit_projected_provider_reasoning(event)
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

    def _start_live_activity_narrator(
        self,
        *,
        run_id: str,
        user_request: str,
        selected_model: str,
        started: float,
    ) -> tuple[threading.Event | None, threading.Thread | None]:
        """Start the optional fact-bound public activity narrator."""

        if (
            not self.enable_workstream_narrator
            or self.narrator_client is None
            or not self.narrator_model
        ):
            return None, None

        stop_event = threading.Event()
        narrator = ThinkingActivityNarrator(
            client=self.narrator_client,
            model=self.narrator_model,
        )
        last_fact_ids: tuple[str, ...] = ()
        last_signature = ""

        def emit_once() -> bool:
            nonlocal last_fact_ids, last_signature
            try:
                events = tuple(self.store.list_events(run_id))
                facts = _narratable_activity_facts(_activity_facts_from_events(events))
                fact_ids = tuple(
                    str(fact.get("id"))
                    for fact in facts
                    if isinstance(fact.get("id"), str)
                )
                if not fact_ids or fact_ids == last_fact_ids:
                    return False
                self._emit(
                    run_id,
                    "narrator_started",
                    "Activity narrator started.",
                    {
                        "phase": "live",
                        "fact_count": len(facts),
                    },
                )
                summary = narrator.create_summary(
                    ThinkingActivityInput(
                        user_request=user_request,
                        selected_model=selected_model,
                        run_status="thinking",
                        duration_ms=int((perf_counter() - started) * 1000),
                        events=events,
                        activity_facts=facts,
                    )
                )
            except Exception as exc:
                if "fact_ids" in locals():
                    last_fact_ids = fact_ids
                self._emit(
                    run_id,
                    "narrator_failed",
                    "Activity narrator failed.",
                    {
                        "phase": "live",
                        "code": _error_code(exc),
                        "message": _safe_error_message(exc),
                    },
                )
                return False
            if summary is None:
                last_fact_ids = fact_ids
                self._emit(
                    run_id,
                    "narrator_rejected",
                    "Activity narrator output rejected.",
                    {
                        "phase": "live",
                        "reason": narrator.last_rejection_reason
                        or "unknown_validation_failure",
                        "fact_count": len(facts),
                    },
                )
                return False
            signature = _activity_items_signature(summary.items)
            if not signature or signature == last_signature:
                last_fact_ids = fact_ids
                return False
            if stop_event.is_set():
                return False
            last_fact_ids = fact_ids
            last_signature = signature
            self._emit(
                run_id,
                "thinking_summary_delta",
                "Thinking activity updated.",
                {
                    "text": summary.summary,
                    "items": list(summary.items),
                    "source": "narrator_model",
                    "phase": "live",
                    "evidence_event_ids": list(summary.evidence_event_ids),
                    "confidence": summary.confidence,
                },
            )
            self._emit(
                run_id,
                "narrator_completed",
                "Activity narrator completed.",
                {
                    "phase": "live",
                    "item_count": len(summary.items),
                    "fact_count": len(facts),
                },
            )
            return True

        def worker() -> None:
            while not stop_event.wait(1.0):
                emit_once()

        thread = threading.Thread(target=worker, daemon=True)
        thread.start()
        return stop_event, thread

    def _stop_live_activity_narrator(
        self,
        stop_event: threading.Event | None,
        thread: threading.Thread | None,
    ) -> None:
        """Stop the optional live activity narrator without blocking the run."""

        if stop_event is not None:
            stop_event.set()
        if thread is not None and thread.is_alive():
            thread.join(timeout=0.2)

    def _create_thinking_summary(
        self,
        *,
        run_id: str,
        user_request: str,
        selected_model: str,
        duration_ms: int,
    ) -> ThinkingActivityResult | None:
        """Return an optional completed-run public activity summary."""

        if (
            not self.enable_workstream_narrator
            or self.narrator_client is None
            or not self.narrator_model
        ):
            return None
        try:
            events = tuple(self.store.list_events(run_id))
            facts = _narratable_activity_facts(_activity_facts_from_events(events))
            if not facts:
                self._emit(
                    run_id,
                    "narrator_rejected",
                    "Activity narrator output rejected.",
                    {
                        "phase": "completed",
                        "reason": "no_items",
                        "fact_count": 0,
                    },
                )
                return None
            narrator = ThinkingActivityNarrator(
                client=self.narrator_client,
                model=self.narrator_model,
            )
            self._emit(
                run_id,
                "narrator_started",
                "Activity narrator started.",
                {
                    "phase": "completed",
                    "fact_count": len(facts),
                },
            )
            summary = narrator.create_summary(
                ThinkingActivityInput(
                    user_request=user_request,
                    selected_model=selected_model,
                    run_status="completed",
                    duration_ms=duration_ms,
                    events=events,
                    activity_facts=facts,
                )
            )
            if summary is None:
                self._emit(
                    run_id,
                    "narrator_rejected",
                    "Activity narrator output rejected.",
                    {
                        "phase": "completed",
                        "reason": narrator.last_rejection_reason
                        or "unknown_validation_failure",
                        "fact_count": len(facts),
                    },
                )
                return None
            self._emit(
                run_id,
                "narrator_completed",
                "Activity narrator completed.",
                {
                    "phase": "completed",
                    "item_count": len(summary.items),
                    "fact_count": len(facts),
                },
            )
            return summary
        except Exception as exc:
            self._emit(
                run_id,
                "narrator_failed",
                "Activity narrator failed.",
                {
                    "phase": "completed",
                    "code": _error_code(exc),
                    "message": _safe_error_message(exc),
                },
            )
            return None

    def _cleanup_run_runtime(self, run_id: str) -> None:
        """Remove per-run cancellation and thread bookkeeping."""

        self._cancel_requested.discard(run_id)
        self._threads.pop(run_id, None)

    def _select_model(self, requested_model: str | None) -> str | None:
        """Validate the requested model against the configured local registry."""

        model = requested_model or self.default_model
        if model and self.allowed_models and model not in self.allowed_models:
            raise ValueError("model_not_allowed")
        return model

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
            if message.status != "completed" or not message.content.strip():
                continue
            if message.role not in {"user", "assistant"}:
                continue
            history.append(
                KlaraMessage(
                    role=message.role,
                    content=self._model_visible_content(message),
                )
            )
        return prepare_conversation_history(history, max_messages=MAX_HISTORY_MESSAGES)

    def _model_visible_content(self, message: MessageRecord) -> str:
        """Return stored message text translated for the model boundary."""

        if message.role != "user":
            return message.content
        return stamp_user_message_content(
            message.content,
            created_at=message.created_at,
            timezone_name=self.user_context.timezone,
        )


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


def _system_prompt(user_context: UserContext) -> str:
    """Build the app prompt while keeping persona outside core."""

    persona = (Path("src") / "klara" / "prompts" / "persona.md").read_text(encoding="utf-8")
    return build_system_prompt(persona=persona, timezone_name=user_context.timezone)


def _activity_facts_from_events(
    events: tuple[RunEventRecord, ...],
) -> tuple[dict[str, Any], ...]:
    """Return all structured activity facts recorded for this run."""

    facts: list[dict[str, Any]] = []
    for event in events:
        if event.event_type != "activity_fact_recorded":
            continue
        fact = event.payload.get("fact")
        if isinstance(fact, dict):
            facts.append(dict(fact))
    return tuple(facts)


def _narratable_activity_facts(
    facts: tuple[dict[str, Any], ...],
) -> tuple[dict[str, Any], ...]:
    """Return only facts meaningful enough for public activity narration."""

    return tuple(fact for fact in facts if _is_narratable_activity_fact(fact))


def _activity_items_signature(items: tuple[dict[str, Any], ...]) -> str:
    """Return a stable signature for public activity items."""

    try:
        return json.dumps(
            [
                {
                    "title": item.get("title"),
                    "body": item.get("body"),
                    "evidence_fact_ids": item.get("evidence_fact_ids"),
                }
                for item in items
            ],
            ensure_ascii=False,
            sort_keys=True,
        )
    except TypeError:
        return ""


def _is_narratable_activity_fact(fact: dict[str, Any]) -> bool:
    """Return whether a structured fact represents real middle work."""

    kind = str(fact.get("kind") or "")
    if kind in {
        "request_orientation",
        "tool_call",
        "tool_result",
        "web_search_result",
        "web_fetch_result",
        "image_generation",
        "error",
        "policy_stop",
    }:
        return True
    if kind != "llm_round":
        return False
    llm = fact.get("llm")
    if not isinstance(llm, dict):
        return False
    tool_call_count = llm.get("tool_call_count")
    return isinstance(tool_call_count, int) and tool_call_count > 0


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
    """Return a compact language hint for narrator output matching."""

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
    text = str(exc).lower()
    if "api_key" in text or "api key" in text or "missing api key" in text:
        return "missing_api_key"
    if "provider http" in text or "provider request" in text:
        return "provider_error"
    return "run_failed"


def _safe_error_message(exc: Exception) -> str:
    """Return a debug-safe error string for narrator diagnostics."""

    message = " ".join(str(exc).split())
    message = re.sub(r"https?://\S+", "[url]", message)
    message = re.sub(r"\bsk-[A-Za-z0-9_-]{12,}\b", "sk-[redacted]", message)
    return message[:180]
