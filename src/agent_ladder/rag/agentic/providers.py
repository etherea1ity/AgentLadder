from __future__ import annotations

import math
import re
from collections import Counter
from pathlib import Path
from typing import Protocol

from agent_ladder.knowledge.paper.corpus import PaperCorpus
from agent_ladder.knowledge.paper.visuals import VisualAssetStore
from agent_ladder.rag.contracts.agentic import FetchRequest, FetchResult, SearchHit, SearchRequest
from agent_ladder.rag.retrieval.tokenizer import tokenize


class SearchProvider(Protocol):
    provider_id: str
    def search(self, request: SearchRequest) -> list[SearchHit]: ...


class FetchProvider(Protocol):
    def fetch(self, request: FetchRequest) -> FetchResult: ...


class PaperSearchProvider:
    def __init__(self, provider_id: str, corpus: PaperCorpus | None = None) -> None:
        self.provider_id = provider_id
        self.corpus = corpus or PaperCorpus()

    def search(self, request: SearchRequest) -> list[SearchHit]:
        query = request.canonical_query_en or request.query
        if not has_query_signal(query):
            return []
        if self.provider_id == "paper_metadata":
            rows = self._metadata_rows(query)
        elif self.provider_id in {"paper_overview_bm25", "paper_overview_dense"}:
            rows = self._overview_rows(query)
        elif self.provider_id in {"paper_chunk_bm25", "paper_chunk_dense"}:
            rows = self._chunk_rows(query)
        elif self.provider_id == "paper_visual_caption":
            rows = self._visual_rows(query)
        else:
            rows = []
        rows = [row for row in rows if _matches_filters(row.metadata, request.filters)]
        rows.sort(key=lambda item: item.score, reverse=True)
        return [row.model_copy(update={"rank": index + 1}) for index, row in enumerate(rows[: request.top_k])]

    def _metadata_rows(self, query: str) -> list[SearchHit]:
        hits = []
        for paper in self.corpus.list_papers():
            text = " ".join([paper.title, paper.domain or "", " ".join(paper.method_tags), paper.abstract or ""])
            base_score = keyword_score(query, text)
            score = base_score + (0.25 if base_score > 0 and _year_recent(paper.year) else 0.0)
            if score > 0:
                metadata = paper.model_dump(mode="json")
                metadata.setdefault("domains", paper.metadata.get("domains", []))
                hits.append(SearchHit(provider_id=self.provider_id, source_id=paper.paper_id, paper_id=paper.paper_id, source_type="paper_overview", title=paper.title, snippet=paper.abstract or "", score=score, fetch_id=f"overview:{paper.paper_id}", source_domain="paper_corpus", evidence_role="paper_claim", metadata=metadata))
        return hits

    def _overview_rows(self, query: str) -> list[SearchHit]:
        hits = []
        for paper in self.corpus.list_papers():
            text = self.corpus.overview_text(paper.paper_id)
            score = keyword_score(query, text + " " + paper.title + " " + " ".join(paper.method_tags))
            if score > 0:
                hits.append(SearchHit(provider_id=self.provider_id, source_id=paper.paper_id, paper_id=paper.paper_id, source_type="paper_overview", title=paper.title, snippet=_snippet(text), score=score, fetch_id=f"overview:{paper.paper_id}", source_domain="paper_corpus", evidence_role="paper_claim", metadata={"domain": paper.domain, "domains": paper.metadata.get("domains", []), "method_tags": paper.method_tags, "year": paper.year, "venue": paper.venue, "source_domain": "paper_corpus"}))
        return hits

    def _chunk_rows(self, query: str) -> list[SearchHit]:
        hits = []
        for row in self.corpus.chunks():
            text = " ".join([row.get("title", ""), row.get("text", ""), row.get("domain", ""), " ".join(row.get("method_tags", []))])
            score = keyword_score(query, text)
            if score > 0:
                role = row.get("evidence_role") or row.get("metadata", {}).get("evidence_role", "paper_claim")
                hits.append(SearchHit(provider_id=self.provider_id, source_id=row.get("source_id", row["chunk_id"]), paper_id=row["paper_id"], source_type="paper_chunk", title=row.get("title", row["paper_id"]), snippet=_snippet(row.get("text", "")), score=score, fetch_id=f"chunk:{row['chunk_id']}", source_domain="paper_corpus", evidence_role=role, metadata=row))
        return hits

    def _visual_rows(self, query: str) -> list[SearchHit]:
        hits = []
        for visual in self.corpus.visuals():
            paper = self.corpus.get_paper(visual.paper_id)
            text = " ".join([visual.label or "", visual.caption, visual.nearby_text or "", visual.visual_summary or "", paper.title if paper else ""])
            score = keyword_score(query, text)
            if score > 0:
                source_type = "paper_table" if visual.visual_type == "table" else "paper_figure"
                hits.append(SearchHit(provider_id=self.provider_id, source_id=visual.source_id or visual.visual_id, paper_id=visual.paper_id, source_type=source_type, title=(paper.title if paper else visual.paper_id), snippet=visual.caption, score=score, fetch_id=f"visual:{visual.visual_id}", source_domain="paper_visuals", evidence_role="visual_support", metadata=visual.model_dump(mode="json")))
        return hits


class LocalKnowledgeSearchProvider:
    """Search the existing Agent Ladder local knowledge corpus inside the v0.3 chain."""

    def __init__(self, provider_id: str, knowledge_root: str | Path = "data/knowledge") -> None:
        self.provider_id = provider_id
        self.knowledge_root = Path(knowledge_root)

    def search(self, request: SearchRequest) -> list[SearchHit]:
        rows = []
        query = request.query
        if not has_query_signal(query):
            return []
        for doc in _local_markdown_docs(self.knowledge_root):
            if self.provider_id == "chapter_docs_bm25" and "/chapters/" not in doc["source_path"].replace("\\", "/"):
                continue
            text = f"{doc['title']} {doc['text']}"
            score = keyword_score(query, text)
            if score <= 0:
                continue
            domain = "chapter_docs" if "/chapters/" in doc["source_path"].replace("\\", "/") else "project_docs"
            rows.append(SearchHit(provider_id=self.provider_id, source_id=doc["document_id"], source_type="chapter_doc" if domain == "chapter_docs" else "project_doc", title=doc["title"], snippet=_snippet(doc["text"]), score=score, fetch_id=f"local_doc:{doc['document_id']}", source_domain=domain, evidence_role="chapter_design" if domain == "chapter_docs" else "project_fact", metadata=doc))
        rows.sort(key=lambda item: item.score, reverse=True)
        return [row.model_copy(update={"rank": index + 1}) for index, row in enumerate(rows[: request.top_k])]


class PaperFetchProvider:
    provider_id = "paper_fetch"

    def __init__(self, corpus: PaperCorpus | None = None, asset_store: VisualAssetStore | None = None) -> None:
        self.corpus = corpus or PaperCorpus()
        self.asset_store = asset_store or VisualAssetStore(self.corpus.root)

    def fetch(self, request: FetchRequest) -> FetchResult:
        kind, _, identifier = request.fetch_id.partition(":")
        if kind == "overview":
            paper = self.corpus.get_paper(identifier)
            if paper is None:
                raise KeyError(identifier)
            return FetchResult(fetch_id=request.fetch_id, source_id=paper.paper_id, source_type="paper_overview", paper_id=paper.paper_id, title=paper.title, text=self.corpus.overview_text(paper.paper_id), source_domain="paper_corpus", evidence_role="paper_claim", metadata={**paper.model_dump(mode="json"), "source_path": f"{self.corpus.root.as_posix()}/{paper.paper_id}/overview.md", "source_domain": "paper_corpus"})
        if kind == "chunk":
            row = self.corpus.fetch_chunk(identifier)
            if row is None:
                raise KeyError(identifier)
            return FetchResult(fetch_id=request.fetch_id, source_id=row.get("source_id", row["chunk_id"]), source_type="paper_chunk", paper_id=row["paper_id"], title=row.get("title", row["paper_id"]), text=row.get("text", ""), source_domain="paper_corpus", evidence_role=row.get("evidence_role") or row.get("metadata", {}).get("evidence_role", "paper_claim"), metadata={**row, "source_path": f"{self.corpus.root.as_posix()}/{row['paper_id']}/chunks.jsonl", "source_domain": "paper_corpus"})
        if kind == "visual":
            visual = self.corpus.fetch_visual(identifier)
            if visual is None:
                raise KeyError(identifier)
            paper = self.corpus.get_paper(visual.paper_id)
            return FetchResult(fetch_id=request.fetch_id, source_id=visual.source_id or visual.visual_id, source_type="paper_table" if visual.visual_type == "table" else "paper_figure", paper_id=visual.paper_id, title=paper.title if paper else visual.paper_id, text=visual.caption, image_path=self.asset_store.resolve(visual), page=visual.page, source_domain="paper_visuals", evidence_role="visual_support", metadata={**visual.model_dump(mode="json"), "caption": visual.caption, "source_domain": "paper_visuals"})
        if kind == "local_doc":
            doc = _local_doc_by_id(identifier)
            if doc is None:
                raise KeyError(identifier)
            domain = "chapter_docs" if "/chapters/" in doc["source_path"].replace("\\", "/") else "project_docs"
            return FetchResult(fetch_id=request.fetch_id, source_id=doc["document_id"], source_type="chapter_doc" if domain == "chapter_docs" else "project_doc", title=doc["title"], text=doc["text"], source_domain=domain, evidence_role="chapter_design" if domain == "chapter_docs" else "project_fact", metadata={**doc, "source_domain": domain})
        raise ValueError(f"unsupported fetch id: {request.fetch_id}")


def has_query_signal(query: str) -> bool:
    return any(token not in _STOPWORDS and not token.startswith("qwerty") for token in tokenize(query))


def keyword_score(query: str, text: str) -> float:
    q = [token for token in dict.fromkeys(tokenize(query)) if token not in _STOPWORDS and not token.startswith("qwerty")]
    if not q:
        return 0.0
    tokens = tokenize(text)
    if not tokens:
        return 0.0
    tf = Counter(tokens)
    score = 0.0
    for token in q:
        if token in tf:
            score += 1.0 + math.log(1 + tf[token])
    return score / max(1.0, math.log(len(tokens) + 2))


_STOPWORDS = {
    "a", "an", "the", "and", "or", "to", "of", "in", "on", "for", "with", "about",
    "this", "that", "should", "not", "match", "anything", "query", "find", "give",
    "me", "explain", "compare", "papers", "paper", "related", "include", "if",
    "available", "chinese", "english", "what", "is", "are", "by", "as", "from", "tell",
}


def _year_recent(year: int | None) -> bool:
    return bool(year and year >= 2023)


def _snippet(text: str, limit: int = 220) -> str:
    return re.sub(r"\s+", " ", text).strip()[:limit]


def _matches_filters(metadata: dict, filters: dict) -> bool:
    if not filters:
        return True
    for key, expected in filters.items():
        if expected in (None, [], ""):
            continue
        actual = metadata.get(key)
        if actual is None and isinstance(metadata.get("metadata"), dict):
            actual = metadata["metadata"].get(key)
        if isinstance(expected, list):
            actual_values = actual if isinstance(actual, list) else [actual]
            if not any(item in actual_values for item in expected):
                return False
        elif actual != expected:
            return False
    return True


def _local_markdown_docs(root: Path = Path("data/knowledge")) -> list[dict]:
    docs: list[dict] = []
    for path in sorted(root.rglob("*.md")):
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if not text:
            continue
        title = _first_heading(text) or path.stem.replace("-", " ").title()
        source_path = path.as_posix()
        docs.append({
            "document_id": f"doc_{re.sub(r'[^a-z0-9]+', '_', source_path.lower()).strip('_')}",
            "title": title,
            "source_path": source_path,
            "text": text,
            "source_type": "markdown",
        })
    return docs


def _local_doc_by_id(document_id: str, root: Path = Path("data/knowledge")) -> dict | None:
    return next((doc for doc in _local_markdown_docs(root) if doc["document_id"] == document_id), None)


def _first_heading(text: str) -> str | None:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return None
