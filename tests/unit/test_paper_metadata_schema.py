from agent_ladder.knowledge.paper.schema import PaperMetadata


def test_metadata_schema_accepts_processing_quality():
    meta = PaperMetadata(paper_id="paper_x", title="X", processing={"chunks_generated": True}, quality={"chunk_count": 1})
    assert meta.quality["chunk_count"] == 1
