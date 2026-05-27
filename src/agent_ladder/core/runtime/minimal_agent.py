from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter

from agent_ladder.core.contracts.answer import AnswerState
from agent_ladder.core.contracts.ask import AskState
from agent_ladder.core.contracts.run import RunLog
from agent_ladder.core.contracts.usage import TokenUsage
from agent_ladder.core.tracing.jsonl_tracer import JsonlTracer
from agent_ladder.llm.base import BaseLLMClient
from agent_ladder.llm.prompts.minimal import build_minimal_agent_messages
from agent_ladder.llm.token_count import estimate_messages_tokens, estimate_text_tokens


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
            answer = AnswerState(
                ask_id=ask.ask_id,
                answer=llm_response.content,
                model=llm_response.model,
            )
            usage = _usage_or_estimate(
                prompt_tokens=llm_response.prompt_tokens,
                completion_tokens=llm_response.completion_tokens,
                messages=messages,
                answer_text=llm_response.content,
            )
            run = RunLog(
                ask_id=ask.ask_id,
                model=llm_response.model,
                latency_ms=latency_ms,
                prompt_tokens=usage.input_tokens,
                completion_tokens=usage.output_tokens,
                total_tokens=usage.total_tokens,
                token_source=usage.source,
            )
        except Exception as error:
            latency_ms = int((perf_counter() - started_at) * 1000)
            answer = AnswerState(
                ask_id=ask.ask_id,
                answer="No answer was produced because the run failed.",
                model="unknown",
            )
            run = RunLog(
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


def _usage_or_estimate(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    messages: list[dict[str, str]],
    answer_text: str,
) -> TokenUsage:
    reported = prompt_tokens is not None and completion_tokens is not None
    return TokenUsage.from_provider_counts(
        prompt_tokens=prompt_tokens if prompt_tokens is not None else estimate_messages_tokens(messages),
        completion_tokens=completion_tokens if completion_tokens is not None else estimate_text_tokens(answer_text),
        source="reported" if reported else "estimated",
    )
