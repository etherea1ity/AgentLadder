"""Index-layer helpers."""

from agent_ladder.rag.indexing.index_record import (
    IndexRecord,
    record_from_chunk,
    records_from_chunks,
)
from agent_ladder.rag.indexing.local_index_store import LocalIndexStore
from agent_ladder.rag.indexing.simple_vector_index import DenseSearchResult, SimpleVectorIndex
from agent_ladder.rag.indexing.similarity import cosine_similarity, dot_product, vector_norm

__all__ = [
    "DenseSearchResult",
    "IndexRecord",
    "LocalIndexStore",
    "SimpleVectorIndex",
    "cosine_similarity",
    "dot_product",
    "record_from_chunk",
    "records_from_chunks",
    "vector_norm",
]
