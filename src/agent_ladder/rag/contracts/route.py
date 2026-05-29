"""Routing contracts for deciding whether Klara needs RAG."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


RouteName = Literal["direct", "rag"]


class RouteDecision(BaseModel):
    route: RouteName
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    matched_terms: list[str] = Field(default_factory=list)
