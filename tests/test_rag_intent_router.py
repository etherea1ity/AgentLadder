from __future__ import annotations

import json

from agent_ladder.core.runtime.klara_agent import KlaraAgent
from agent_ladder.llm.base import BaseLLMClient, LLMResponse, Message
from agent_ladder.rag.contracts.document import DocumentMetadata
from agent_ladder.rag.embeddings.base import BaseEmbedder
from agent_ladder.rag.indexing.index_record import IndexRecord
from agent_ladder.rag.indexing.local_index_store import LocalIndexStore
from agent_ladder.rag.routing import IntentRouter
from agent_ladder.rag.routing.rule_intent_router import RuleIntentRouter


class JsonRouterLLM(BaseLLMClient):
    def __init__(self, payload: dict | str) -> None:
        self.payload = payload
        self.messages: list[list[Message]] = []

    def chat(self, messages: list[Message]) -> LLMResponse:
        self.messages.append(messages)
        content = self.payload if isinstance(self.payload, str) else json.dumps(self.payload)
        return LLMResponse(content=content, model="router-json-llm", prompt_tokens=9, completion_tokens=7)


class FakeEmbedder(BaseEmbedder):
    def embed_text(self, text: str) -> list[float]:
        normalized = text.lower()
        if "answerframe" in normalized or "citation" in normalized:
            return [1.0, 0.0, 0.0]
        return [0.0, 1.0, 0.0]


def test_llm_intent_router_validates_json_decision():
    router = IntentRouter(
        JsonRouterLLM(
            {
                "route": "rag",
                "reason": "The question asks about a local Klara chapter object.",
                "confidence": 0.94,
                "needs_local_knowledge": True,
                "query_type": "project_knowledge",
                "rewritten_query": "Explain AnswerFrameV1 in Agent Ladder chapter 2.",
                "matched_terms": ["AnswerFrameV1", "chapter 2"],
            }
        )
    )

    decision = router.route("What is AnswerFrameV1?")

    assert decision.route == "rag"
    assert decision.needs_local_knowledge is True
    assert decision.query_type == "project_knowledge"
    assert decision.rewritten_query == "Explain AnswerFrameV1 in Agent Ladder chapter 2."
    assert decision.router_model == "router-json-llm"
    assert decision.fallback_used is False
    assert router.last_model == "router-json-llm"
    assert router.last_prompt_tokens == 9
    assert router.last_completion_tokens == 7
    assert router.last_total_tokens == 16
    assert router.last_token_source == "reported"


def test_llm_intent_router_falls_back_on_invalid_json():
    router = IntentRouter(JsonRouterLLM("not json"))

    decision = router.route("What is Klara RAG?")

    assert decision.route == "rag"
    assert decision.fallback_used is True
    assert router.last_error


def test_rule_router_treats_current_chapter_as_v02_rag():
    decision = RuleIntentRouter().route("hi，能告诉我我们这一章讲什么吗？")

    assert decision.route == "rag"
    assert decision.query_type == "chapter_question"
    assert "v0.2-rag-agent" in (decision.rewritten_query or "")



def test_klara_agent_uses_llm_router_json_and_structured_rag_modules(tmp_path):
    store = LocalIndexStore(tmp_path / "index_records.jsonl")
    store.save_records(
        [
            IndexRecord(
                record_id="idx_answerframe",
                chunk_id="chunk_answerframe",
                document_id="doc_ch02",
                text="AnswerFrameV1 is Klara's structured RAG answer object with answer, sources, citations, used chunks, and run log.",
                metadata=DocumentMetadata(
                    source_path="data/knowledge/ch02-rag-agent.md",
                    title="Chapter 2 Capability: RAG Agent",
                    chapter="ch02",
                    version="v0.2",
                    tags=["rag", "answerframev1"],
                    summary="RAG answer frame contract.",
                ),
                dense_vector=[1.0, 0.0, 0.0],
                sparse_tokens=["answerframev1", "klara", "rag", "sources", "citations"],
                token_count=5,
            ),
            IndexRecord(
                record_id="idx_general",
                chunk_id="chunk_general",
                document_id="doc_global",
                text="Klara is a learning-oriented agent presence in Agent Ladder.",
                metadata=DocumentMetadata(
                    source_path="data/knowledge/global.md",
                    title="Global Klara Overview",
                    chapter="global",
                    version="v0.2",
                    tags=["klara"],
                    summary="Global project overview.",
                ),
                dense_vector=[0.0, 1.0, 0.0],
                sparse_tokens=["klara", "agent", "ladder"],
                token_count=3,
            ),
        ]
    )
    router_llm = JsonRouterLLM(
        {
            "route": "rag",
            "reason": "AnswerFrameV1 is a local chapter contract.",
            "confidence": 0.97,
            "needs_local_knowledge": True,
            "query_type": "project_knowledge",
            "rewritten_query": "AnswerFrameV1 structured RAG answer object sources citations",
            "matched_terms": ["AnswerFrameV1", "RAG"],
        }
    )
    modules = []
    agent = KlaraAgent(embedder=FakeEmbedder(), index_store=store, top_k_dense=2, top_k_sparse=2, top_k_hybrid=3, top_k_context=1)

    preparation = agent.prepare("What is AnswerFrameV1?", emit_module=modules.append, router_client=router_llm)

    assert preparation.route.route == "rag"
    assert preparation.route.router_model == "router-json-llm"
    assert preparation.route.fallback_used is False
    assert preparation.used_chunks == ["chunk_answerframe"]
    completed = [module for module in modules if module.status == "completed"]
    module_ids = [module.module_id for module in completed]
    assert module_ids == [
        "intent_router",
        "dense_retrieval",
        "bm25_retrieval",
        "hybrid_retrieval",
        "reranking",
        "context_builder",
    ]
    router_module = completed[0]
    assert router_module.input_payload["question"] == "What is AnswerFrameV1?"
    assert "v0.2 RAG intent router" in router_module.input_payload["system_prompt"]
    assert router_module.input_payload["input_json"] == {"question": "What is AnswerFrameV1?"}
    assert router_module.output_payload["route"] == "rag"
    assert router_module.output_payload["decision"]["route"] == "rag"
    assert router_module.output_payload["model"] == "router-json-llm"
    assert router_module.output_payload["prompt_tokens"] == 9
    assert router_module.output_payload["completion_tokens"] == 7
    assert router_module.output_payload["total_tokens"] == 16
    assert router_module.output_payload["rewritten_query"] == "AnswerFrameV1 structured RAG answer object sources citations"
    assert completed[1].input_payload["query"] == "AnswerFrameV1 structured RAG answer object sources citations"
    assert completed[1].output_payload["algorithm"] == "cosine_similarity"
    assert completed[1].output_payload["index"] == "local_jsonl_dense_vector"
    assert completed[2].output_payload["algorithm"] == "BM25"
    assert completed[3].output_payload["algorithm"] == "weighted_score_fusion"
    assert completed[4].output_payload["algorithm"] == "SimpleReranker"
    assert completed[-1].output_payload["token_budget"] > 0
    assert completed[-1].output_payload["source_blocks"] == 1
    assert completed[-1].output_payload["sources"][0]["chunk_id"] == "chunk_answerframe"
    assert "source_path" not in preparation.built_context.context_text
    assert "chunk_id" not in preparation.built_context.context_text
