from agent_ladder.rag.agentic.normalizer import normalize_request


def test_language_plan_explicit_overrides_input_language():
    assert normalize_request("Explain ReAct in Chinese.").language_plan.output_language == "zh"
    spec = normalize_request("用英文解释 Self-RAG。")
    assert spec.language_plan.output_language == "en"
    assert spec.language_plan.explicit_output_language is True
