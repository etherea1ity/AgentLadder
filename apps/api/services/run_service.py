from __future__ import annotations

import os
import threading
from collections.abc import Callable
from time import perf_counter

from agent_ladder.llm.base import BaseLLMClient

from apps.api.schemas import (
    CreateRunResponse,
    MessageRecord,
    RunError,
    RunEventRecord,
    RunRecord,
    now_iso,
)
from agent_ladder.rag.contracts.module import ModuleResult
from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime
from agent_ladder.rag.agentic.trace import save_workflow_trace
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
            self._cleanup_run_runtime(run_id)
            return
        user_message = self.store.get_message(run.user_message_id)
        assistant_message = self.store.get_message(run.assistant_message_id)
        if user_message is None or assistant_message is None:
            self._cleanup_run_runtime(run_id)
            return

        self._run_v03_thread(
            run_id=run_id,
            started=started,
            run=run,
            user_message=user_message,
            assistant_message=assistant_message,
        )
        return

    def _run_v03_thread(
        self,
        *,
        run_id: str,
        started: float,
        run: RunRecord,
        user_message: MessageRecord,
        assistant_message: MessageRecord,
    ) -> None:
        current = run.model_copy(update={"status": "thinking", "started_at": now_iso(), "model": "klara-v0.3-runtime"})
        self.store.save_run(current)
        self._emit(run_id, "thinking_started", "Klara is normalizing the ask request...", {})

        try:
            runtime = AgenticRAGRuntime(trace_path=self.trace_path, paper_root=os.getenv("AGENT_LADDER_PAPER_ROOT", "data/papers"))
            self._emit_module(
                run_id,
                ModuleResult(
                    module_id="klara_v03_runtime",
                    module_name="Klara v0.3 Ask Runtime",
                    status="running",
                    input_summary="Run bounded local evidence search.",
                    output_summary="Normalize → plan → search/fetch across local domains → EvidencePack → write → verify",
                    input_payload={"question": user_message.content, "paper_root": str(runtime.paper_root)},
                ).started(),
            )
            result = runtime.run(user_message.content, save_trace=False)
            state = result.state.model_copy(update={"workflow_id": run_id})
            frame = result.answer_frame
            verification_status = state.verification.status if state.verification else "unknown"
            search_units_count = len(state.search_plan.search_units) if state.search_plan else 0
            retrieval_attempts_count = len(state.retrieval_attempts)
            evidence_items_count = len(state.evidence_pack.items) if state.evidence_pack else 0

            for decision in state.decisions:
                self._emit_module(
                    run_id,
                    ModuleResult(
                        module_id=f"klara_v03_{decision.node_name}",
                        module_name=f"Klara v0.3 · {decision.node_name}",
                        status="completed",
                        input_summary=decision.input_summary or decision.decision_type,
                        output_summary=decision.output_summary or decision.reason,
                        output_payload=decision.model_dump(mode="json"),
                    ).completed(output_summary=decision.output_summary or decision.reason),
                )

            self._emit(
                run_id,
                "answer_streaming_started",
                "Klara is writing from the verified EvidencePack...",
                {},
            )
            final_text = frame.final_text
            if run_id in self._cancel_requested:
                return
            self.store.update_message(assistant_message.model_copy(update={"content": final_text, "status": "running"}))
            self._emit(run_id, "answer_delta", "", {"delta": final_text, "streamed_chars": len(final_text)})

            save_workflow_trace(self.trace_path, state, question=user_message.content, final_text=final_text, latency_ms=result.latency_ms)
            self._emit(
                run_id,
                "trace_saved",
                "Decision trace saved.",
                {"trace_saved": True, "schema_version": "v0.3"},
            )

            completed = current.model_copy(
                update={
                    "status": "completed",
                    "completed_at": now_iso(),
                    "latency_ms": result.latency_ms,
                    "prompt_tokens": 0,
                    "completion_tokens": len(final_text.split()),
                    "total_tokens": len(final_text.split()),
                    "token_source": "estimated",
                    "trace_saved": True,
                }
            )
            self.store.save_run(completed)
            self.store.update_message(assistant_message.model_copy(update={"status": "completed", "content": final_text}))
            self._emit_module(
                run_id,
                ModuleResult(
                    module_id="klara_v03_runtime",
                    module_name="Klara v0.3 Ask Runtime",
                    status="completed",
                    input_summary="Run bounded local evidence search.",
                    output_summary=f"{search_units_count} search units, {retrieval_attempts_count} retrieval attempts, {evidence_items_count} evidence items, verification={verification_status}.",
                    output_payload={
                        "route": state.route.route if state.route else "rag",
                        "run_mode": state.run_mode,
                        "search_units_count": search_units_count,
                        "retrieval_attempts_count": retrieval_attempts_count,
                        "evidence_items_count": evidence_items_count,
                        "verification_status": verification_status,
                        "source_count": len(frame.sources),
                        "visual_source_count": len(frame.visual_sources),
                        "answer_frame": frame.model_dump(mode="json"),
                    },
                ).completed(),
            )
            self._emit(
                run_id,
                "run_completed",
                "Run completed.",
                {
                    "latency_ms": result.latency_ms,
                    "prompt_tokens": 0,
                    "completion_tokens": len(final_text.split()),
                    "total_tokens": len(final_text.split()),
                    "token_source": "estimated",
                    "trace_saved": True,
                    "route": state.route.route if state.route else "rag",
                    "run_mode": state.run_mode,
                    "search_units_count": search_units_count,
                    "retrieval_attempts_count": retrieval_attempts_count,
                    "evidence_items_count": evidence_items_count,
                    "verification_status": verification_status,
                },
            )
        except Exception as exc:
            latency_ms = int((perf_counter() - started) * 1000)
            error = RunError(code=_error_code(exc), message=str(exc), stage="klara_v03_runtime")
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
