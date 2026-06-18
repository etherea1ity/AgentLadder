from __future__ import annotations

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
from apps.api.services.sse_bus import SSEBus
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
        """

        self.store = store
        self.bus = bus
        self.llm_client = llm_client
        self.allowed_models = allowed_models or set()
        self.default_model = default_model
        self.loop_policy = loop_policy or LoopPolicy()
        self.user_context = user_context or UserContext.local_default()
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

        usage_totals = _UsageTotals()
        bridge = _RunEventBridge(self, run_id, usage_totals)
        hooks = HookManager([bridge, JsonlTraceHook(Path(self.trace_path))])

        try:
            registry = ToolRegistry.with_default_tools()
            loop = KlaraLoop(
                llm=self.llm_client,
                tool_executor=ToolExecutor(list(registry.visible_tools())),
                hooks=hooks,
                policy=self.loop_policy,
                model=current.model or self.default_model or "fake-model",
                system_prompt=_system_prompt(self.user_context),
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

            final_text = result.final_answer
            self._emit(run_id, "answer_streaming_started", "Klara is writing the final answer.", {})
            self.store.update_message(assistant_message.model_copy(update={"content": final_text, "status": "running"}))
            self._emit(run_id, "answer_delta", "", {"delta": final_text, "streamed_chars": len(final_text)})

            latency_ms = int((perf_counter() - started) * 1000)
            token_source: TokenSource = "reported" if usage_totals.has_reported else "unknown"
            completed = current.model_copy(
                update={
                    "status": "completed",
                    "completed_at": now_iso(),
                    "latency_ms": latency_ms,
                    "prompt_tokens": usage_totals.prompt_tokens,
                    "completion_tokens": usage_totals.completion_tokens,
                    "total_tokens": usage_totals.total_tokens,
                    "token_source": token_source,
                    "trace_saved": False,
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
                    "trace_saved": False,
                },
            )
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            error = RunError(code=_error_code(exc), message=str(exc), stage="runtime_loop")
            failed = current.model_copy(update={"status": "failed", "completed_at": now_iso(), "latency_ms": latency_ms, "error": error})
            self.store.save_run(failed)
            self.store.update_message(assistant_message.model_copy(update={"status": "failed"}))
            self._emit(run_id, "run_failed", "Run failed.", {"error": error.model_dump(mode="json")})
        finally:
            self._cleanup_run_runtime(run_id)

    def _emit(self, run_id: str, event_type, message: str, payload: dict[str, Any]) -> None:
        """Persist and publish one API-level run event."""

        event = RunEventRecord(run_id=run_id, event_type=event_type, message=message, payload=payload)
        self.store.append_event(event)
        self.bus.publish(event)

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


class _RunEventBridge:
    """Convert core lifecycle events into compact frontend-visible events."""

    def __init__(self, service: RunService, run_id: str, usage_totals: "_UsageTotals") -> None:
        """Create a bridge bound to one app run."""

        self.service = service
        self.run_id = run_id
        self.usage_totals = usage_totals

    def on_event(self, event: KlaraEvent) -> None:
        """Project selected core events into the SSE stream."""

        if event.type == "llm.started":
            self.service._emit(
                self.run_id,
                "llm_call_started",
                "Klara is calling the model.",
                {"turn_index": event.payload.get("turn_index")},
            )
            return
        if event.type == "llm.completed":
            usage = event.payload.get("usage") if isinstance(event.payload.get("usage"), dict) else {}
            self.usage_totals.add(usage)
            self.service._emit(
                self.run_id,
                "llm_call_completed",
                "Model call completed.",
                {
                    "turn_index": event.payload.get("turn_index"),
                    "tool_call_count": event.payload.get("tool_call_count"),
                    "usage": usage,
                    **_usage_payload(usage),
                },
            )
            return
        if event.type == "tool.started":
            tool_call = event.payload.get("tool_call") if isinstance(event.payload.get("tool_call"), dict) else {}
            name = str(tool_call.get("name") or "tool")
            self.service._emit(
                self.run_id,
                "tool_call_started",
                f"Klara is using {name}.",
                {"turn_index": event.payload.get("turn_index"), "tool_call": tool_call},
            )
            return
        if event.type == "tool.completed":
            tool_result = event.payload.get("tool_result") if isinstance(event.payload.get("tool_result"), dict) else {}
            name = str(tool_result.get("name") or "tool")
            self.service._emit(
                self.run_id,
                "tool_call_completed",
                f"{name} returned an observation.",
                {"turn_index": event.payload.get("turn_index"), "tool_result": tool_result},
            )


class _UsageTotals:
    """Accumulate provider token usage across loop turns."""

    def __init__(self) -> None:
        """Create an empty usage accumulator."""

        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.total_tokens = 0
        self.has_reported = False

    def add(self, usage: dict[str, Any]) -> None:
        """Add one provider usage payload when token fields are present."""

        payload = _usage_payload(usage)
        if any(value is not None for value in payload.values()):
            self.has_reported = True
        self.prompt_tokens += payload["prompt_tokens"] or 0
        self.completion_tokens += payload["completion_tokens"] or 0
        self.total_tokens += payload["total_tokens"] or 0


def _system_prompt(user_context: UserContext) -> str:
    """Build the app prompt while keeping persona outside core."""

    persona = (Path("src") / "klara" / "prompts" / "persona.md").read_text(encoding="utf-8")
    return build_system_prompt(persona=persona, timezone_name=user_context.timezone)


def _usage_payload(usage: dict[str, Any]) -> dict[str, int | None]:
    """Normalize common OpenAI-compatible usage field names."""

    prompt = _int_or_none(usage.get("prompt_tokens") or usage.get("input_tokens"))
    completion = _int_or_none(usage.get("completion_tokens") or usage.get("output_tokens"))
    total = _int_or_none(usage.get("total_tokens"))
    if total is None and (prompt is not None or completion is not None):
        total = (prompt or 0) + (completion or 0)
    return {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": total}


def _int_or_none(value: Any) -> int | None:
    """Return an integer token count when the value is numeric."""

    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    return None


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
