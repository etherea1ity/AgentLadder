from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

AccessStatus = Literal["local_existing", "open_access", "metadata_only", "unknown"]
ProcessingStatus = Literal["processed", "partial", "metadata_only", "failed", "completed"]


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class PaperManifestEntry(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    arxiv_id: str | None = None
    domains: list[str] = Field(default_factory=list)
    method_tags: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    access_status: AccessStatus = "unknown"
    access_note: str = ""
    source_input_path: str | None = None
    local_pdf_path: str | None = None
    processed_dir: str | None = None
    processing_status: ProcessingStatus = "partial"
    has_overview: bool = False
    has_chunks: bool = False
    has_visuals: bool = False
    chunk_count: int = 0
    visual_count: int = 0
    created_at: str = Field(default_factory=now_iso)
    updated_at: str = Field(default_factory=now_iso)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("paper_id", "title")
    @classmethod
    def non_empty(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value


class PaperMetadata(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    url: str | None = None
    pdf_url: str | None = None
    arxiv_id: str | None = None
    doi: str | None = None
    domains: list[str] = Field(default_factory=list)
    method_tags: list[str] = Field(default_factory=list)
    benchmarks: list[str] = Field(default_factory=list)
    source_input_path: str | None = None
    local_pdf_path: str | None = None
    access_status: AccessStatus = "unknown"
    access_note: str = ""
    language: str = "en"
    processing: dict[str, bool] = Field(default_factory=dict)
    quality: dict[str, Any] = Field(default_factory=dict)
    extraction: dict[str, Any] = Field(default_factory=dict)
