from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def test_visual_retrieval_returns_rendered_asset():
    result = AgenticRAGRuntime().run("Explain figure aware RAG in Chinese, include figure", save_trace=False)
    assert result.answer_frame.visual_sources
    assert result.answer_frame.rendered_assets[0]["image_path"]
