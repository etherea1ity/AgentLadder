import re
from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_english_query_chinese_output():
    result = AgenticRAGRuntime(paper_root="data/papers").run("Explain Self-RAG in Chinese.", save_trace=False)
    assert result.state.request.language_plan.output_language == "zh"
    assert re.search(r"[\u4e00-\u9fff]", result.answer_frame.final_text)


def test_chinese_query_english_output():
    result = AgenticRAGRuntime(paper_root="data/papers").run("用英文解释 Self-RAG。", save_trace=False)
    assert result.state.request.language_plan.output_language == "en"
    assert not re.search(r"[\u4e00-\u9fff]", result.answer_frame.final_text)


def test_chinese_query_defaults_to_chinese_with_english_canonical():
    result = AgenticRAGRuntime(paper_root="data/papers").run("Agentic RAG 是什么？", save_trace=False)
    assert result.state.request.language_plan.output_language == "zh"
    assert result.state.request.language_plan.canonical_query_language == "en"
