"""Retrieval result aliases for public imports."""

from agent_ladder.rag.contracts.retrieval import HybridSearchResult, RetrievalResult
from agent_ladder.rag.indexing.simple_vector_index import DenseSearchResult

__all__ = ["DenseSearchResult", "HybridSearchResult", "RetrievalResult"]
