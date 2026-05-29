"""RAG contracts exported for the teaching pipeline."""

from agent_ladder.rag.contracts.answer_frame import AnswerFrameV1
from agent_ladder.rag.contracts.chunk import TextChunk
from agent_ladder.rag.contracts.context import BuiltContext
from agent_ladder.rag.contracts.document import Document, DocumentMetadata
from agent_ladder.rag.contracts.module import ModuleResult, ModuleStatus
from agent_ladder.rag.contracts.retrieval import HybridSearchResult, RerankedChunk, RetrievalQuery, RetrievalResult
from agent_ladder.rag.contracts.route import QueryType, RouteDecision, RouteName, RouterInput
from agent_ladder.rag.contracts.source import Citation, SourceCard

__all__ = [
    "AnswerFrameV1",
    "BuiltContext",
    "Citation",
    "Document",
    "DocumentMetadata",
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
]
