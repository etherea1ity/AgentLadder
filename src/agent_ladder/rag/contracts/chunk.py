"""Chunk contracts for Klara's local RAG pipeline."""

from datetime import datetime

from pydantic import BaseModel, Field

from agent_ladder.rag.contracts.document import DocumentMetadata


class TextChunk(BaseModel):
    """A searchable text fragment produced from a source Document."""

    chunk_id: str
    document_id: str
    text: str
    chunk_index: int
    start_char: int
    end_char: int
    metadata: DocumentMetadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
