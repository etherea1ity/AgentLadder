from pathlib import Path
from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_real_visual_query_returns_caption_and_existing_image_when_present():
    result = AgenticRAGRuntime(paper_root="data/papers").run("Explain figure-aware RAG in Chinese, include figure", save_trace=False)
    assert any(a.provider_id == "paper_visual_caption" for a in result.state.retrieval_attempts if a.stage == "search")
    assert result.answer_frame.visual_sources
    visual = result.answer_frame.visual_sources[0]
    assert visual.caption
    if visual.image_path:
        assert Path(visual.image_path).exists()
    assert result.answer_frame.evidence_items[0].evidence_type in {"figure", "table", "equation", "page_image", "text"}
