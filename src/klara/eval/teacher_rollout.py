"""Async concurrent DeepSeek V4 Pro teacher rollout generator.

This module turns tasks from data/tasks/task_pool.json (or an explicitly
passed tasks file) into OpenAI-style teacher trajectories.  Every trajectory is
appended as one JSON object per line to data/trajectories/raw.jsonl.

The tool backend is intentionally a small deterministic in-memory stub for the
eight frozen tools.  It exposes the same async interface that the later
FrozenToolBackend can plug into, so only build_tool_backend needs to change
when the fixture store lands.
"""

from __future__ import annotations

import argparse
import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import time
from typing import Any, Iterable, Protocol

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover - optional convenience loader
    load_dotenv = None

import openai
from openai import AsyncOpenAI


SCHEMA_VERSION = "klara.teacher-rollout.v1"
DEFAULT_MODEL = "deepseek-v4-pro"
DEFAULT_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_TASKS_PATH = Path("data/tasks/task_pool.json")
DEFAULT_RAW_PATH = Path("data/trajectories/raw.jsonl")

TOOL_NAMES: tuple[str, ...] = (
    "web_search",
    "web_fetch",
    "memory_search",
    "current_time",
    "evidence_submit",
    "update_activity",
    "skills_list",
    "skill_view",
)

# Frozen tool schema.  Kept in sync with the repo tool modules and with
# docs/resume/klara-eval-contract.md.  Used for both model-visible tool JSON and
# deterministic filter validation.
TOOL_SCHEMAS: dict[str, dict[str, Any]] = {
    "web_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "allowed_domains": {"type": "array", "items": {"type": "string"}},
            "blocked_domains": {"type": "array", "items": {"type": "string"}},
            "count": {"type": "integer", "minimum": 1, "maximum": 20},
            "freshness": {"type": "string", "enum": ["day", "week", "month", "year", "any"]},
            "date_after": {"type": "string"},
            "date_before": {"type": "string"},
            "language": {"type": "string"},
            "country": {"type": "string"},
            "search_depth": {"type": "string", "enum": ["basic", "advanced"]},
            "require_freshness_enforced": {"type": "boolean"},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "web_fetch": {
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "candidate_id": {"type": "string"},
            "source_id": {"type": "string"},
            "max_chars": {"type": "integer", "minimum": 200, "maximum": 12000},
            "query_terms": {"type": "array", "items": {"type": "string"}},
            "extract_mode": {
                "type": "string",
                "enum": ["plain", "relevant_snippets", "summary_snippets"],
            },
        },
        "required": ["url"],
        "additionalProperties": False,
    },
    "memory_search": {
        "type": "object",
        "properties": {
            "query": {"type": "string"},
            "mode": {
                "type": "string",
                "enum": [
                    "hybrid",
                    "lexical",
                    "vector",
                    "recent",
                    "full_context",
                    "semantic_recency",
                    "mem0_compatible",
                ],
            },
            "at_time": {"type": "string", "format": "date-time"},
            "limit": {"type": "integer", "minimum": 1, "maximum": 20},
        },
        "required": ["query"],
        "additionalProperties": False,
    },
    "current_time": {
        "type": "object",
        "properties": {"timezone": {"type": "string"}},
        "required": [],
        "additionalProperties": False,
    },
    "evidence_submit": {
        "type": "object",
        "properties": {
            "final_text": {"type": "string"},
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string"},
                        "text": {"type": "string"},
                        "required": {"type": "boolean"},
                    },
                    "required": ["claim_id", "text"],
                    "additionalProperties": False,
                },
            },
            "links": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string"},
                        "source_id": {"type": "string"},
                        "judgment": {
                            "type": "string",
                            "enum": ["supported", "contradicted", "insufficient"],
                        },
                        "support_note": {"type": "string"},
                    },
                    "required": ["claim_id", "source_id", "judgment", "support_note"],
                    "additionalProperties": False,
                },
            },
            "citations": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "claim_id": {"type": "string"},
                        "source_id": {"type": "string"},
                    },
                    "required": ["claim_id", "source_id"],
                    "additionalProperties": False,
                },
            },
            "abstain": {"type": "boolean"},
            "abstention_reason": {"type": "string"},
        },
        "required": ["final_text", "claims", "links", "citations", "abstain"],
        "additionalProperties": False,
    },
    "update_activity": {
        "type": "object",
        "properties": {"text": {"type": "string"}},
        "required": ["text"],
        "additionalProperties": False,
    },
    "skills_list": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "skill_view": {
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "reference": {"type": "string"},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
}

TOOL_DESCRIPTIONS: dict[str, str] = {
    "web_search": "Search the public web and return candidate result cards as public links with titles, URLs, snippets, provider, and searched_at metadata.",
    "web_fetch": "Fetch one public HTTP(S) page and return readable text, final URL, status, content type, title, and truncation metadata.",
    "memory_search": "Search only this user's durable memory. Use at_time for historical questions. Results include provenance and score components.",
    "current_time": "Return exact current wall-clock date, time, weekday, and UTC offset for a requested timezone.",
    "evidence_submit": "Submit a web-backed proposed answer, material claims, exact fetched-source links, citations, or an explicit abstention for runtime verification.",
    "update_activity": "Append Klara's public thinking update for the current step. This is not the final answer.",
    "skills_list": "List available procedural Skills as metadata.",
    "skill_view": "Load one relevant Skill body or one declared reference on demand.",
}

SYSTEM_PROMPT = """You are Klara's teacher rollout agent. You may use only the tools listed in the current request.

Rules:
- Call tools one logical step at a time. You may call more than one tool in the same response only when they are independent.
- Use only the tools currently exposed in the tool list.
- When you call a tool, provide valid JSON arguments matching its JSON schema exactly.
- After tool observations are available, continue only if needed; otherwise produce one concise Final Answer.
- The Final Answer is ordinary assistant text, never a tool call.
- If evidence_submit is available for a web-backed task, submit final_text, claims, links, citations, and abstain before your final answer.
"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _stable_id(prefix: str, *parts: Any, length: int = 10) -> str:
    digest = hashlib.sha256(_canonical([prefix, *parts]).encode("utf-8")).hexdigest()
    return f"{prefix}-{digest[:length]}"


def model_tools(available_tools: Iterable[str]) -> list[dict[str, Any]]:
    """Return OpenAI function-tool definitions for the available frozen tools."""

    names = tuple(dict.fromkeys(available_tools))
    return [
        {
            "type": "function",
            "function": {
                "name": name,
                "description": TOOL_DESCRIPTIONS[name],
                "parameters": TOOL_SCHEMAS[name],
            },
        }
        for name in names
        if name in TOOL_SCHEMAS
    ]


class ToolBackend(Protocol):
    """Interface that FrozenToolBackend will later implement."""

    async def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return a deterministic JSON-serializable tool observation."""

        ...


@dataclass
class DeterministicToolStub:
    """Deterministic in-memory implementation of the eight frozen tools.

    Every result is a function of the tool name and arguments, so repeated
    rollouts are comparable and no external service or local fixture store is
    required yet.
    """

    def _query_seed(self, arguments: dict[str, Any]) -> str:
        return hashlib.sha256(_canonical(arguments).encode("utf-8")).hexdigest()

    async def run(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name not in TOOL_NAMES:
            return {
                "schema_version": "klara.tool-stub.v1",
                "ok": False,
                "error": "unknown_tool",
                "name": name,
            }
        handler = getattr(self, f"_run_{name}")
        return handler(arguments)

    def _run_web_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", ""))
        seed = self._query_seed(args)
        count = min(max(int(args.get("count", 3)), 1), 5)
        results = []
        for index in range(count):
            results.append(
                {
                    "candidate_id": f"stub-search-{seed[:12]}-{index}",
                    "title": f"Stable result {index + 1} for {query[:80]}",
                    "url": f"https://example.test/{seed[:12]}/{index + 1}",
                    "snippet": f"Deterministic snippet for query: {query[:120]}",
                    "provider": "teacher-stub",
                    "searched_at": "2026-08-16T12:00:00+08:00",
                }
            )
        return {
            "schema_version": "klara.tool-stub.v1",
            "ok": True,
            "query": query,
            "result_count": len(results),
            "results": results,
        }

    def _run_web_fetch(self, args: dict[str, Any]) -> dict[str, Any]:
        url = str(args.get("url", ""))
        seed = self._query_seed(args)
        return {
            "schema_version": "klara.tool-stub.v1",
            "ok": True,
            "url": url,
            "candidate_id": args.get("candidate_id"),
            "source_id": args.get("source_id", f"stub-source-{seed[:10]}"),
            "status": 200,
            "content_type": "text/html; charset=utf-8",
            "title": f"Stable fetched page for {url[:80]}",
            "text": f"Deterministic page text for {url}. The stable fact is: klara-teacher-smoke-ok.",
            "truncated": False,
        }

    def _run_memory_search(self, args: dict[str, Any]) -> dict[str, Any]:
        query = str(args.get("query", ""))
        return {
            "schema_version": "klara.tool-stub.v1",
            "ok": True,
            "query": query,
            "result_count": 2,
            "selection_order": "top_k_by_retrieval_score",
            "presentation_order": "chronological_after_selection",
            "results": [
                {
                    "memory_id": "stub-memory-001",
                    "content": "The owner prefers deterministic fixtures for smoke tests.",
                    "kind": "preference",
                    "valid_from": "2026-08-01T00:00:00+08:00",
                    "retrieval_rank": 1,
                },
                {
                    "memory_id": "stub-memory-002",
                    "content": "Frozen teacher tools are web_search, web_fetch, memory_search, current_time, evidence_submit, update_activity, skills_list, skill_view.",
                    "kind": "stable_fact",
                    "valid_from": "2026-08-16T12:00:00+08:00",
                    "retrieval_rank": 2,
                },
            ],
        }

    def _run_current_time(self, args: dict[str, Any]) -> dict[str, Any]:
        timezone_name = args.get("timezone", "Asia/Shanghai")
        return {
            "schema_version": "klara.tool-stub.v1",
            "ok": True,
            "timezone": timezone_name,
            "datetime": "2026-08-16T12:00:00+08:00",
            "weekday": "Sunday",
            "utc_offset": "+08:00",
            "is_dst": False,
        }

    def _run_evidence_submit(self, args: dict[str, Any]) -> dict[str, Any]:
        claims = args.get("claims", [])
        links = args.get("links", [])
        citations = args.get("citations", [])
        return {
            "schema_version": "klara.tool-stub.v1",
            "ok": True,
            "submitted": True,
            "abstain": bool(args.get("abstain", False)),
            "claim_count": len(claims) if isinstance(claims, list) else 0,
            "links_count": len(links) if isinstance(links, list) else 0,
            "citations_count": len(citations) if isinstance(citations, list) else 0,
            "verification": "pending",
        }

    def _run_update_activity(self, args: dict[str, Any]) -> dict[str, Any]:
        text = str(args.get("text", ""))
        return {
            "schema_version": "klara.tool-stub.v1",
            "ok": True,
            "recorded": True,
            "activity_chars": len(text),
        }

    def _run_skills_list(self, args: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema_version": "klara.tool-stub.v1",
            "ok": True,
            "skills": [
                {
                    "name": "web-research",
                    "version": "1.0.0",
                    "scope": "project",
                    "reference": "SKILL.md",
                },
                {
                    "name": "memory-hygiene",
                    "version": "1.0.0",
                    "scope": "user",
                    "reference": "SKILL.md",
                },
            ],
        }

    def _run_skill_view(self, args: dict[str, Any]) -> dict[str, Any]:
        name = str(args.get("name", ""))
        return {
            "schema_version": "klara.tool-stub.v1",
            "ok": True,
            "name": name,
            "version": "1.0.0",
            "scope": "project",
            "sha256": hashlib.sha256(name.encode("utf-8")).hexdigest(),
            "reference": args.get("reference", "SKILL.md"),
            "loaded": True,
            "body_content_exposed": False,
        }


def build_tool_backend() -> ToolBackend:
    """Factory seam for later replacement with the frozen fixture backend."""

    return DeterministicToolStub()


@dataclass
class RateLimiter:
    """Minimal asyncio-safe rate limiter (one request every N seconds)."""

    requests_per_minute: int = 20

    def __post_init__(self) -> None:
        self._interval = 60.0 / max(1, self.requests_per_minute)
        self._last_request_at = 0.0
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        while True:
            async with self._lock:
                now = time.monotonic()
                wait = self._last_request_at + self._interval - now
                if wait <= 0:
                    self._last_request_at = now
                    return
            await asyncio.sleep(wait)


@dataclass
class RolloutConfig:
    model: str = DEFAULT_MODEL
    base_url: str = DEFAULT_BASE_URL
    api_key_env: str = "DEEPSEEK_API_KEY"
    rollouts_per_task: int = 3
    max_concurrency: int = 4
    requests_per_minute: int = 20
    max_tool_calls: int = 8
    max_attempts: int = 4
    base_backoff_seconds: float = 1.0
    max_backoff_seconds: float = 20.0
    temperature: float = 0.2
    raw_path: Path = DEFAULT_RAW_PATH
    timeout_seconds: float = 60.0


@dataclass(frozen=True)
class Task:
    task_id: str
    instruction: str
    available_tools: tuple[str, ...] = ()
    expected_behavior: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "Task":
        if not isinstance(raw, dict):
            raise ValueError("task must be a JSON object")
        task_id = str(raw.get("task_id", "")).strip()
        instruction = str(raw.get("instruction", "")).strip()
        if not task_id:
            raise ValueError("task_id is required")
        if not instruction:
            raise ValueError(f"task {task_id or '<unknown>'} instruction is required")
        available_tools = tuple(
            str(name)
            for name in raw.get("available_tools", [])
            if str(name) in TOOL_NAMES
        )
        expected_behavior = raw.get("expected_behavior", {})
        if not isinstance(expected_behavior, dict):
            raise ValueError(f"task {task_id} expected_behavior must be an object")
        return cls(
            task_id=task_id,
            instruction=instruction,
            available_tools=available_tools,
            expected_behavior=expected_behavior,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "instruction": self.instruction,
            "available_tools": list(self.available_tools),
            "expected_behavior": dict(self.expected_behavior),
        }


@dataclass(frozen=True)
class ToolCallRecord:
    call_id: str
    name: str
    arguments: dict[str, Any]
    result: dict[str, Any]


@dataclass
class RolloutRecord:
    run_id: str
    task_id: str
    rollout_index: int
    model: str
    created_at: str
    task: dict[str, Any]
    messages: list[dict[str, Any]]
    tool_calls: list[dict[str, Any]]
    final_answer: str
    metrics: dict[str, float | int]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "run_id": self.run_id,
            "task_id": self.task_id,
            "rollout_index": self.rollout_index,
            "model": self.model,
            "created_at": self.created_at,
            "task": self.task,
            "messages": self.messages,
            "tool_calls": self.tool_calls,
            "final_answer": self.final_answer,
            "metrics": dict(self.metrics),
        }


def _message_from_response(message: Any) -> dict[str, Any]:
    """Convert an OpenAI message object to a serializable dict."""

    result: dict[str, Any] = {"role": message.role, "content": message.content or ""}
    tool_calls = getattr(message, "tool_calls", None)
    if tool_calls:
        result["tool_calls"] = [
            {
                "id": call.id,
                "type": getattr(call, "type", "function"),
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments or "{}",
                },
            }
            for call in tool_calls
        ]
    return result


def _parse_arguments(arguments_text: str, name: str, task_id: str) -> dict[str, Any]:
    try:
        parsed = json.loads(arguments_text or "{}")
    except json.JSONDecodeError as exc:
        raise ValueError(f"tool {name} returned invalid JSON arguments: {exc}") from exc
    if not isinstance(parsed, dict):
        raise ValueError(f"tool {name} arguments must be a JSON object")
    return parsed


async def _complete_with_retry(
    client: AsyncOpenAI,
    *,
    messages: list[dict[str, Any]],
    tools: list[dict[str, Any]],
    config: RolloutConfig,
    rate_limiter: RateLimiter,
) -> Any:
    """Call chat completions with a simple exponential-backoff retry policy."""

    last_error: Exception | None = None
    for attempt in range(1, config.max_attempts + 1):
        await rate_limiter.acquire()
        try:
            return await client.chat.completions.create(
                model=config.model,
                messages=messages,
                tools=tools,
                tool_choice="auto",
                temperature=config.temperature,
                timeout=config.timeout_seconds,
            )
        except (
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
            openai.InternalServerError,
        ) as exc:
            last_error = exc
            if attempt >= config.max_attempts:
                break
            delay = min(
                config.max_backoff_seconds,
                config.base_backoff_seconds * (2 ** (attempt - 1)),
            )
            await asyncio.sleep(delay)
        except openai.APIStatusError as exc:
            if exc.status_code >= 500 or exc.status_code == 429:
                last_error = exc
                if attempt >= config.max_attempts:
                    break
                delay = min(
                    config.max_backoff_seconds,
                    config.base_backoff_seconds * (2 ** (attempt - 1)),
                )
                await asyncio.sleep(delay)
            else:
                raise
    assert last_error is not None
    raise last_error


async def run_one_rollout(
    task: Task,
    *,
    client: AsyncOpenAI,
    tool_backend: ToolBackend,
    config: RolloutConfig,
    rate_limiter: RateLimiter,
    rollout_index: int,
) -> RolloutRecord:
    started = time.monotonic()
    available_tools = tuple(task.available_tools) or TOOL_NAMES
    tools = model_tools(available_tools)
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Task: {task.instruction}\n"
                f"Available tools: {', '.join(available_tools) or 'none'}."
            ),
        },
    ]
    tool_call_records: list[ToolCallRecord] = []
    total_input_tokens = 0
    total_output_tokens = 0
    attempts = 0

    for _turn in range(config.max_tool_calls + 2):
        response = await _complete_with_retry(
            client,
            messages=messages,
            tools=tools,
            config=config,
            rate_limiter=rate_limiter,
        )
        attempts += 1
        usage = getattr(response, "usage", None)
        if usage is not None:
            total_input_tokens += int(getattr(usage, "prompt_tokens", 0) or 0)
            total_output_tokens += int(getattr(usage, "completion_tokens", 0) or 0)

        message = response.choices[0].message
        assistant_message = _message_from_response(message)
        messages.append(assistant_message)

        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            final_answer = (message.content or "").strip()
            used_names = [item.name for item in tool_call_records]
            required_tools = [
                str(name)
                for name in task.expected_behavior.get("required_tools", [])
                if str(name) in TOOL_NAMES
            ]
            missing_required = [name for name in required_tools if name not in used_names]
            if missing_required:
                messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You answered before using every required tool. "
                            f"Call {', '.join(missing_required)} before the final answer. "
                            f"Call {missing_required[0]} now."
                        ),
                    }
                )
                continue
            if final_answer:
                break
            messages.append(
                {
                    "role": "user",
                    "content": "Please provide a concise Final Answer now.",
                }
            )
            continue

        for call in calls:
            name = str(call.function.name)
            arguments_text = str(call.function.arguments or "{}")
            arguments = _parse_arguments(arguments_text, name, task.task_id)
            result = await tool_backend.run(name, arguments)
            tool_call_id = str(getattr(call, "id", "") or "")
            tool_call_records.append(
                ToolCallRecord(
                    call_id=tool_call_id,
                    name=name,
                    arguments=arguments,
                    result=result,
                )
            )
            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call_id,
                    "name": name,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    final_answer = ""
    for item in reversed(messages):
        if item.get("role") == "assistant" and not item.get("tool_calls"):
            final_answer = str(item.get("content", "")).strip()
            if final_answer:
                break

    latency_ms = int((time.monotonic() - started) * 1000)
    run_id = _stable_id("rollout", task.task_id, rollout_index, started, length=14)
    return RolloutRecord(
        run_id=run_id,
        task_id=task.task_id,
        rollout_index=rollout_index,
        model=config.model,
        created_at=_now_iso(),
        task=task.to_dict(),
        messages=messages,
        tool_calls=[
            {
                "call_id": item.call_id,
                "name": item.name,
                "arguments": item.arguments,
                "result": item.result,
            }
            for item in tool_call_records
        ],
        final_answer=final_answer,
        metrics={
            "latency_ms": latency_ms,
            "input_tokens": total_input_tokens,
            "output_tokens": total_output_tokens,
            "total_tokens": total_input_tokens + total_output_tokens,
            "attempts": attempts,
        },
    )


def _load_tasks(path: Path) -> list[Task]:
    if not path.exists():
        raise FileNotFoundError(f"task pool not found: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        raw = raw.get("tasks", raw.get("data", []))
    if not isinstance(raw, list):
        raise ValueError("task pool must be a JSON list or an object with a 'tasks' list")
    tasks = [Task.from_dict(item) for item in raw]
    if not tasks:
        raise ValueError("task pool contains no tasks")
    return tasks


SMOKE_TASKS: list[dict[str, Any]] = [
    {
        "task_id": "smoke-001",
        "instruction": "Use current_time for Asia/Shanghai and tell me the current time in Shanghai.",
        "available_tools": ["current_time"],
        "expected_behavior": {"required_tools": ["current_time"], "min_tool_calls": 1, "max_tool_calls": 4},
    },
    {
        "task_id": "smoke-002",
        "instruction": "List the available skills with skills_list and summarize them.",
        "available_tools": ["skills_list"],
        "expected_behavior": {"required_tools": ["skills_list"], "min_tool_calls": 1, "max_tool_calls": 4},
    },
    {
        "task_id": "smoke-003",
        "instruction": "View the web-research skill with skill_view, then say whether it loaded.",
        "available_tools": ["skill_view"],
        "expected_behavior": {"required_tools": ["skill_view"], "min_tool_calls": 1, "max_tool_calls": 4},
    },
    {
        "task_id": "smoke-004",
        "instruction": "Search memory for the owner's smoke-test preferences with memory_search.",
        "available_tools": ["memory_search"],
        "expected_behavior": {"required_tools": ["memory_search"], "min_tool_calls": 1, "max_tool_calls": 4},
    },
    {
        "task_id": "smoke-005",
        "instruction": "Search the web for deterministic smoke test fixtures, then answer.",
        "available_tools": ["web_search"],
        "expected_behavior": {"required_tools": ["web_search"], "min_tool_calls": 1, "max_tool_calls": 4},
    },
    {
        "task_id": "smoke-006",
        "instruction": "Search the web for example.test, fetch the first result, and report what you found.",
        "available_tools": ["web_search", "web_fetch"],
        "expected_behavior": {"required_tools": ["web_search", "web_fetch"], "min_tool_calls": 2, "max_tool_calls": 6},
    },
    {
        "task_id": "smoke-007",
        "instruction": "Search the web for evidence, submit it with evidence_submit, then give a final answer.",
        "available_tools": ["web_search", "evidence_submit"],
        "expected_behavior": {"required_tools": ["web_search", "evidence_submit"], "min_tool_calls": 2, "max_tool_calls": 6},
    },
    {
        "task_id": "smoke-008",
        "instruction": "Record a short public activity update, then report the current time in UTC.",
        "available_tools": ["update_activity", "current_time"],
        "expected_behavior": {"required_tools": ["update_activity", "current_time"], "min_tool_calls": 2, "max_tool_calls": 6},
    },
    {
        "task_id": "smoke-009",
        "instruction": "Search the web and also search memory, then combine what you found into an answer.",
        "available_tools": ["web_search", "memory_search"],
        "expected_behavior": {"required_tools": ["web_search", "memory_search"], "min_tool_calls": 2, "max_tool_calls": 6},
    },
    {
        "task_id": "smoke-010",
        "instruction": "List skills, view the memory-hygiene skill, and confirm both tool calls succeeded.",
        "available_tools": ["skills_list", "skill_view"],
        "expected_behavior": {"required_tools": ["skills_list", "skill_view"], "min_tool_calls": 2, "max_tool_calls": 6},
    },
]


def _iter_rollout_jobs(tasks: list[Task], config: RolloutConfig):
    for task in tasks:
        for rollout_index in range(config.rollouts_per_task):
            yield task, rollout_index


async def _run_worker(
    task: Task,
    rollout_index: int,
    *,
    client: AsyncOpenAI,
    tool_backend: ToolBackend,
    config: RolloutConfig,
    rate_limiter: RateLimiter,
    semaphore: asyncio.Semaphore,
    append_lock: asyncio.Lock,
) -> dict[str, Any]:
    async with semaphore:
        try:
            record = await run_one_rollout(
                task,
                client=client,
                tool_backend=tool_backend,
                config=config,
                rate_limiter=rate_limiter,
                rollout_index=rollout_index,
            )
            line = json.dumps(
                record.to_dict(), ensure_ascii=False, sort_keys=True, separators=(",", ":")
            )
            async with append_lock:
                with config.raw_path.open("a", encoding="utf-8", newline="\n") as handle:
                    handle.write(line + "\n")
            return {
                "task_id": task.task_id,
                "rollout_index": rollout_index,
                "ok": True,
                "run_id": record.run_id,
                "tool_calls": len(record.tool_calls),
                "final_answer_chars": len(record.final_answer),
            }
        except Exception as exc:  # noqa: BLE001 - report one failed rollout, keep others alive
            return {
                "task_id": task.task_id,
                "rollout_index": rollout_index,
                "ok": False,
                "error": f"{type(exc).__name__}: {exc}",
            }


async def generate_rollouts(
    tasks: list[Task],
    *,
    config: RolloutConfig | None = None,
) -> list[dict[str, Any]]:
    config = config or RolloutConfig()
    config.raw_path.parent.mkdir(parents=True, exist_ok=True)

    if config.rollouts_per_task < 1:
        raise ValueError("rollouts_per_task must be >= 1")
    if config.max_concurrency < 1:
        raise ValueError("max_concurrency must be >= 1")

    if load_dotenv is not None:
        load_dotenv()
    api_key = os.environ.get(config.api_key_env)
    if not api_key:
        raise RuntimeError(
            f"missing {config.api_key_env}; create a .env file or set the environment variable"
        )

    client = AsyncOpenAI(
        api_key=api_key,
        base_url=config.base_url,
        max_retries=0,
    )
    tool_backend = build_tool_backend()
    rate_limiter = RateLimiter(requests_per_minute=config.requests_per_minute)
    semaphore = asyncio.Semaphore(config.max_concurrency)
    append_lock = asyncio.Lock()

    jobs = list(_iter_rollout_jobs(tasks, config))
    results = await asyncio.gather(
        *[
            _run_worker(
                task,
                rollout_index,
                client=client,
                tool_backend=tool_backend,
                config=config,
                rate_limiter=rate_limiter,
                semaphore=semaphore,
                append_lock=append_lock,
            )
            for task, rollout_index in jobs
        ]
    )
    return list(results)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate DeepSeek V4 Pro teacher trajectories")
    parser.add_argument("--tasks", type=Path, default=DEFAULT_TASKS_PATH)
    parser.add_argument("--smoke", action="store_true", help="use the built-in 10-task smoke set")
    parser.add_argument("--raw", type=Path, default=DEFAULT_RAW_PATH)
    parser.add_argument("--truncate", action="store_true", help="empty raw.jsonl before appending")
    parser.add_argument("--rollouts", type=int, default=3)
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--requests-per-minute", type=int, default=20)
    parser.add_argument("--max-tool-calls", type=int, default=8)
    parser.add_argument("--max-attempts", type=int, default=4)
    parser.add_argument("--model", default=DEFAULT_MODEL)
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--timeout", type=float, default=60.0)
    return parser.parse_args(argv)


async def _main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.smoke:
        tasks = [Task.from_dict(item) for item in SMOKE_TASKS]
    else:
        tasks_path = args.tasks
        if not tasks_path.exists() and tasks_path == DEFAULT_TASKS_PATH:
            smoke_path = Path("data/trajectories/smoke_tasks.json")
            if smoke_path.exists():
                print(
                    "teacher_rollout: default task pool missing; "
                    f"using smoke tasks: {smoke_path}"
                )
                tasks_path = smoke_path
        tasks = _load_tasks(tasks_path)

    if args.truncate:
        args.raw.parent.mkdir(parents=True, exist_ok=True)
        args.raw.write_text("", encoding="utf-8")

    config = RolloutConfig(
        model=args.model,
        base_url=args.base_url,
        rollouts_per_task=args.rollouts,
        max_concurrency=args.max_concurrency,
        requests_per_minute=args.requests_per_minute,
        max_tool_calls=args.max_tool_calls,
        max_attempts=args.max_attempts,
        temperature=args.temperature,
        raw_path=args.raw,
        timeout_seconds=args.timeout,
    )
    print(
        "teacher_rollout: "
        f"tasks={len(tasks)} rollouts_per_task={config.rollouts_per_task} "
        f"concurrency={config.max_concurrency} rpm={config.requests_per_minute} "
        f"model={config.model} raw={config.raw_path}"
    )
    results = await generate_rollouts(tasks, config=config)
    ok = [item for item in results if item["ok"]]
    failed = [item for item in results if not item["ok"]]
    print(f"teacher_rollout: succeeded={len(ok)} failed={len(failed)} total={len(results)}")
    for item in failed[:20]:
        print(f"teacher_rollout: FAILED {item['task_id']} r={item['rollout_index']} {item['error']}")
    return 0 if ok else 1


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_main(argv))


if __name__ == "__main__":
    raise SystemExit(main())
