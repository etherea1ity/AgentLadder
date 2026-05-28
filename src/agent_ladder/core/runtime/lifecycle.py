from __future__ import annotations

from agent_ladder.core.contracts.answer import AnswerState
from agent_ladder.core.contracts.run import RunLog
from agent_ladder.core.contracts.usage import TokenUsage
from agent_ladder.llm.base import Message
from agent_ladder.llm.token_count import estimate_messages_tokens, estimate_text_tokens

NO_ANSWER_TEXT = "No answer was produced."
FAILED_ANSWER_TEXT = "No answer was produced because the run failed."


def final_answer_text(answer_text: str | None, *, failed: bool = False) -> str:
    """Return the canonical user-visible answer text for empty/failed runs."""
    text = (answer_text or "").strip()
    if text:
        return answer_text or text
    return FAILED_ANSWER_TEXT if failed else NO_ANSWER_TEXT


def usage_or_estimate(
    *,
    prompt_tokens: int | None,
    completion_tokens: int | None,
    messages: list[Message] | None = None,
    estimated_prompt_tokens: int | None = None,
    answer_text: str,
) -> TokenUsage:
    """Prefer provider-reported usage; otherwise estimate input/output tokens."""
    reported = prompt_tokens is not None and completion_tokens is not None
    input_tokens = prompt_tokens
    if input_tokens is None:
        input_tokens = estimated_prompt_tokens
    if input_tokens is None and messages is not None:
        input_tokens = estimate_messages_tokens(messages)

    output_tokens = completion_tokens
    if output_tokens is None:
        output_tokens = estimate_text_tokens(answer_text)

    return TokenUsage.from_provider_counts(
        prompt_tokens=input_tokens,
        completion_tokens=output_tokens,
        source="reported" if reported else "estimated",
    )


def build_answer_state(*, ask_id: str, answer_text: str, model: str) -> AnswerState:
    return AnswerState(ask_id=ask_id, answer=final_answer_text(answer_text), model=model)


def build_run_log(
    *,
    run_id: str | None = None,
    ask_id: str,
    model: str,
    latency_ms: int | None,
    usage: TokenUsage | None = None,
    error: str | None = None,
) -> RunLog:
    payload = {
        "ask_id": ask_id,
        "model": model,
        "latency_ms": latency_ms,
        "prompt_tokens": usage.input_tokens if usage else None,
        "completion_tokens": usage.output_tokens if usage else None,
        "total_tokens": usage.total_tokens if usage else None,
        "token_source": usage.source if usage else "unknown",
        "error": error,
    }
    if run_id is not None:
        payload["run_id"] = run_id
    return RunLog(**payload)
