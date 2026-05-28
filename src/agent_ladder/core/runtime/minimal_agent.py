from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from agent_ladder.core.contracts.answer import AnswerState
from agent_ladder.core.contracts.ask import AskState
from agent_ladder.core.contracts.run import RunLog
from agent_ladder.core.runtime.lifecycle import (
    FAILED_ANSWER_TEXT,
    build_answer_state,
    build_run_log,
    usage_or_estimate,
)
from agent_ladder.core.tracing.jsonl_tracer import JsonlTracer
from agent_ladder.llm.base import BaseLLMClient
from agent_ladder.llm.prompts.minimal import build_minimal_agent_messages


@dataclass(frozen=True)
class MinimalAgentResult:
    ask: AskState
    answer: AnswerState
    run: RunLog


class MinimalAgent:
    """Smallest useful agent: ask a question, call an LLM, record the run."""

    def __init__(self, llm_client: BaseLLMClient, tracer: JsonlTracer | None = None) -> None:
        self.llm_client = llm_client
        self.tracer = tracer

    def ask(self, question: str, language: str = "auto") -> MinimalAgentResult:
        ask = AskState(question=question, language=language)
        started_at = perf_counter()

        messages = build_minimal_agent_messages(ask.question)

        try:
            llm_response = self.llm_client.chat(messages=messages)
            latency_ms = int((perf_counter() - started_at) * 1000)
            answer_text = llm_response.content
            answer = build_answer_state(
                ask_id=ask.ask_id,
                answer_text=answer_text,
                model=llm_response.model,
            )
            usage = usage_or_estimate(
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
                messages=messages,
                answer_text=answer.answer,
            )
            run = build_run_log(
                ask_id=ask.ask_id,
                model=llm_response.model,
                latency_ms=latency_ms,
                usage=usage,
            )
        except Exception as error:
            latency_ms = int((perf_counter() - started_at) * 1000)
            answer = AnswerState(
                ask_id=ask.ask_id,
                answer=FAILED_ANSWER_TEXT,
                model="unknown",
            )
            run = build_run_log(
                ask_id=ask.ask_id,
                model="unknown",
                latency_ms=latency_ms,
                error=str(error),
            )
            if self.tracer is not None:
                self.tracer.save(ask=ask, answer=answer, run=run, prompt_messages=messages)
            raise

        if self.tracer is not None:
            self.tracer.save(ask=ask, answer=answer, run=run, prompt_messages=messages, usage=run.usage)

        return MinimalAgentResult(ask=ask, answer=answer, run=run)
