from agent_ladder.core.contracts.answer import AnswerState
from agent_ladder.core.contracts.ask import AskState
from agent_ladder.core.contracts.run import RunLog
from agent_ladder.core.contracts.usage import TokenUsage
from agent_ladder.llm.prompts.minimal import build_minimal_agent_messages
from agent_ladder.llm.token_count import estimate_messages_tokens, estimate_text_tokens


def test_core_contracts_generate_ids_and_validate_text():
    ask = AskState(question=" What is an AI Agent? ")
    answer = AnswerState(ask_id=ask.ask_id, answer="An answer", model="qwen3.6-plus")
    usage = TokenUsage(input_tokens=3, output_tokens=4, source="reported")
    run = RunLog(ask_id=ask.ask_id, model=answer.model, latency_ms=10, prompt_tokens=usage.input_tokens, completion_tokens=usage.output_tokens, token_source=usage.source)

    assert ask.ask_id.startswith("ask_")
    assert ask.question == "What is an AI Agent?"
    assert answer.ask_id == ask.ask_id
    assert run.run_id.startswith("run_")
    assert run.total_tokens == 7
    assert run.usage.input_tokens == 3
    assert run.usage.output_tokens == 4
    assert run.usage.source == "reported"


def test_token_estimator_handles_english_chinese_and_math():
    assert estimate_text_tokens("What is an AI Agent?") > 0
    assert estimate_text_tokens("傅里叶变换") >= 5
    assert estimate_text_tokens(r"F(\omega)=\int f(t)e^{-j\omega t}dt") > 5
    assert estimate_messages_tokens([{"role": "user", "content": "你好"}]) > estimate_text_tokens("你好")


def test_minimal_prompt_builder_keeps_system_and_user_messages():
    messages = build_minimal_agent_messages("What is an AI Agent?")

    assert [message["role"] for message in messages] == ["system", "user"]
    assert "Klara" in messages[0]["content"]
    assert "Markdown" in messages[0]["content"]
    assert "sunlight" in messages[0]["content"]
    assert "raw chain-of-thought" in messages[0]["content"]
    assert messages[1]["content"] == "What is an AI Agent?"
