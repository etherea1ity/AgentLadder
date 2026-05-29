"""Prompt builder for the v0.2 KlaraAgent writer."""

from __future__ import annotations

from agent_ladder.llm.base import Message
from agent_ladder.rag.contracts.context import BuiltContext


_DIRECT_SYSTEM = """You are Klara, a calm learning-oriented AI agent in Agent Ladder. Answer directly, clearly, and concisely. Do not reveal private reasoning."""

_RAG_SYSTEM = """You are Klara, a learning-oriented RAG agent for Agent Ladder.
Answer the user's question using the provided local context.
If the context is insufficient, say what is missing instead of inventing.
Keep citations lightweight by mentioning the source title or chunk id when useful.
Do not reveal private reasoning or chain-of-thought."""


def build_direct_writer_messages(question: str) -> list[Message]:
    return [
        {"role": "system", "content": _DIRECT_SYSTEM},
        {"role": "user", "content": question},
    ]


def build_rag_writer_messages(question: str, context: BuiltContext) -> list[Message]:
    return [
        {"role": "system", "content": _RAG_SYSTEM},
        {
            "role": "user",
            "content": f"""Question:
{question}

Local context:
{context.context_text}

Write the final answer for the user. Use the local context first. If useful, include a short Sources section.""",
        },
    ]
