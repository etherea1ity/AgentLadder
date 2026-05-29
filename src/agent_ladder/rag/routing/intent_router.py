"""LLM-backed JSON intent router with deterministic fallback."""

from __future__ import annotations

import json
import re
from typing import Any

from agent_ladder.llm.base import BaseLLMClient, Message
from agent_ladder.rag.contracts.route import RouteDecision, RouterInput
from agent_ladder.rag.routing.rule_intent_router import RuleIntentRouter

_ROUTER_SYSTEM = """You are Klara's v0.2 RAG intent router.
Decide whether the user's question needs the local Agent Ladder/Klara knowledge base.
Return ONLY valid JSON. Do not include markdown, explanations, or chain-of-thought.

Schema:
{
  "route": "direct" | "rag",
  "reason": "short public reason",
  "confidence": number between 0 and 1,
  "needs_local_knowledge": boolean,
  "query_type": "general_chat" | "project_knowledge" | "chapter_question" | "technical_question" | "ambiguous",
  "rewritten_query": string or null,
  "matched_terms": string[]
}

Choose "rag" when the question asks about Klara, Agent Ladder, this repository, a chapter, local docs, RAG concepts in this course, or named project states such as AskState, RunLog, SourceCard, Citation, or AnswerFrameV1.
Choose "direct" for greetings, general conversation, or questions that do not need local project knowledge.
"""


class IntentRouter:
    """Route through an LLM JSON call when available, then fall back safely."""

    def __init__(self, llm_client: BaseLLMClient | None = None, fallback: RuleIntentRouter | None = None) -> None:
        self.llm_client = llm_client
        self.fallback = fallback or RuleIntentRouter()
        self.last_raw_output: str | None = None
        self.last_error: str | None = None

    def route(self, question: str | RouterInput, llm_client: BaseLLMClient | None = None) -> RouteDecision:
        router_input = question if isinstance(question, RouterInput) else RouterInput(question=question)
        client = llm_client or self.llm_client
        self.last_raw_output = None
        self.last_error = None
        if client is None:
            return self.fallback.route(router_input)

        try:
            response = client.chat(_router_messages(router_input))
            self.last_raw_output = response.content
            payload = _extract_json_object(response.content)
            decision = RouteDecision.model_validate(payload)
            if decision.route == "rag" and not decision.rewritten_query:
                decision = decision.model_copy(update={"rewritten_query": router_input.question})
            return decision.model_copy(update={"router_model": response.model, "fallback_used": False})
        except Exception as exc:
            self.last_error = str(exc)
            fallback_decision = self.fallback.route(router_input)
            return fallback_decision.model_copy(update={"fallback_used": True})


def _router_messages(router_input: RouterInput) -> list[Message]:
    return [
        {"role": "system", "content": _ROUTER_SYSTEM},
        {"role": "user", "content": json.dumps(router_input.model_dump(mode="json"), ensure_ascii=False)},
    ]


def _extract_json_object(content: str) -> dict[str, Any]:
    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text, flags=re.IGNORECASE)
        text = re.sub(r"\s*```$", "", text)
    try:
        value = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValueError("router response must be a JSON object")
    return value
