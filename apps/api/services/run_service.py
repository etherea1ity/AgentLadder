from __future__ import annotations

import json
import re
import threading
from pathlib import Path
from time import perf_counter, sleep
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
    project_assistant_activity,
    project_activity_fact,
    project_provider_reasoning,
)
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
from klara.services.web import WebResearchController
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
        thinking_support: dict[str, bool] | None = None,
        default_thinking: dict[str, bool] | None = None,
        default_model: str | None = None,
        loop_policy: LoopPolicy | None = None,
        user_context: UserContext | None = None,
        answer_chunking_enabled: bool = True,
        answer_chunk_delay_ms: int = 15,
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
        self.trace_path = trace_path
        self._cancel_requested: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}

    def create_run(
        self,
        session_id: str,
        question: str,
        model: str | None = None,
        thinking_enabled: bool | None = None,
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

        user_message = MessageRecord(session_id=session_id, role="user", content=question, status="completed")
        self.store.save_message(user_message)

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
        selected_model = current.model or self.default_model or "fake-model"
        thinking_enabled = current.thinking_enabled
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
        hooks = HookManager(
            [RunProjectionHook(self, run_id, projector), JsonlTraceHook(Path(self.trace_path))]
        )

        try:
            registry = ToolRegistry.with_default_tools()
            loop = KlaraLoop(
                llm=self.llm_client,
                tool_executor=ToolExecutor(list(registry.visible_tools())),
                hooks=hooks,
                policy=self.loop_policy,
                controllers=(
                    WebResearchController(user_timezone=self.user_context.timezone),
                ),
                model=selected_model,
                thinking_enabled=thinking_enabled,
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
            self._emit(run_id, "answer_streaming_started", "Klara is writing the final answer.", {})
            self._stream_answer_chunks(
                run_id=run_id,
                assistant_message=assistant_message,
                final_text=final_text,
            )

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
            latency_ms = int((perf_counter() - started) * 1000)
            error = RunError(code=_error_code(exc), message=str(exc), stage="runtime_loop")
            failed = current.model_copy(update={"status": "failed", "completed_at": now_iso(), "latency_ms": latency_ms, "error": error})
            self.store.save_run(failed)
            self.store.update_message(assistant_message.model_copy(update={"status": "failed"}))
            self._emit(run_id, "run_failed", "Run failed.", {"error": error.model_dump(mode="json")})
        finally:
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

        self._cancel_requested.discard(run_id)
        self._threads.pop(run_id, None)

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
    text = str(exc).lower()
    if "api_key" in text or "api key" in text or "missing api key" in text:
        return "missing_api_key"
    if "provider http" in text or "provider request" in text:
        return "provider_error"
    return "run_failed"
