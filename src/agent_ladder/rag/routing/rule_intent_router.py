"""Deterministic fallback intent router for local RAG."""

from __future__ import annotations

from agent_ladder.rag.contracts.route import RouteDecision, RouterInput
from agent_ladder.rag.retrieval.tokenizer import tokenize

_RAG_TERMS = {
    "klara",
    "ladder",
    "agentladder",
    "chapter",
    "v0.1",
    "v0.2",
    "minimal",
    "rag",
    "askstate",
    "answerstate",
    "runlog",
    "answerframev1",
    "sourcecard",
    "citation",
    "retrieval",
    "chunk",
    "embedding",
    "bm25",
    "hybrid",
    "metadata",
    "本章",
    "这一章",
    "这章",
    "当前章节",
}
_DIRECT_TERMS = {"hi", "hello", "hey", "你好", "谢谢", "thanks"}


class RuleIntentRouter:
    """Cheap deterministic router used when the LLM JSON router is unavailable."""

    def route(self, question: str | RouterInput) -> RouteDecision:
        router_input = question if isinstance(question, RouterInput) else RouterInput(question=question)
        tokens = set(tokenize(router_input.question))
        normalized = router_input.question.strip().lower()
        matched = sorted(tokens & _RAG_TERMS)
        if "agent" in tokens and "ladder" in tokens and "agent" not in matched:
            matched.append("agent")
        if matched:
            return RouteDecision(
                route="rag",
                reason="The question mentions Klara, the course, or RAG-specific project terms.",
                confidence=0.86,
                needs_local_knowledge=True,
                query_type="project_knowledge",
                rewritten_query=router_input.question,
                matched_terms=matched,
                fallback_used=True,
            )
        current_chapter_terms = ["this chapter", "current chapter", "本章", "这一章", "这章", "当前章节"]
        if any(term in normalized for term in current_chapter_terms):
            return RouteDecision(
                route="rag",
                reason="The question asks about the current v0.2 RAG chapter.",
                confidence=0.84,
                needs_local_knowledge=True,
                query_type="chapter_question",
                rewritten_query="v0.2-rag-agent Chapter 2 RAG Agent current chapter goals capabilities RAG pipeline",
                matched_terms=["v0.2", "rag", "chapter"],
                fallback_used=True,
            )
        if normalized in _DIRECT_TERMS or len(tokens) <= 2:
            return RouteDecision(
                route="direct",
                reason="The question looks like a short greeting or general chat.",
                confidence=0.72,
                needs_local_knowledge=False,
                query_type="general_chat",
                matched_terms=[],
                fallback_used=True,
            )
        if any(term in normalized for term in ["this project", "this repo", "knowledge", "source", "资料", "章节", "克拉拉"]):
            return RouteDecision(
                route="rag",
                reason="The question appears to ask about local project knowledge.",
                confidence=0.78,
                needs_local_knowledge=True,
                query_type="project_knowledge",
                rewritten_query=router_input.question,
                matched_terms=[],
                fallback_used=True,
            )
        return RouteDecision(
            route="direct",
            reason="No local-knowledge signal was detected, so Klara can answer directly.",
            confidence=0.62,
            needs_local_knowledge=False,
            query_type="general_chat",
            matched_terms=[],
            fallback_used=True,
        )
