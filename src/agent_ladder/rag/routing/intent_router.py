"""Rule-based v0.2 intent router."""

from __future__ import annotations

from agent_ladder.rag.contracts.route import RouteDecision
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
}
_DIRECT_TERMS = {"hi", "hello", "hey", "你好", "谢谢", "thanks"}


class IntentRouter:
    def route(self, question: str) -> RouteDecision:
        tokens = set(tokenize(question))
        normalized = question.strip().lower()
        matched = sorted(tokens & _RAG_TERMS)
        if "agent" in tokens and "ladder" in tokens and "agent" not in matched:
            matched.append("agent")
        if matched:
            return RouteDecision(route="rag", reason="The question mentions Klara, the course, or RAG-specific project terms.", confidence=0.86, matched_terms=matched)
        if normalized in _DIRECT_TERMS or len(tokens) <= 2:
            return RouteDecision(route="direct", reason="The question looks like a short greeting or general chat.", confidence=0.72, matched_terms=[])
        if any(term in normalized for term in ["this project", "this repo", "knowledge", "source", "资料", "章节", "克拉拉"]):
            return RouteDecision(route="rag", reason="The question appears to ask about local project knowledge.", confidence=0.78, matched_terms=[])
        return RouteDecision(route="direct", reason="No local-knowledge signal was detected, so Klara can answer directly.", confidence=0.62, matched_terms=[])
