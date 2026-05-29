"""Programmatic local index builder for API/runtime fallback."""

from __future__ import annotations

from agent_ladder.rag.chunking.overlap import OverlapTextSplitter
from agent_ladder.rag.embeddings.base import BaseEmbedder
from agent_ladder.rag.indexing.index_record import IndexRecord, records_from_chunks
from agent_ladder.rag.ingestion.local_markdown import LocalMarkdownLoader
from agent_ladder.rag.retrieval.tokenizer import tokenize


def build_local_index_records(knowledge_root: str = "data/knowledge", embedder: BaseEmbedder | None = None) -> list[IndexRecord]:
    documents = LocalMarkdownLoader(knowledge_root).load()
    chunks = OverlapTextSplitter(chunk_size=800, chunk_overlap=120).split_documents(documents)
    records = records_from_chunks(chunks)
    if embedder is None:
        return [_with_sparse(record) for record in records]
    vectors = embedder.embed_texts([record.text for record in records])
    return [_with_sparse(record).model_copy(update={"dense_vector": vector}) for record, vector in zip(records, vectors, strict=True)]


def _with_sparse(record: IndexRecord) -> IndexRecord:
    tokens = tokenize("\n".join([record.metadata.title or "", record.metadata.summary or "", " ".join(record.metadata.tags), record.text]))
    return record.model_copy(update={"sparse_tokens": tokens, "token_count": len(tokens)})
