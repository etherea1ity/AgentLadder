"""Chapter 3 Agentic RAG contracts.

These contracts are intentionally explicit and JSON-serializable. They extend
v0.1/v0.2 state without replacing AskState, AnswerState, RunLog, SourceCard, or
AnswerFrameV1.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from agent_ladder.rag.contracts.source import Citation, SourceCard

AnswerMode = Literal["direct", "rag", "mixed", "insufficient_info"]
OutputLanguage = Literal["auto", "en", "zh", "mixed"]
AnswerStyle = Literal["short", "explanatory", "paper_list", "comparison", "research_brief"]
EvidenceType = Literal["text", "visual", "mixed", "figure", "table", "equation", "page_image"]
VisualType = Literal["figure", "table", "page", "visual", "equation", "page_image"]
SourceDomain = Literal["paper_corpus", "paper_visuals", "project_docs", "chapter_docs", "future_web"]
EvidenceRole = Literal["paper_claim", "paper_method", "paper_result", "visual_support", "project_fact", "chapter_design"]
SearchProviderKind = Literal[
    "paper_overview_dense",
    "paper_overview_bm25",
    "paper_metadata",
    "paper_chunk_dense",
    "paper_chunk_bm25",
    "paper_visual_caption",
    "project_docs_bm25",
    "chapter_docs_bm25",
]
SourceType = Literal["markdown", "paper", "paper_overview", "paper_chunk", "paper_figure", "paper_table", "paper_visual", "project_doc", "chapter_doc"]
WorkflowStatus = Literal["created", "running", "completed", "failed", "insufficient_info"]
VerificationStatus = Literal["passed", "failed", "insufficient", "revised"]


def utc_now() -> datetime:
    return datetime.now(UTC)


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex}"


class LanguagePlan(BaseModel):
    input_language: OutputLanguage = "auto"
    canonical_query_language: Literal["en"] = "en"
    output_language: OutputLanguage = "auto"
    explicit_output_language: bool = False
    reason: str = "default"


class OutputStyleSpec(BaseModel):
    answer_style: AnswerStyle = "explanatory"
    include_sources: bool = True
    include_visual_sources: bool = True
    max_bullets: int | None = Field(default=None, ge=1, le=50)


class AnswerRequirement(BaseModel):
    requested_count: int | None = Field(default=None, ge=1, le=50)
    need_diversity: bool = False
    need_recent: bool = False
    need_method_details: bool = False
    need_limitations: bool = False
    requested_domains: list[str] = Field(default_factory=list)
    requested_method_tags: list[str] = Field(default_factory=list)


class RequestSpec(BaseModel):
    request_id: str = Field(default_factory=lambda: new_id("req"))
    original_query: str
    canonical_query_en: str
    language_plan: LanguagePlan = Field(default_factory=LanguagePlan)
    output_style: OutputStyleSpec = Field(default_factory=OutputStyleSpec)
    requirements: AnswerRequirement = Field(default_factory=AnswerRequirement)
    query_variants_by_domain: dict[str, str] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)

    @field_validator("original_query", "canonical_query_en")
    @classmethod
    def non_empty(cls, value: str) -> str:
        text = value.strip()
        if not text:
            raise ValueError("query must not be empty")
        return text


class RouteState(BaseModel):
    route: AnswerMode = "rag"
    reason: str = "agentic rag default"
    confidence: float = Field(default=0.7, ge=0.0, le=1.0)
    needs_evidence: bool = True


class SubQuestion(BaseModel):
    sub_question_id: str = Field(default_factory=lambda: new_id("subq"))
    question: str
    canonical_query_en: str
    priority: int = Field(default=1, ge=1, le=10)


class CapabilitySpec(BaseModel):
    capability_id: str
    kind: Literal["worker", "search_provider", "fetch_provider", "runtime_node"]
    input_schema: str
    output_schema: str
    description: str = ""
    budget_tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class WorkerAgentSpec(BaseModel):
    worker_id: str
    name: str
    input_schema: str
    output_schema: str
    prompt_label: str | None = None
    max_calls_per_run: int = Field(default=1, ge=1, le=5)
    description: str = ""


class SearchProviderSpec(BaseModel):
    provider_id: SearchProviderKind | Literal["paper_fetch"]
    input_schema: str = "SearchRequest"
    output_schema: str = "list[SearchHit]"
    source_types: list[SourceType] = Field(default_factory=list)
    supports_filters: bool = True
    enabled: bool = True


class SearchRequest(BaseModel):
    query: str
    canonical_query_en: str | None = None
    provider_id: str | None = None
    top_k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    source_domain: SourceDomain | None = None


class SearchHit(BaseModel):
    hit_id: str = Field(default_factory=lambda: new_id("hit"))
    provider_id: str
    source_id: str
    paper_id: str | None = None
    source_type: SourceType
    title: str
    snippet: str = ""
    score: float = 0.0
    rank: int = Field(default=0, ge=0)
    fetch_id: str
    source_domain: SourceDomain = "paper_corpus"
    evidence_role: EvidenceRole = "paper_claim"
    metadata: dict[str, Any] = Field(default_factory=dict)


class FetchRequest(BaseModel):
    fetch_id: str
    source_type: SourceType
    paper_id: str | None = None
    include_asset: bool = True
    source_domain: SourceDomain | None = None


class FetchResult(BaseModel):
    fetch_id: str
    source_id: str
    source_type: SourceType
    paper_id: str | None = None
    title: str
    text: str = ""
    image_path: str | None = None
    page: int | None = None
    source_domain: SourceDomain = "paper_corpus"
    evidence_role: EvidenceRole = "paper_claim"
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchUnit(BaseModel):
    unit_id: str = Field(default_factory=lambda: new_id("unit"))
    provider_id: SearchProviderKind
    query: str
    top_k: int = Field(default=10, ge=1, le=100)
    filters: dict[str, Any] = Field(default_factory=dict)
    source_domain: SourceDomain = "paper_corpus"
    purpose: str = "evidence_search"


class EvidenceSearchPlan(BaseModel):
    original_query: str
    canonical_query_en: str
    search_units: list[SearchUnit] = Field(default_factory=list)
    final_source_count: int = Field(default=5, ge=1, le=50)
    candidate_source_budget: int = Field(default=25, ge=1, le=100)
    candidate_chunk_budget: int = Field(default=40, ge=1, le=200)
    evidence_item_budget: int = Field(default=8, ge=1, le=50)
    fusion_method: Literal["rrf", "weighted"] = "rrf"
    diversity_requirements: list[str] = Field(default_factory=list)
    stop_conditions: list[str] = Field(default_factory=lambda: ["enough_evidence", "budget_exhausted"])


class RetrievalAttempt(BaseModel):
    attempt_id: str = Field(default_factory=lambda: new_id("att"))
    stage: Literal["search", "fusion", "dedup", "rerank", "fetch", "rewrite", "expand"]
    provider_id: str | None = None
    query: str | None = None
    hit_count: int = 0
    selected_count: int = 0
    latency_ms: int | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class PaperCard(BaseModel):
    paper_id: str
    title: str
    authors: list[str] = Field(default_factory=list)
    year: int | None = None
    venue: str | None = None
    domain: str | None = None
    method_tags: list[str] = Field(default_factory=list)
    abstract: str | None = None
    overview_path: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class VisualElement(BaseModel):
    visual_id: str
    paper_id: str
    source_id: str | None = None
    visual_type: VisualType
    label: str | None = None
    caption: str
    page: int | None = None
    image_path: str | None = None
    thumbnail_path: str | None = None
    section: str | None = None
    nearby_text: str | None = None
    ocr_text: str | None = None
    visual_summary: str | None = None
    bbox: Any | None = None
    source_domain: SourceDomain = "paper_visuals"
    evidence_role: EvidenceRole = "visual_support"
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="before")
    @classmethod
    def accept_title_as_label(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("label") and data.get("title"):
                data["label"] = data["title"]
            if not data.get("source_id") and data.get("visual_id"):
                data["source_id"] = data["visual_id"]
        return data

    @field_validator("caption", "label")
    @classmethod
    def visual_text_not_empty(cls, value: str | None) -> str:
        value = value or ""
        text = value.strip()
        if not text:
            raise ValueError("visual label/caption must not be empty")
        return text


class EvidenceItem(BaseModel):
    evidence_id: str = Field(default_factory=lambda: new_id("ev"))
    evidence_type: EvidenceType = "text"
    source_id: str
    paper_id: str | None = None
    title: str
    text: str = ""
    visual: VisualElement | None = None
    score: float | None = None
    rank: int = Field(default=0, ge=0)
    source_domain: SourceDomain = "paper_corpus"
    evidence_role: EvidenceRole = "paper_claim"
    supports_claims: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def evidence_has_content(self) -> "EvidenceItem":
        if not self.text.strip() and self.visual is None:
            raise ValueError("evidence item must contain text or visual metadata")
        return self


class EvidencePack(BaseModel):
    pack_id: str = Field(default_factory=lambda: new_id("epack"))
    question: str
    canonical_query_en: str
    items: list[EvidenceItem] = Field(default_factory=list)
    source_cards: list[SourceCard] = Field(default_factory=list)
    budget: dict[str, int] = Field(default_factory=dict)
    evidence_status: Literal["sufficient", "weak", "insufficient"] = "weak"
    source_domains: list[SourceDomain] = Field(default_factory=list)
    evidence_by_domain: dict[str, list[str]] = Field(default_factory=dict)

    @property
    def source_ids(self) -> set[str]:
        return {str(getattr(card, "source_id", "")) for card in self.source_cards if getattr(card, "source_id", None)}


class AnswerFrameV2(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str
    mode: AnswerMode = "rag"
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    claims: list[str] = Field(default_factory=list)
    sources: list[SourceCard] = Field(default_factory=list)
    evidence_items: list[EvidenceItem] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    visual_sources: list[VisualElement] = Field(default_factory=list)
    rendered_assets: list[dict[str, Any]] = Field(default_factory=list)
    final_text: str


class VerificationResult(BaseModel):
    status: VerificationStatus
    citation_ok: bool = True
    evidence_ok: bool = True
    visual_ok: bool = True
    language_ok: bool = True
    unsupported_claims: list[str] = Field(default_factory=list)
    missing_source_ids: list[str] = Field(default_factory=list)
    reason: str = ""
    revised: bool = False


class DecisionRecord(BaseModel):
    decision_id: str = Field(default_factory=lambda: new_id("dec"))
    node_name: str
    decision_type: str
    reason: str
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    input_summary: str = ""
    output_summary: str = ""
    alternatives: list[str] = Field(default_factory=list)
    latency_ms: int | None = None
    error: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class BudgetState(BaseModel):
    max_search_units: int = 6
    max_candidate_sources: int = 60
    max_candidate_chunks: int = 120
    max_evidence_items: int = 24
    search_units_used: int = 0
    candidate_sources_used: int = 0
    candidate_chunks_used: int = 0
    evidence_items_used: int = 0
    clamp_events: list[str] = Field(default_factory=list)


class FailurePolicy(BaseModel):
    max_json_repair: int = 1
    max_query_rewrite: int = 1
    max_search_expansion: int = 1
    max_answer_revision: int = 1
    json_repair_used: int = 0
    query_rewrite_used: int = 0
    search_expansion_used: int = 0
    answer_revision_used: int = 0


class WorkflowState(BaseModel):
    workflow_id: str = Field(default_factory=lambda: new_id("wf"))
    run_mode: Literal["agentic_rag"] = "agentic_rag"
    status: WorkflowStatus = "created"
    request: RequestSpec | None = None
    route: RouteState | None = None
    sub_questions: list[SubQuestion] = Field(default_factory=list)
    search_plan: EvidenceSearchPlan | None = None
    search_hits: list[SearchHit] = Field(default_factory=list)
    retrieval_attempts: list[RetrievalAttempt] = Field(default_factory=list)
    fetch_results: list[FetchResult] = Field(default_factory=list)
    evidence_pack: EvidencePack | None = None
    answer_frame: AnswerFrameV2 | None = None
    verification: VerificationResult | None = None
    decisions: list[DecisionRecord] = Field(default_factory=list)
    budget: BudgetState = Field(default_factory=BudgetState)
    failure_policy: FailurePolicy = Field(default_factory=FailurePolicy)
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None
