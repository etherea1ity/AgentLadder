from agent_ladder.rag.agentic.normalizer import normalize_request
from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_plain_react_query_maps_to_react_paper_evidence():
    request = normalize_request("tell me about react")
    assert "reasoning acting language models" in request.canonical_query_en.lower()

    result = AgenticRAGRuntime(paper_root="data/papers").run("tell me about react", save_trace=False)
    titles = [source.title for source in result.answer_frame.sources]
    assert any("ReAct: Synergizing Reasoning and Acting" in title for title in titles)
    assert "Klara" in result.answer_frame.final_text
    assert "Core evidence" in result.answer_frame.final_text or "核心证据" in result.answer_frame.final_text
