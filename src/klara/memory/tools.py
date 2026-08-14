"""Model-visible tools for explicit, scoped memory operations."""

from __future__ import annotations

from dataclasses import dataclass

import json

from klara.core.tools import (
    JsonObject,
    ToolMetadata,
    ToolOutputTrust,
    ToolResult,
    ToolSideEffect,
    ToolSpec,
)
from klara.memory.models import MemoryKind, MemoryProvenance, MemoryScope, MemorySensitivity
from klara.memory.service import MemoryNotFoundError, MemoryService, MemoryValidationError
from klara.tools.base import BaseTool, ToolInputError


MEMORY_METADATA = ToolMetadata(
    label="Memory",
    category="memory",
    side_effect=ToolSideEffect.WRITE,
    parallel_safe=False,
    max_output_chars=12_000,
)


@dataclass(frozen=True)
class MemoryRememberTool(BaseTool):
    """Persist only content the user explicitly requested to remember."""

    service: MemoryService
    scope: MemoryScope
    spec: ToolSpec = ToolSpec(
        name="memory_remember",
        description=(
            "Explicitly remember one durable user fact, preference, episode, task fact, "
            "or reviewed agent lesson. Do not save ordinary chat automatically."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "content": {"type": "string"},
                "kind": {
                    "type": "string",
                    "enum": [item.value for item in MemoryKind],
                },
                "sensitivity": {
                    "type": "string",
                    "enum": [item.value for item in MemorySensitivity],
                },
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                "ttl_seconds": {"type": "integer", "minimum": 1},
            },
            "required": ["content", "kind"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = MEMORY_METADATA

    def run(self, arguments: JsonObject):
        try:
            record = self.service.remember(
                scope=self.scope,
                content=self.required_string(arguments, "content"),
                kind=_kind(arguments),
                sensitivity=_sensitivity(arguments),
                provenance=MemoryProvenance(
                    source_type="explicit_user_request",
                    actor_id=self.scope.user_id,
                    source_id=self.scope.session_id,
                ),
                confidence=_confidence(arguments),
                ttl_seconds=_optional_int(arguments, "ttl_seconds"),
            )
        except (MemoryValidationError, ValueError) as exc:
            return self.failure(arguments, str(exc))
        return self.json_success(
            arguments,
            {**record.to_trace_dict(), "remembered": True},
        )

    def required_string(self, arguments: JsonObject, key: str) -> str:
        value = self.optional_string(arguments, key)
        if not value:
            raise ToolInputError(f"{key} is required")
        return value


@dataclass(frozen=True)
class MemorySearchTool(BaseTool):
    """Retrieve owner-scoped memories with temporal and hybrid ranking."""

    service: MemoryService
    scope: MemoryScope
    spec: ToolSpec = ToolSpec(
        name="memory_search",
        description=(
            "Search only this user's durable memory. Use at_time for historical "
            "questions. Results include provenance and score components."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["hybrid", "lexical", "vector", "recent", "full_context", "semantic_recency", "mem0_compatible"],
                    "description": "Use semantic_recency for the local vector-plus-recency ablation. mem0_compatible is a deprecated compatibility alias and is not official Mem0.",
                },
                "at_time": {
                    "type": "string",
                    "format": "date-time",
                    "description": (
                        "Optional exact ISO-8601 snapshot time for questions about what "
                        "memory knew then. Do not use it merely because the event being "
                        "searched has a date; keep event dates in query instead."
                    ),
                },
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = ToolMetadata(
        label="Memory search",
        category="memory",
        side_effect=ToolSideEffect.READ,
        max_output_chars=20_000,
        output_trust=ToolOutputTrust.UNTRUSTED,
    )

    def run(self, arguments: JsonObject):
        query = self.optional_string(arguments, "query")
        if not query:
            return self.failure(arguments, "query is required")
        try:
            hits = self.service.search(
                scope=self.scope,
                query=query,
                mode=self.optional_string(arguments, "mode") or "hybrid",
                at_time=self.optional_string(arguments, "at_time") or None,
                limit=_optional_int(arguments, "limit") or 8,
            )
        except ValueError as exc:
            return self.failure(arguments, str(exc))
        ranked_hits = list(enumerate(hits, start=1))
        timeline_hits = sorted(
            ranked_hits,
            key=lambda item: (
                item[1].record.valid_from or item[1].record.created_at,
                item[0],
            ),
        )
        content = {
            "schema_version": "klara.memory-search.v1",
            "query": query,
            "result_count": len(hits),
            "selection_order": "top_k_by_retrieval_score",
            "presentation_order": "chronological_after_selection",
            "results": [
                {**hit.to_model_dict(), "retrieval_rank": retrieval_rank}
                for retrieval_rank, hit in timeline_hits
            ],
        }
        return ToolResult(
            tool_call_id=self.call_id(arguments),
            name=self.spec.name,
            content=json.dumps(content, ensure_ascii=False),
            public_content=json.dumps(
                {
                    "schema_version": "klara.memory-search-public.v1",
                    "result_count": len(hits),
                    "memory_ids": [hit.record.memory_id for hit in hits],
                    "content_exposed": False,
                },
                ensure_ascii=False,
            ),
        )


@dataclass(frozen=True)
class MemoryUpdateTool(BaseTool):
    service: MemoryService
    scope: MemoryScope
    spec: ToolSpec = ToolSpec(
        name="memory_update",
        description="Update one owned memory by creating a superseding current record.",
        input_schema={
            "type": "object",
            "properties": {
                "memory_id": {"type": "string"},
                "content": {"type": "string"},
                "confidence": {"type": "number", "minimum": 0, "maximum": 1},
            },
            "required": ["memory_id", "content"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = MEMORY_METADATA

    def run(self, arguments: JsonObject):
        memory_id = self.optional_string(arguments, "memory_id")
        content = self.optional_string(arguments, "content")
        if not memory_id or not content:
            return self.failure(arguments, "memory_id_and_content_required")
        try:
            record = self.service.update(
                scope=self.scope,
                memory_id=memory_id,
                content=content,
                actor_id=self.scope.user_id,
                confidence=_optional_float(arguments, "confidence"),
            )
        except (MemoryNotFoundError, MemoryValidationError) as exc:
            return self.failure(arguments, str(exc))
        return self.json_success(arguments, {**record.to_trace_dict(), "updated": True})


@dataclass(frozen=True)
class MemoryForgetTool(BaseTool):
    service: MemoryService
    scope: MemoryScope
    spec: ToolSpec = ToolSpec(
        name="memory_forget",
        description="Stop retrieving one owned memory while retaining auditable history.",
        input_schema={
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = MEMORY_METADATA

    def run(self, arguments: JsonObject):
        memory_id = self.optional_string(arguments, "memory_id")
        try:
            record = self.service.forget(
                scope=self.scope,
                memory_id=memory_id,
                actor_id=self.scope.user_id,
            )
        except MemoryNotFoundError as exc:
            return self.failure(arguments, str(exc))
        return self.json_success(arguments, {**record.to_trace_dict(), "forgotten": True})


@dataclass(frozen=True)
class MemoryDeleteTool(BaseTool):
    service: MemoryService
    scope: MemoryScope
    spec: ToolSpec = ToolSpec(
        name="memory_delete",
        description="Permanently delete one owned memory and verify its raw content is gone.",
        input_schema={
            "type": "object",
            "properties": {"memory_id": {"type": "string"}},
            "required": ["memory_id"],
            "additionalProperties": False,
        },
    )
    metadata: ToolMetadata = MEMORY_METADATA

    def run(self, arguments: JsonObject):
        memory_id = self.optional_string(arguments, "memory_id")
        try:
            receipt = self.service.delete(
                scope=self.scope,
                memory_id=memory_id,
                actor_id=self.scope.user_id,
            )
        except MemoryNotFoundError as exc:
            return self.failure(arguments, str(exc))
        return self.json_success(arguments, receipt)


def memory_tools(service: MemoryService, scope: MemoryScope) -> tuple[BaseTool, ...]:
    """Return the complete model-facing memory capability set."""

    return (
        MemoryRememberTool(service, scope),
        MemorySearchTool(service, scope),
        MemoryUpdateTool(service, scope),
        MemoryForgetTool(service, scope),
        MemoryDeleteTool(service, scope),
    )


def _kind(arguments: JsonObject) -> MemoryKind:
    return MemoryKind(str(arguments.get("kind", "")))


def _sensitivity(arguments: JsonObject) -> MemorySensitivity:
    return MemorySensitivity(str(arguments.get("sensitivity", "standard")))


def _confidence(arguments: JsonObject) -> float:
    value = _optional_float(arguments, "confidence")
    return 1.0 if value is None else value


def _optional_int(arguments: JsonObject, key: str) -> int | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise ToolInputError(f"{key} must be an integer")
    return value


def _optional_float(arguments: JsonObject, key: str) -> float | None:
    value = arguments.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ToolInputError(f"{key} must be a number")
    return float(value)
