"""Build source cards from selected RAG chunks."""

from __future__ import annotations

from agent_ladder.rag.contracts.retrieval import RerankedChunk
from agent_ladder.rag.contracts.source import Citation, SourceCard


def build_source_cards(chunks: list[RerankedChunk]) -> list[SourceCard]:
    grouped: dict[str, SourceCard] = {}
    for chunk in chunks:
        record = chunk.record
        source_id = record.document_id
        card = grouped.get(source_id)
        if card is None:
            card = SourceCard(
                source_id=source_id,
                title=record.metadata.title or record.document_id,
                source_path=record.metadata.source_path,
                chapter=record.metadata.chapter,
                version=record.metadata.version,
                summary=record.metadata.summary,
                used_chunk_ids=[],
            )
        if record.chunk_id not in card.used_chunk_ids:
            card.used_chunk_ids.append(record.chunk_id)
        grouped[source_id] = card
    return list(grouped.values())


def build_citations(chunks: list[RerankedChunk]) -> list[Citation]:
    citations: list[Citation] = []
    for index, chunk in enumerate(chunks, start=1):
        record = chunk.record
        text = " ".join(record.text.split())[:220]
        citations.append(
            Citation(
                citation_id=f"cit_{index}",
                source_id=record.document_id,
                chunk_id=record.chunk_id,
                label=f"Source {index}",
                quote_or_summary=text,
            )
        )
    return citations
