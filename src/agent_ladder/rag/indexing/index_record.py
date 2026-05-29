"""Index-layer records for Klara's local RAG pipeline."""

from datetime import datetime

from pydantic import BaseModel, Field

from agent_ladder.rag.contracts.chunk import TextChunk
from agent_ladder.rag.contracts.document import DocumentMetadata


class IndexRecord(BaseModel):
    """A TextChunk after it enters the retrieval/index layer."""

    record_id: str
    chunk_id: str
    document_id: str
    text: str
    metadata: DocumentMetadata
    dense_vector: list[float] | None = None
    sparse_tokens: list[str] = Field(default_factory=list)
    token_count: int = 0
    created_at: datetime = Field(default_factory=datetime.utcnow)


def record_from_chunk(chunk: TextChunk) -> IndexRecord:
    """Convert one TextChunk into the minimal index-layer record."""

    return IndexRecord(
        record_id=f"idx_{chunk.chunk_id}",
        chunk_id=chunk.chunk_id,
        document_id=chunk.document_id,
        text=chunk.text,
        metadata=chunk.metadata,
    )


def records_from_chunks(chunks: list[TextChunk]) -> list[IndexRecord]:
    """Convert TextChunks into IndexRecords while preserving order."""

    return [record_from_chunk(chunk) for chunk in chunks]
