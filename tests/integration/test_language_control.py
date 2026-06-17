from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_language_control_chinese_input_english_output():
    result = AgenticRAGRuntime().run("用英文解释 Self-RAG。", save_trace=False)
    assert result.state.request.language_plan.output_language == "en"
    assert "Based on" in result.answer_frame.final_text or "insufficient" in result.answer_frame.final_text
