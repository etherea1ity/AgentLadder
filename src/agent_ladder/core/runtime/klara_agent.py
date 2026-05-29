"""KlaraAgent runtime helpers for v0.2 RAG."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from agent_ladder.llm.base import BaseLLMClient, Message
from agent_ladder.rag.citations import build_citations, build_source_cards
from agent_ladder.rag.context import ContextBuilder
from agent_ladder.rag.contracts import AnswerFrameV1, BuiltContext, Citation, ModuleResult, RouteDecision, RouterInput, SourceCard
from agent_ladder.rag.embeddings.base import BaseEmbedder
from agent_ladder.rag.indexing.build_local_index import build_local_index_records
from agent_ladder.rag.indexing.local_index_store import LocalIndexStore
from agent_ladder.rag.reranking import SimpleReranker
from agent_ladder.rag.retrieval import BM25Retriever, DenseRetriever, HybridRetriever
from agent_ladder.rag.routing import IntentRouter
from agent_ladder.rag.writer import build_direct_writer_messages, build_rag_writer_messages

ModuleEmitter = Callable[[ModuleResult], None]


class KlaraRunPreparation(BaseModel):
    route: RouteDecision
    messages: list[Message]
    built_context: BuiltContext | None = None
    sources: list[SourceCard] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    used_chunks: list[str] = Field(default_factory=list)
    modules: list[ModuleResult] = Field(default_factory=list)


class KlaraAgent:
    """Prepare direct or RAG writer prompts while exposing public module results."""

    def __init__(
        self,
        *,
        embedder: BaseEmbedder | None = None,
        index_store: LocalIndexStore | None = None,
        knowledge_root: str = "data/knowledge",
        top_k_dense: int = 6,
        top_k_sparse: int = 6,
        top_k_hybrid: int = 14,
        top_k_context: int = 4,
    ) -> None:
        self.embedder = embedder
        self.index_store = index_store or LocalIndexStore()
        self.knowledge_root = knowledge_root
        self.top_k_dense = top_k_dense
        self.top_k_sparse = top_k_sparse
        self.top_k_hybrid = top_k_hybrid
        self.top_k_context = top_k_context
        self.router = IntentRouter()
        self.context_builder = ContextBuilder()

    def prepare(
        self,
        question: str,
        emit_module: ModuleEmitter | None = None,
        router_client: BaseLLMClient | None = None,
    ) -> KlaraRunPreparation:
        modules: list[ModuleResult] = []

        def emit(result: ModuleResult) -> None:
            modules.append(result) if result.status in {"completed", "failed", "skipped"} else None
            if emit_module:
                emit_module(result)

        router_input = RouterInput(question=question)
        route_module = ModuleResult(
            module_id="intent_router",
            module_name="Intent Router",
            input_summary="Classify whether the question needs local knowledge.",
            input_payload=router_input.model_dump(mode="json"),
        ).started()
        emit(route_module)
        route = self.router.route(router_input, llm_client=router_client)
        route_payload = route.model_dump(mode="json")
        if self.router.last_error:
            route_payload["fallback_error"] = self.router.last_error
        route_done = route_module.completed(
            output_summary=f"Decision: {route.route.upper()}",
            output_payload=route_payload,
        )
        emit(route_done)

        if route.route == "direct":
            return KlaraRunPreparation(route=route, messages=build_direct_writer_messages(question), modules=modules)

        retrieval_query = route.rewritten_query or question
        records = self._load_or_build_records()
        query_vector = self._embed_query(retrieval_query)

        dense_module = ModuleResult(
            module_id="dense_retrieval",
            module_name="Dense Retrieval",
            input_summary="Search semantic vectors for related chunks.",
            input_payload={"query": retrieval_query, "query_vector_dimensions": len(query_vector), "top_k": self.top_k_dense},
        ).started()
        emit(dense_module)
        dense_results = DenseRetriever(records).search(query_vector, top_k=self.top_k_dense)
        dense_done = dense_module.completed(
            output_summary=f"Found {len(dense_results)} semantic candidates.",
            output_payload={"results": [_dense_payload(item) for item in dense_results]},
        )
        emit(dense_done)

        bm25_module = ModuleResult(
            module_id="bm25_retrieval",
            module_name="BM25 Retrieval",
            input_summary="Search exact project terms and keywords.",
            input_payload={"query": retrieval_query, "top_k": self.top_k_sparse},
        ).started()
        emit(bm25_module)
        sparse_results = BM25Retriever(records).search(retrieval_query, top_k=self.top_k_sparse)
        bm25_done = bm25_module.completed(
            output_summary=f"Found {len(sparse_results)} keyword candidates.",
            output_payload={"results": [_bm25_payload(item) for item in sparse_results]},
        )
        emit(bm25_done)

        hybrid_module = ModuleResult(
            module_id="hybrid_retrieval",
            module_name="Hybrid Retrieval",
            input_summary="Fuse dense and BM25 candidates.",
            input_payload={"dense_count": len(dense_results), "bm25_count": len(sparse_results), "top_k": self.top_k_hybrid},
        ).started()
        emit(hybrid_module)
        hybrid_results = HybridRetriever().fuse(dense_results=dense_results, sparse_results=sparse_results, top_k=self.top_k_hybrid)
        hybrid_done = hybrid_module.completed(
            output_summary=f"Merged into {len(hybrid_results)} hybrid candidates.",
            output_payload={"results": [_hybrid_payload(item) for item in hybrid_results]},
        )
        emit(hybrid_done)

        rerank_module = ModuleResult(
            module_id="reranking",
            module_name="Reranking",
            input_summary="Select the best chunks for the writer context.",
            input_payload={"query": retrieval_query, "candidate_count": len(hybrid_results), "top_k": self.top_k_context},
        ).started()
        emit(rerank_module)
        reranked = SimpleReranker().rerank(retrieval_query, hybrid_results, top_k=self.top_k_context)
        rerank_done = rerank_module.completed(
            output_summary=f"Selected {len(reranked)} chunks for context.",
            output_payload={"results": [_rerank_payload(item) for item in reranked]},
        )
        emit(rerank_done)

        context_module = ModuleResult(
            module_id="context_builder",
            module_name="Context Builder",
            input_summary="Build a token-bounded evidence context for the writer.",
            input_payload={"query": retrieval_query, "selected_chunk_count": len(reranked)},
        ).started()
        emit(context_module)
        built_context = self.context_builder.build(retrieval_query, reranked)
        context_done = context_module.completed(
            output_summary=f"Built context with about {built_context.token_estimate} tokens.",
            output_payload={"token_estimate": built_context.token_estimate, "sources": built_context.source_summaries},
        )
        emit(context_done)

        sources = build_source_cards(reranked)
        citations = build_citations(reranked)
        return KlaraRunPreparation(
            route=route,
            messages=build_rag_writer_messages(question, built_context),
            built_context=built_context,
            sources=sources,
            citations=citations,
            used_chunks=[item.record.chunk_id for item in reranked],
            modules=modules,
        )

    def answer_frame(self, *, answer: str, preparation: KlaraRunPreparation, run_log: dict[str, Any]) -> AnswerFrameV1:
        return AnswerFrameV1(
            answer=answer,
            route=preparation.route.route,
            sources=preparation.sources,
            citations=preparation.citations,
            used_chunks=preparation.used_chunks,
            run_log=run_log,
        )

    def _load_or_build_records(self):
        records = self.index_store.load_records()
        if records and all(record.dense_vector for record in records):
            return records
        if self.embedder is None:
            raise ValueError("RAG index is missing dense vectors. Run scripts/rag/build_index.py or configure DASHSCOPE_API_KEY.")
        records = build_local_index_records(self.knowledge_root, self.embedder)
        self.index_store.save_records(records)
        return records

    def _embed_query(self, question: str) -> list[float]:
        if self.embedder is None:
            raise ValueError("DASHSCOPE_API_KEY is required to embed RAG queries.")
        return self.embedder.embed_text(question)


def _record_payload(record) -> dict[str, Any]:
    return {
        "record_id": record.record_id,
        "chunk_id": record.chunk_id,
        "document_id": record.document_id,
        "title": record.metadata.title,
        "source_path": record.metadata.source_path,
        "preview": " ".join(record.text.split())[:180],
    }


def _dense_payload(item) -> dict[str, Any]:
    return {**_record_payload(item.record), "rank": item.rank, "score": round(item.score, 4)}


def _bm25_payload(item) -> dict[str, Any]:
    return {**_record_payload(item.record), "rank": item.rank, "score": round(item.score, 4), "matched_tokens": item.matched_tokens}


def _hybrid_payload(item) -> dict[str, Any]:
    return {
        **_record_payload(item.record),
        "rank": item.rank,
        "score": round(item.score, 4),
        "dense_score": round(item.dense_score, 4) if item.dense_score is not None else None,
        "sparse_score": round(item.sparse_score, 4) if item.sparse_score is not None else None,
        "dense_rank": item.dense_rank,
        "sparse_rank": item.sparse_rank,
    }


def _rerank_payload(item) -> dict[str, Any]:
    return {**_record_payload(item.record), "rank": item.rank, "score": round(item.score, 4), "hybrid_score": round(item.hybrid_score, 4), "bonuses": item.bonuses}
