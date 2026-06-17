import json
from pathlib import Path


def test_visual_rows_have_caption_and_domain_when_present():
    path = Path("data/papers/processed/paper_002/visuals.jsonl")
    row = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert row["caption"]
    assert row["source_id"] == row["visual_id"]
    assert row["metadata"]["source_domain"] == "paper_visuals"
