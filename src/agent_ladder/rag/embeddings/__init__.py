"""Embedding clients."""

from agent_ladder.rag.embeddings.base import BaseEmbedder
from agent_ladder.rag.embeddings.dashscope import DashScopeEmbedder

__all__ = ["BaseEmbedder", "DashScopeEmbedder"]
