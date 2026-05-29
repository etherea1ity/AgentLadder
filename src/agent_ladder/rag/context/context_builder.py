"""Build writer-ready context from selected chunks."""

from __future__ import annotations

from agent_ladder.llm.token_count import estimate_text_tokens
from agent_ladder.rag.contracts.context import BuiltContext
from agent_ladder.rag.contracts.retrieval import RerankedChunk


class ContextBuilder:
    def __init__(self, *, token_budget: int = 1800) -> None:
        self.token_budget = token_budget

    def build(self, query: str, chunks: list[RerankedChunk]) -> BuiltContext:
        selected: list[RerankedChunk] = []
        blocks: list[str] = []
        total_tokens = 0
        seen: set[str] = set()
        for chunk in chunks:
            record = chunk.record
            if record.chunk_id in seen:
                continue
            block = _format_source_block(chunk)
            block_tokens = estimate_text_tokens(block)
            if selected and total_tokens + block_tokens > self.token_budget:
                break
            seen.add(record.chunk_id)
            selected.append(chunk)
            blocks.append(block)
            total_tokens += block_tokens
        return BuiltContext(
            query=query,
            selected_chunks=selected,
            context_text="\n\n".join(blocks),
            token_estimate=total_tokens,
            source_summaries=[_source_summary(item) for item in selected],
        )


def _format_source_block(chunk: RerankedChunk) -> str:
    record = chunk.record
    metadata = record.metadata
    title = metadata.title or record.document_id
    return f"""[Context Block {chunk.rank}]
title: {title}
text:
{record.text.strip()}"""


def _source_summary(chunk: RerankedChunk) -> dict[str, str | int | float | None]:
    record = chunk.record
    return {
        "rank": chunk.rank,
        "chunk_id": record.chunk_id,
        "document_id": record.document_id,
        "title": record.metadata.title,
        "source_path": record.metadata.source_path,
        "score": round(chunk.score, 4),
    }
