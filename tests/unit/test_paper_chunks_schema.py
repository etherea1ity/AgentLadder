import json
from pathlib import Path


def test_real_chunks_have_source_ids_after_migration():
    path = Path("data/papers/processed/paper_001/chunks.jsonl")
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["source_id"] == row["chunk_id"]
    assert row["metadata"]["source_domain"] == "paper_corpus"
