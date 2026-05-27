from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from agent_ladder.core.contracts.answer import AnswerState
from agent_ladder.core.contracts.ask import AskState
from agent_ladder.core.contracts.run import RunLog
from agent_ladder.core.contracts.usage import TokenUsage
from agent_ladder.core.tracing.jsonl_tracer import JsonlTracer
from agent_ladder.llm.base import BaseLLMClient
from agent_ladder.llm.prompts.minimal import build_minimal_agent_messages
from agent_ladder.llm.token_count import estimate_messages_tokens, estimate_text_tokens

from apps.api.schemas import (
    CreateRunResponse,
    MessageRecord,
    RunError,
    RunEventRecord,
    RunRecord,
    now_iso,
)
from apps.api.services.app_store import JsonlAppStore
from apps.api.services.sse_bus import SSEBus


class RunService:
    def __init__(
        self,
        store: JsonlAppStore,
        bus: SSEBus,
        llm_client: BaseLLMClient,
        trace_path: str = "data/traces/runs.jsonl",
        llm_client_factory: Callable[[str | None], BaseLLMClient] | None = None,
        allowed_models: set[str] | None = None,
        default_model: str | None = None,
    ) -> None:
        self.store = store
        self.bus = bus
        self.llm_client = llm_client
        self.llm_client_factory = llm_client_factory
        self.allowed_models = allowed_models or set()
        self.default_model = default_model
        self.trace_path = trace_path
        self._cancel_requested: set[str] = set()
        self._threads: dict[str, threading.Thread] = {}

    def create_run(self, session_id: str, question: str, model: str | None = None) -> CreateRunResponse:
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
        for run in self.store.list_runs(session_id):
            if run.status not in {"completed", "failed", "cancelled"}:
                self.cancel_run(run.run_id)

    def _run_thread(self, run_id: str) -> None:
        started = perf_counter()
        run = self.store.get_run(run_id)
        if run is None:
            return
        user_message = self.store.get_message(run.user_message_id)
        assistant_message = self.store.get_message(run.assistant_message_id)
        if user_message is None or assistant_message is None:
            return

        llm_client = self._llm_for_model(run.model)
        ask = AskState(question=user_message.content)
        configured_model = getattr(getattr(llm_client, "config", None), "model", None)
        current = run.model_copy(update={"status": "thinking", "started_at": now_iso(), "model": run.model or configured_model or self.default_model})
        self.store.save_run(current)
        self._emit(run_id, "thinking_started", "Understanding your question...", {})
        self._emit(run_id, "llm_call_started", "Calling the language model...", {"model": current.model})

        answer_text = ""
        prompt_tokens = None
        completion_tokens = None
        model = current.model or "unknown"

        try:
            streaming_started = False
            messages = build_minimal_agent_messages(ask.question)
            estimated_prompt_tokens = estimate_messages_tokens(messages)
            for chunk in llm_client.stream_chat(messages):
                if run_id in self._cancel_requested:
                    return
                if chunk.model:
                    model = chunk.model
                if chunk.prompt_tokens is not None:
                    prompt_tokens = chunk.prompt_tokens
                if chunk.completion_tokens is not None:
                    completion_tokens = chunk.completion_tokens
                if chunk.done:
                    continue
                if chunk.delta:
                    if not streaming_started:
                        streaming_started = True
                        current = current.model_copy(update={"status": "streaming", "model": model})
                        self.store.save_run(current)
                        self._emit(run_id, "answer_streaming_started", "Answer is streaming...", {})
                    answer_text += chunk.delta
                    updated_message = assistant_message.model_copy(update={"content": answer_text, "status": "running"})
                    self.store.update_message(updated_message)
                    assistant_message = updated_message
                    self._emit(run_id, "answer_delta", "", {"delta": chunk.delta, "streamed_chars": len(answer_text)})

            latency_ms = int((perf_counter() - started) * 1000)
            answer = AnswerState(ask_id=ask.ask_id, answer=answer_text or "No answer was produced.", model=model)
            usage = _tokens_or_estimate(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_prompt_tokens=estimated_prompt_tokens,
                answer_text=answer_text,
            )
            prompt_tokens = usage.input_tokens or 0
            completion_tokens = usage.output_tokens or 0
            total_tokens = usage.total_tokens or prompt_tokens + completion_tokens
            run_log = RunLog(
                run_id=run_id,
                ask_id=ask.ask_id,
                model=model,
                latency_ms=latency_ms,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                token_source=usage.source,
            )
            JsonlTracer(Path(self.trace_path)).save(ask=ask, answer=answer, run=run_log, prompt_messages=messages, usage=usage)
            completed = current.model_copy(
                update={
                    "status": "completed",
                    "model": model,
                    "completed_at": now_iso(),
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "token_source": usage.source,
                    "trace_saved": True,
                }
            )
            self.store.save_run(completed)
            self.store.update_message(assistant_message.model_copy(update={"status": "completed", "content": answer_text}))
            self._emit(run_id, "llm_call_completed", "LLM call completed.", {"completion_tokens": completion_tokens})
            self._emit(
                run_id,
                "run_completed",
                "Run completed.",
                {
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": total_tokens,
                    "token_source": usage.source,
                    "trace_saved": True,
                },
            )
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            error = RunError(code=_error_code(exc), message=str(exc), stage="llm_call_started")
            failed = current.model_copy(update={"status": "failed", "completed_at": now_iso(), "latency_ms": latency_ms, "error": error})
            self.store.save_run(failed)
            self.store.update_message(assistant_message.model_copy(update={"status": "failed"}))
            self._emit(run_id, "run_failed", "Run failed.", {"error": error.model_dump(mode="json")})

    def _emit(self, run_id: str, event_type, message: str, payload: dict) -> None:
        event = RunEventRecord(run_id=run_id, event_type=event_type, message=message, payload=payload)
        self.store.append_event(event)
        self.bus.publish(event)

    def _select_model(self, requested_model: str | None) -> str | None:
        model = requested_model or self.default_model
        if model and self.allowed_models and model not in self.allowed_models:
            raise ValueError("model_not_allowed")
        return model

    def _llm_for_model(self, model: str | None) -> BaseLLMClient:
        if self.llm_client_factory is None:
            return self.llm_client
        return self.llm_client_factory(model)


def _title_from_question(question: str) -> str:
    text = " ".join(question.split())
    if not text:
        return "Untitled"
    title = " ".join(text.split()[:8])
    return title[:40]


def _error_code(exc: Exception) -> str:
    text = str(exc).lower()
    if "api_key" in text or "api key" in text or "dashscope_api_key" in text:
        return "missing_api_key"
    return "run_failed"


def _tokens_or_estimate(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    estimated_prompt_tokens: int,
    answer_text: str,
) -> TokenUsage:
    reported = prompt_tokens is not None and completion_tokens is not None
    return TokenUsage.from_provider_counts(
        prompt_tokens=prompt_tokens if prompt_tokens is not None else estimated_prompt_tokens,
        completion_tokens=completion_tokens if completion_tokens is not None else estimate_text_tokens(answer_text),
        source="reported" if reported else "estimated",
    )
