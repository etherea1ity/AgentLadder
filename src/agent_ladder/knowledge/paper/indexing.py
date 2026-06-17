from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_ladder.knowledge.paper.corpus import PaperCorpus


def build_indexes(root: str | Path) -> dict[str, Any]:
    root = Path(root)
    corpus = PaperCorpus(root)
    overview_rows = []
    chunk_rows = []
    metadata_rows = []
    visual_rows = []
    for paper in corpus.list_papers():
        metadata_rows.append(paper.model_dump(mode="json"))
        overview_rows.append({
            "paper_id": paper.paper_id,
            "title": paper.title,
            "year": paper.year,
            "domains": paper.metadata.get("domains", []) or ([paper.domain] if paper.domain else []),
            "method_tags": paper.method_tags,
            "text": corpus.overview_text(paper.paper_id),
            "source_domain": "paper_corpus",
        })
    for row in corpus.chunks():
        chunk_rows.append({
            "paper_id": row.get("paper_id"),
            "chunk_id": row.get("chunk_id"),
            "source_id": row.get("source_id", row.get("chunk_id")),
            "section": row.get("section"),
            "text": row.get("text", ""),
            "metadata": row.get("metadata", {}),
            "source_domain": row.get("source_domain") or row.get("metadata", {}).get("source_domain", "paper_corpus"),
        })
    for visual in corpus.visuals():
        visual_rows.append(visual.model_dump(mode="json"))
    return {
        "paper_overview_index": {"schema_version": 1, "rows": overview_rows},
        "paper_chunk_index": {"schema_version": 1, "rows": chunk_rows},
        "paper_metadata_index": {"schema_version": 1, "rows": metadata_rows},
        "paper_visual_caption_index": {"schema_version": 1, "rows": visual_rows},
    }


def write_indexes(root: str | Path) -> dict[str, Path]:
    root = Path(root)
    indexes_dir = root / "indexes"
    indexes_dir.mkdir(parents=True, exist_ok=True)
    written: dict[str, Path] = {}
    for name, payload in build_indexes(root).items():
        path = indexes_dir / f"{name}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        written[name] = path
    return written
