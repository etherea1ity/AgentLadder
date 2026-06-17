"""RAG contracts exported for the teaching pipeline."""

from agent_ladder.rag.contracts.answer_frame import AnswerFrameV1, EvidenceItem, WriterInputFrame
from agent_ladder.rag.contracts.chunk import TextChunk
from agent_ladder.rag.contracts.context import BuiltContext
from agent_ladder.rag.contracts.document import Document, DocumentMetadata
from agent_ladder.rag.contracts.module import ModuleResult, ModuleStatus
from agent_ladder.rag.contracts.retrieval import HybridSearchResult, RerankedChunk, RetrievalQuery, RetrievalResult
from agent_ladder.rag.contracts.route import QueryType, RouteDecision, RouteName, RouterInput
from agent_ladder.rag.contracts.source import Citation, SourceCard
from agent_ladder.rag.contracts.agentic import (
    AnswerFrameV2, AnswerRequirement, BudgetState, CapabilitySpec, DecisionRecord,
    EvidenceItem as AgenticEvidenceItem, EvidencePack, EvidenceSearchPlan, FailurePolicy,
    FetchRequest, FetchResult, LanguagePlan, OutputStyleSpec, PaperCard, RequestSpec,
    RetrievalAttempt, RouteState, SearchHit, SearchProviderSpec, SearchRequest,
    SearchUnit, SubQuestion, VerificationResult, VisualElement, WorkerAgentSpec, WorkflowState,
)

__all__ = [
    "AnswerFrameV1",
    "BuiltContext",
    "Citation",
    "Document",
    "DocumentMetadata",
    "EvidenceItem",
    "HybridSearchResult",
    "ModuleResult",
    "ModuleStatus",
    "RerankedChunk",
    "RetrievalQuery",
    "RetrievalResult",
    "QueryType",
    "RouteDecision",
    "RouteName",
    "RouterInput",
    "SourceCard",
    "TextChunk",
    "WriterInputFrame",
    "AnswerFrameV2", "AnswerRequirement", "BudgetState", "CapabilitySpec", "DecisionRecord",
    "AgenticEvidenceItem", "EvidencePack", "EvidenceSearchPlan", "FailurePolicy",
    "FetchRequest", "FetchResult", "LanguagePlan", "OutputStyleSpec", "PaperCard", "RequestSpec",
    "RetrievalAttempt", "RouteState", "SearchHit", "SearchProviderSpec", "SearchRequest",
    "SearchUnit", "SubQuestion", "VerificationResult", "VisualElement", "WorkerAgentSpec", "WorkflowState",
]
