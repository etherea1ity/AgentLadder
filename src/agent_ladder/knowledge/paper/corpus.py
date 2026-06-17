from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from agent_ladder.rag.contracts.agentic import PaperCard, VisualElement


class PaperCorpus:
    """Read processed Chapter 3 paper corpus.

    `root` may point either to a direct paper directory collection such as
    `data/papers/fixtures`, or to the real corpus root `data/papers` containing a
    `processed/` child. Providers only read processed files and indexes; they do
    not parse PDFs.
    """

    def __init__(self, root: str | Path = "data/papers/fixtures") -> None:
        self.requested_root = Path(root)
        self.base_root, self.root = resolve_corpus_roots(self.requested_root)
        self.manifest = _load_manifest(self.base_root / "manifest.jsonl")
        self.papers = PaperLoader(self.root, manifest=self.manifest).load()

    def list_papers(self) -> list[PaperCard]:
        return list(self.papers.values())

    def get_paper(self, paper_id: str) -> PaperCard | None:
        return self.papers.get(paper_id)

    def overview_text(self, paper_id: str) -> str:
        path = self.root / paper_id / "overview.md"
        return path.read_text(encoding="utf-8") if path.exists() else ""

    def chunks(self, paper_id: str | None = None) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        for paper in self._paper_ids(paper_id):
            rows.extend(_read_jsonl(self.root / paper / "chunks.jsonl"))
        return rows

    def visuals(self, paper_id: str | None = None) -> list[VisualElement]:
        rows: list[VisualElement] = []
        for paper in self._paper_ids(paper_id):
            for row in _read_jsonl(self.root / paper / "visuals.jsonl"):
                rows.append(VisualElement.model_validate(row))
        return rows

    def fetch_chunk(self, chunk_id: str) -> dict[str, Any] | None:
        for row in self.chunks():
            if row.get("chunk_id") == chunk_id or row.get("source_id") == chunk_id:
                return row
        return None

    def fetch_visual(self, visual_id: str) -> VisualElement | None:
        return next((visual for visual in self.visuals() if visual.visual_id == visual_id or getattr(visual, "source_id", None) == visual_id), None)

    def _paper_ids(self, paper_id: str | None = None) -> list[str]:
        if paper_id:
            return [paper_id]
        return [paper.paper_id for paper in self.list_papers()]


class PaperLoader:
    def __init__(self, root: str | Path, *, manifest: dict[str, dict[str, Any]] | None = None) -> None:
        self.root = Path(root)
        self.manifest = manifest or {}

    def load(self) -> dict[str, PaperCard]:
        papers: dict[str, PaperCard] = {}
        if not self.root.exists():
            return papers
        for metadata_path in sorted(self.root.glob("*/metadata.json")):
            data = json.loads(metadata_path.read_text(encoding="utf-8"))
            pid = data.get("paper_id") or metadata_path.parent.name
            manifest_data = self.manifest.get(pid, {})
            merged = {**manifest_data, **data}
            domains = merged.get("domains") or ([] if not merged.get("domain") else [merged.get("domain")])
            domain = merged.get("domain") or (domains[0] if domains else None)
            paper_payload = {
                "paper_id": pid,
                "title": merged.get("title") or _title_from_overview(metadata_path.parent / "overview.md") or pid,
                "authors": merged.get("authors") or [],
                "year": merged.get("year"),
                "venue": merged.get("venue"),
                "domain": domain,
                "method_tags": merged.get("method_tags") or [],
                "abstract": merged.get("abstract") or _overview_snippet(metadata_path.parent / "overview.md"),
                "overview_path": str(metadata_path.parent / "overview.md"),
                "metadata": {**merged, "domains": domains, "source_domain": "paper_corpus"},
            }
            paper = PaperCard.model_validate(paper_payload)
            papers[paper.paper_id] = paper
        return papers


def resolve_corpus_roots(root: str | Path) -> tuple[Path, Path]:
    root = Path(root)
    direct_metadata = [p for p in root.glob("*/metadata.json") if p.parent.name not in {"processed", "raw"}]
    if direct_metadata:
        return root, root
    if (root / "processed").exists():
        return root, root / "processed"
    if root.name == "processed":
        return root.parent, root
    return root, root


def _load_manifest(path: Path) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    if not path.exists():
        return rows
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                try:
                    row = json.loads(line)
                except json.JSONDecodeError:
                    continue
                pid = row.get("paper_id")
                if pid:
                    rows[pid] = row
    return rows


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            if line.strip():
                rows.append(json.loads(line))
    return rows


def _title_from_overview(path: Path) -> str | None:
    if not path.exists():
        return None
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None


def _overview_snippet(path: Path, limit: int = 600) -> str | None:
    if not path.exists():
        return None
    text = path.read_text(encoding="utf-8", errors="replace")
    return " ".join(text.split())[:limit]
