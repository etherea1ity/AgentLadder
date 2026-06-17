from agent_ladder.knowledge.paper.schema import PaperManifestEntry


def test_manifest_entry_schema_roundtrip():
    entry = PaperManifestEntry(paper_id="paper_test_2024", title="Test Paper", year=2024, processed_dir="data/papers/processed/paper_test_2024")
    assert PaperManifestEntry.model_validate_json(entry.model_dump_json()).paper_id == entry.paper_id
