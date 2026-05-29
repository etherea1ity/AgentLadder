"""Document contracts for Klara's local knowledge library."""

from datetime import datetime

from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Identity information for a document loaded into the RAG system."""

    source_path: str
    source_type: str = "markdown"
    category: str | None = None
    title: str | None = None
    chapter: str | None = None
    version: str | None = None
    language: str = "en"
    tags: list[str] = Field(default_factory=list)
    summary: str | None = None


class Document(BaseModel):
    """A local knowledge file after it enters Klara's RAG system."""

    document_id: str
    title: str
    text: str
    metadata: DocumentMetadata
    created_at: datetime = Field(default_factory=datetime.utcnow)
