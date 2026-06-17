import pytest
from agent_ladder.rag.agentic.registry import CapabilityRegistry
from agent_ladder.rag.contracts.agentic import CapabilitySpec


def test_capability_registry_rejects_duplicate():
    reg = CapabilityRegistry()
    spec = CapabilitySpec(capability_id="paper_chunk_bm25", kind="search_provider", input_schema="SearchRequest", output_schema="list[SearchHit]")
    reg.register_spec(spec)
    assert reg.get("paper_chunk_bm25") == spec
    with pytest.raises(ValueError):
        reg.register_spec(spec)
