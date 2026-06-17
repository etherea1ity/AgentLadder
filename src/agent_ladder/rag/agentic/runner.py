from __future__ import annotations

from collections.abc import Callable
from time import perf_counter
from typing import Any, TypeVar

from pydantic import BaseModel

from agent_ladder.rag.contracts.agentic import DecisionRecord
from agent_ladder.rag.agentic.trace import DecisionTracer

TIn = TypeVar("TIn", bound=BaseModel)
TOut = TypeVar("TOut", bound=BaseModel)


class WorkerAgentRunner:
    """Run a controlled one-shot worker with Pydantic validation."""

    def __init__(self, tracer: DecisionTracer | None = None) -> None:
        self.tracer = tracer or DecisionTracer()

    def run(self, *, worker_id: str, input_model: TIn, output_type: type[TOut], worker: Callable[[TIn], TOut | dict[str, Any]]) -> TOut:
        started = perf_counter()
        try:
            validated_input = type(input_model).model_validate(input_model.model_dump(mode="json"))
            raw = worker(validated_input)
            output = raw if isinstance(raw, output_type) else output_type.model_validate(raw)
            latency = int((perf_counter() - started) * 1000)
            self.tracer.record(node_name=worker_id, decision_type="worker_call", reason="worker output validated", input_summary=type(input_model).__name__, output_summary=output_type.__name__, latency_ms=latency)
            return output
        except Exception as exc:
            latency = int((perf_counter() - started) * 1000)
            self.tracer.record(node_name=worker_id, decision_type="worker_error", reason=str(exc), input_summary=type(input_model).__name__, output_summary=output_type.__name__, latency_ms=latency, error=str(exc))
            raise


class NodeRunner:
    def __init__(self, tracer: DecisionTracer | None = None) -> None:
        self.tracer = tracer or DecisionTracer()

    def run(self, node_name: str, fn: Callable[[], TOut]) -> TOut:
        started = perf_counter()
        try:
            result = fn()
            self.tracer.record(node_name=node_name, decision_type="node_completed", reason="node completed", latency_ms=int((perf_counter() - started) * 1000))
            return result
        except Exception as exc:
            self.tracer.record(node_name=node_name, decision_type="node_failed", reason=str(exc), latency_ms=int((perf_counter() - started) * 1000), error=str(exc))
            raise
