"""Frozen, deterministic tool backend for the three-way evaluation harness.

In ``eval_mode`` every tool observation is resolved from an immutable fixture
store keyed by ``(tool_name, arguments)``. The same logical call therefore
always returns the same ``ToolResult``, which is the property that makes the
frozen harness comparable across klara/qwen/deepseek runs.

Outside eval mode this class delegates to a real :class:`klara.core.tools.ToolRunner`
(or any object exposing ``specs`` and ``execute_many``), which keeps the
boundary useful for pre-generating fixtures and for ordinary runtime use.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from typing import Any, Iterable, Protocol

from klara.core.tools import (
    JsonObject,
    ToolCall,
    ToolExecutionReport,
    ToolResult,
    ToolSpec,
)
from klara.eval.trajectory import canonical_json


FIXTURE_SCHEMA_VERSION = "klara.frozen-tool-fixture.v1"
MISSING_FIXTURE_ERROR_PREFIX = "FrozenToolBackend.missing_fixture:"
UNKNOWN_TOOL_ERROR_PREFIX = "FrozenToolBackend.unknown_tool:"


class ToolBackend(Protocol):
    """Minimal real-backend contract needed by ``FrozenToolBackend``."""

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        """Return visible tool specifications."""

        ...

    def execute_many(self, calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
        """Execute one batch of tool calls."""

        ...


@dataclass(frozen=True)
class FixtureResult:
    """Stable observation body stored inside a frozen fixture."""

    content: str = ""
    ok: bool = True
    error: str | None = None
    public_content: str | None = None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the result without exposing execution provenance."""

        data: dict[str, Any] = {
            "content": self.content,
            "ok": self.ok,
        }
        if self.error is not None:
            data["error"] = self.error
        if self.public_content is not None:
            data["public_content"] = self.public_content
        return data

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FixtureResult":
        """Parse a fixture result with a fail-closed missing-field policy."""

        if not isinstance(raw, dict):
            raise ValueError("fixture result must be an object")
        content = raw.get("content")
        if not isinstance(content, str):
            content = str(content) if content is not None else ""
        ok = bool(raw.get("ok", True))
        error = raw.get("error")
        public_content = raw.get("public_content")
        return cls(
            content=content,
            ok=ok,
            error=str(error) if error is not None else None,
            public_content=str(public_content) if public_content is not None else None,
        )


@dataclass(frozen=True)
class FixtureEntry:
    """One ``(tool_name, arguments) -> result`` fixture record."""

    tool_name: str
    arguments: JsonObject
    result: FixtureResult

    def to_dict(self) -> dict[str, Any]:
        """Serialize one fixture entry."""

        return {
            "tool_name": self.tool_name,
            "arguments": dict(self.arguments),
            "result": self.result.to_dict(),
        }


@dataclass(frozen=True)
class FrozenToolFixture:
    """Serializable fixture store for one task set."""

    schema_version: str = FIXTURE_SCHEMA_VERSION
    task_set: str = "default"
    tools: tuple[ToolSpec, ...] = ()
    entries: tuple[FixtureEntry, ...] = ()

    def __post_init__(self) -> None:
        """Reject duplicate keys and unsupported schema versions."""

        if self.schema_version != FIXTURE_SCHEMA_VERSION:
            raise ValueError(f"unsupported fixture schema: {self.schema_version}")
        seen: set[str] = set()
        for entry in self.entries:
            key = fixture_key(entry.tool_name, entry.arguments)
            if key in seen:
                raise ValueError(f"duplicate fixture key: {key}")
            seen.add(key)

    @property
    def tool_names(self) -> frozenset[str]:
        """Return the frozen tool names visible to the model."""

        return frozenset(tool.name for tool in self.tools)

    def lookup(self, tool_name: str, arguments: JsonObject) -> FixtureResult | None:
        """Return the deterministic result for one logical call, if present."""

        key = fixture_key(tool_name, arguments)
        for entry in self.entries:
            if fixture_key(entry.tool_name, entry.arguments) == key:
                return entry.result
        return None

    def to_dict(self) -> dict[str, Any]:
        """Serialize the complete fixture store."""

        return {
            "schema_version": self.schema_version,
            "task_set": self.task_set,
            "tools": [tool.to_public_dict() for tool in self.tools],
            "entries": [entry.to_dict() for entry in self.entries],
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "FrozenToolFixture":
        """Parse a fixture store from JSON-compatible data."""

        if not isinstance(raw, dict):
            raise ValueError("fixture must be an object")
        raw_tools = raw.get("tools", [])
        tools = tuple(
            ToolSpec(
                name=str(item["name"]),
                description=str(item.get("description", item["name"])),
                input_schema=dict(item.get("input_schema") or {"type": "object"}),
            )
            for item in raw_tools
            if isinstance(item, dict)
        )
        entries = tuple(
            FixtureEntry(
                tool_name=str(item["tool_name"]),
                arguments=dict(item.get("arguments", {})),
                result=FixtureResult.from_dict(item["result"]),
            )
            for item in raw.get("entries", [])
            if isinstance(item, dict)
        )
        return cls(
            schema_version=str(raw.get("schema_version", FIXTURE_SCHEMA_VERSION)),
            task_set=str(raw.get("task_set", "default")),
            tools=tools,
            entries=entries,
        )

    def save(self, path: str | Path) -> None:
        """Write the fixture to a UTF-8 JSON file."""

        destination = Path(path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    @classmethod
    def load(cls, path: str | Path) -> "FrozenToolFixture":
        """Load a fixture from a JSON file."""

        raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        return cls.from_dict(raw)


def fixture_key(tool_name: str, arguments: JsonObject) -> str:
    """Return a stable key for one frozen tool call."""

    if not tool_name.strip():
        raise ValueError("tool_name must not be empty")
    return f"{tool_name}:{canonical_json(dict(arguments))}"


def _tool_result_from_fixture(
    *,
    call: ToolCall,
    fixture: FrozenToolFixture,
) -> ToolResult:
    """Resolve one call against the frozen store.

    The result is deterministic for every ``(tool_name, arguments)`` pair:
    either the stored fixture result or a stable missing/unknown error.
    """

    tool_names = {tool.name for tool in fixture.tools}
    if call.name not in tool_names:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="",
            ok=False,
            error=f"{UNKNOWN_TOOL_ERROR_PREFIX}{call.name}",
        )
    record = fixture.lookup(call.name, call.arguments)
    if record is None:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="",
            ok=False,
            error=f"{MISSING_FIXTURE_ERROR_PREFIX}{fixture_key(call.name, call.arguments)}",
        )
    return ToolResult(
        tool_call_id=call.id,
        name=call.name,
        content=record.content,
        ok=record.ok,
        error=record.error,
        public_content=record.public_content,
    )


class FrozenToolBackend:
    """ToolRunner-compatible backend with a frozen eval mode."""

    def __init__(
        self,
        *,
        fixture: FrozenToolFixture | None = None,
        eval_mode: bool = True,
        real_backend: ToolBackend | None = None,
        tool_specs: tuple[ToolSpec, ...] = (),
    ) -> None:
        """Create a frozen backend.

        Args:
            fixture: Frozen fixture used in eval mode.
            eval_mode: When true, all observations come from ``fixture``.
            real_backend: Real tool executor used outside eval mode and by
                fixture pre-generation.
            tool_specs: Fallback tool specs when no fixture is supplied.
        """

        self.fixture = fixture
        self.eval_mode = eval_mode
        self.real_backend = real_backend
        self._fallback_tool_specs = tuple(tool_specs)

    @property
    def specs(self) -> tuple[ToolSpec, ...]:
        """Return model-visible tool specs for the active mode."""

        if self.eval_mode:
            if self.fixture is not None and self.fixture.tools:
                return self.fixture.tools
            return self._fallback_tool_specs
        if self.real_backend is None:
            return self._fallback_tool_specs
        return self.real_backend.specs

    def execute(self, call: ToolCall) -> ToolResult:
        """Execute one tool call."""

        results = self.execute_many((call,))
        return results[0]

    def execute_many(self, calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
        """Execute a batch of tool calls in request order."""

        if self.eval_mode:
            if self.fixture is None:
                return tuple(
                    ToolResult(
                        tool_call_id=call.id,
                        name=call.name,
                        content="",
                        ok=False,
                        error=f"{MISSING_FIXTURE_ERROR_PREFIX}{fixture_key(call.name, call.arguments)}",
                    )
                    for call in calls
                )
            return tuple(
                _tool_result_from_fixture(call=call, fixture=self.fixture)
                for call in calls
            )

        if self.real_backend is None:
            raise RuntimeError("non-eval FrozenToolBackend requires a real_backend")
        if hasattr(self.real_backend, "execute_many"):
            return self.real_backend.execute_many(calls)
        return tuple(self.real_backend.execute(call) for call in calls)

    def execute_many_with_reports(
        self,
        calls: tuple[ToolCall, ...],
    ) -> tuple[ToolExecutionReport, ...]:
        """Execute one batch and attach timing metadata."""

        started_at = datetime.now(UTC).isoformat()
        results = self.execute_many(calls)
        completed_at = datetime.now(UTC).isoformat()
        return tuple(
            ToolExecutionReport(
                call=call,
                result=result,
                duration_ms=0,
                started_at=started_at,
                completed_at=completed_at,
            )
            for call, result in zip(calls, results)
        )

    def pre_generate_fixture(
        self,
        tasks: Iterable[Any],
        *,
        task_set: str,
        real_backend: ToolBackend | None = None,
        tool_specs: tuple[ToolSpec, ...] | None = None,
    ) -> FrozenToolFixture:
        """Generate a frozen fixture from a task set using a real backend.

        Each ``task.expected_tool_calls`` item is executed exactly once against
        the real backend. The resulting observations become deterministic
        fixture records keyed by ``(tool_name, arguments)``. Tools and expected
        calls are expected to be public evaluation data, not hidden reasoning.
        """

        backend = real_backend or self.real_backend
        if backend is None:
            raise RuntimeError("pre_generate_fixture requires a real_backend")
        materialized = tuple(tasks)
        if not materialized:
            raise ValueError("pre_generate_fixture requires at least one task")
        if not tool_specs:
            tool_specs = backend.specs

        entries: list[FixtureEntry] = []
        seen: set[str] = set()
        for task_index, task in enumerate(materialized):
            expected_calls = getattr(task, "expected_tool_calls", ())
            if not expected_calls:
                continue
            for call_index, expected in enumerate(expected_calls):
                name = getattr(expected, "name", None)
                if name is None and isinstance(expected, dict):
                    name = expected.get("name", "")
                name = str(name or "")
                arguments = getattr(expected, "arguments", None)
                if arguments is None and isinstance(expected, dict):
                    arguments = expected.get("arguments", {})
                arguments = dict(arguments or {})
                key = fixture_key(name, arguments)
                if key in seen:
                    continue
                call = ToolCall(
                    id=f"fixture-{task_index}-{call_index}",
                    name=name,
                    arguments=arguments,
                )
                result = backend.execute_many((call,))[0]
                seen.add(key)
                entries.append(
                    FixtureEntry(
                        tool_name=name,
                        arguments=arguments,
                        result=FixtureResult(
                            content=result.content,
                            ok=result.ok,
                            error=result.error,
                            public_content=result.public_content,
                        ),
                    )
                )
        return FrozenToolFixture(
            task_set=task_set,
            tools=tuple(tool_specs),
            entries=tuple(entries),
        )

    @classmethod
    def from_fixture(
        cls,
        fixture: FrozenToolFixture,
    ) -> "FrozenToolBackend":
        """Create an eval-mode backend from an already-loaded fixture."""

        return cls(fixture=fixture, eval_mode=True)

    @classmethod
    def load_fixture_backend(cls, path: str | Path) -> "FrozenToolBackend":
        """Load a fixture JSON file and return an eval-mode backend."""

        return cls.from_fixture(FrozenToolFixture.load(path))
