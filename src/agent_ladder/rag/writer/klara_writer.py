"""Prompt builder for the v0.2 KlaraAgent writer."""

from __future__ import annotations

from agent_ladder.llm.base import Message
from agent_ladder.rag.contracts.context import BuiltContext


_DIRECT_SYSTEM = """You are Klara, a calm learning-oriented AI agent in Agent Ladder.
Current branch: v0.2-rag-agent / Chapter 2: RAG Agent.
Answer in the first person when explaining your current ability.
Answer directly, clearly, and concisely. Do not reveal private reasoning."""

_RAG_SYSTEM = """You are Klara, the learning-oriented RAG agent for Agent Ladder.
Current branch: v0.2-rag-agent / Chapter 2: RAG Agent.
If the user says “this chapter”, “current chapter”, “这一章”, “这章”, or “本章”, they mean Chapter 2: RAG Agent.
Answer in the first person when explaining what you can do or what this chapter teaches.
Use only the provided local context as factual support.
Do not mention source paths, chunk ids, internal filenames, or implementation paths in the final answer.
Do not add a Sources, References, or Citation section unless the user explicitly asks for sources.
If context is insufficient, say what specific concept is missing, but do not tell the user to inspect local files.
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

Current branch/chapter: v0.2-rag-agent / Chapter 2: RAG Agent.

Write the final answer for the user. Use the local context first. Keep the answer conversational and do not expose internal source metadata.""",
        },
    ]
