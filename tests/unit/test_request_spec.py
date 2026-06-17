from agent_ladder.rag.agentic.normalizer import normalize_request
from agent_ladder.rag.contracts.agentic import RequestSpec


def test_request_spec_serializes_roundtrip():
    spec = normalize_request("给我 10 篇 Agentic RAG 相关论文，并按路线分类")
    loaded = RequestSpec.model_validate_json(spec.model_dump_json())
    assert loaded.requirements.requested_count == 10
    assert loaded.language_plan.output_language == "zh"
    assert "Agentic RAG" in loaded.canonical_query_en
