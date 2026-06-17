from agent_ladder.knowledge.paper.indexing import build_indexes


def test_index_builder_returns_expected_indexes():
    indexes = build_indexes("data/papers")
    assert "paper_overview_index" in indexes
    assert indexes["paper_chunk_index"]["rows"]
    assert "paper_visual_caption_index" in indexes
