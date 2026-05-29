from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path
from time import perf_counter

from agent_ladder.core.contracts.ask import AskState
from agent_ladder.core.runtime.klara_agent import KlaraAgent, KlaraRunPreparation
from agent_ladder.core.runtime.lifecycle import (
    build_answer_state,
    build_run_log,
    final_answer_text,
    usage_or_estimate,
)
from agent_ladder.core.tracing.jsonl_tracer import JsonlTracer
from agent_ladder.llm.base import BaseLLMClient
from agent_ladder.llm.token_count import estimate_messages_tokens

from apps.api.schemas import (
    CreateRunResponse,
    MessageRecord,
    RunError,
    RunEventRecord,
    RunRecord,
    now_iso,
)
from agent_ladder.rag.contracts.module import ModuleResult
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
        klara_agent: KlaraAgent | None = None,
    ) -> None:
        self.store = store
        self.bus = bus
        self.llm_client = llm_client
        self.llm_client_factory = llm_client_factory
        self.allowed_models = allowed_models or set()
        self.default_model = default_model
        self.klara_agent = klara_agent or KlaraAgent()
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
            self._cleanup_run_runtime(run_id)
            return
        user_message = self.store.get_message(run.user_message_id)
        assistant_message = self.store.get_message(run.assistant_message_id)
        if user_message is None or assistant_message is None:
            self._cleanup_run_runtime(run_id)
            return

        llm_client = self._llm_for_model(run.model)
        ask = AskState(question=user_message.content)
        configured_model = getattr(getattr(llm_client, "config", None), "model", None)
        current = run.model_copy(update={"status": "thinking", "started_at": now_iso(), "model": run.model or configured_model or self.default_model})
        self.store.save_run(current)
        self._emit(run_id, "thinking_started", "Understanding your question...", {})

        answer_text = ""
        prompt_tokens = None
        completion_tokens = None
        model = current.model or "unknown"
        preparation: KlaraRunPreparation | None = None
        writer_module: ModuleResult | None = None
        writer_done: ModuleResult | None = None

        try:
            preparation = self.klara_agent.prepare(
                ask.question,
                emit_module=lambda module: self._emit_module(run_id, module),
                router_client=llm_client,
            )
            writer_module = ModuleResult(
                module_id="klara_writer",
                module_name="KlaraAgent Writer",
                input_summary="Write the final answer from the route/context decision.",
                input_payload={
                    "route": preparation.route.route,
                    "context_token_estimate": preparation.built_context.token_estimate if preparation.built_context else 0,
                    "source_count": len(preparation.sources),
                },
            ).started()
            self._emit_module(run_id, writer_module)
            self._emit(run_id, "llm_call_started", "Calling the language model...", {"model": current.model})
            streaming_started = False
            messages = preparation.messages
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
            final_text = final_answer_text(answer_text)
            answer = build_answer_state(ask_id=ask.ask_id, answer_text=final_text, model=model)
            usage = usage_or_estimate(
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                estimated_prompt_tokens=estimated_prompt_tokens,
                answer_text=final_text,
            )
            prompt_count = usage.input_tokens or 0
            completion_count = usage.output_tokens or 0
            total_count = usage.total_tokens or prompt_count + completion_count
            run_log = build_run_log(
                run_id=run_id,
                ask_id=ask.ask_id,
                model=model,
                latency_ms=latency_ms,
                usage=usage,
            )
            answer_frame = self.klara_agent.answer_frame(
                answer=final_text,
                preparation=preparation,
                run_log={
                    "run_id": run_id,
                    "model": model,
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_count,
                    "completion_tokens": completion_count,
                    "total_tokens": total_count,
                    "token_source": usage.source,
                },
            ) if preparation is not None else None
            if writer_module is not None:
                writer_done = writer_module.completed(
                    output_summary=f"Generated answer with {completion_count} output tokens.",
                    output_payload={
                        "route": preparation.route.route if preparation else "direct",
                        "prompt_tokens": prompt_count,
                        "completion_tokens": completion_count,
                        "total_tokens": total_count,
                        "token_source": usage.source,
                        "used_chunks": preparation.used_chunks if preparation else [],
                        "source_count": len(preparation.sources) if preparation else 0,
                        "prompt_messages": messages,
                        "answer_frame": answer_frame.model_dump(mode="json") if answer_frame else None,
                    },
                )
                self._emit_module(run_id, writer_done)
            trace_modules = [*(preparation.modules if preparation else [])]
            if writer_done is not None:
                trace_modules.append(writer_done)
            trace_extra = {
                "route": preparation.route.model_dump(mode="json") if preparation else None,
                "modules": [module.model_dump(mode="json") for module in trace_modules],
                "answer_frame": answer_frame.model_dump(mode="json") if answer_frame else None,
            }
            if preparation is not None and preparation.route.route == "rag":
                trace_extra["schema_version"] = "v0.2"
            JsonlTracer(Path(self.trace_path)).save(
                ask=ask,
                answer=answer,
                run=run_log,
                prompt_messages=messages,
                usage=usage,
                extra=trace_extra,
            )
            completed = current.model_copy(
                update={
                    "status": "completed",
                    "model": model,
                    "completed_at": now_iso(),
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_count,
                    "completion_tokens": completion_count,
                    "total_tokens": total_count,
                    "token_source": usage.source,
                    "trace_saved": True,
                }
            )
            self.store.save_run(completed)
            self.store.update_message(assistant_message.model_copy(update={"status": "completed", "content": final_text}))
            self._emit(
                run_id,
                "llm_call_completed",
                "LLM call completed.",
                {
                    "prompt_tokens": prompt_count,
                    "completion_tokens": completion_count,
                    "total_tokens": total_count,
                    "token_source": usage.source,
                },
            )
            self._emit(
                run_id,
                "run_completed",
                "Run completed.",
                {
                    "latency_ms": latency_ms,
                    "prompt_tokens": prompt_count,
                    "completion_tokens": completion_count,
                    "total_tokens": total_count,
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
        finally:
            self._cleanup_run_runtime(run_id)

    def _emit(self, run_id: str, event_type, message: str, payload: dict) -> None:
        event = RunEventRecord(run_id=run_id, event_type=event_type, message=message, payload=payload)
        self.store.append_event(event)
        self.bus.publish(event)

    def _emit_module(self, run_id: str, module: ModuleResult) -> None:
        event_type = "module_failed" if module.status == "failed" else "module_completed" if module.status in {"completed", "skipped"} else "module_started"
        self._emit(run_id, event_type, module.output_summary or module.input_summary or module.module_name, {"module_result": module.model_dump(mode="json")})

    def _cleanup_run_runtime(self, run_id: str) -> None:
        self._cancel_requested.discard(run_id)
        self._threads.pop(run_id, None)

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
