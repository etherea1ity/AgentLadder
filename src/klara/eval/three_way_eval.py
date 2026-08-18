"""Unified three-way evaluation harness for klara/qwen/deepseek.

The public entry point is :func:`evaluate(model, benchmark, harness)`. It runs
one benchmark against one model adapter while keeping the same harness, tool
schema, hidden set, decode budget, and frozen tool backend across the three
candidate routes. The returned dict contains the frozen metrics contract:

- task_success
- tool_call_accuracy
- invalid_call_rate
- token_usage
- latency
- cost
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from pathlib import Path
from time import perf_counter
from typing import Any, Iterable, Protocol

from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolCall, ToolSpec
from klara.eval.frozen_tool_backend import (
    FrozenToolBackend,
    FrozenToolFixture,
    MISSING_FIXTURE_ERROR_PREFIX,
    UNKNOWN_TOOL_ERROR_PREFIX,
)
from klara.infra.config.loader import load_models_config
from klara.infra.config.models import ProviderConfig
from klara.infra.llm.model_ref import ModelRef
from klara.infra.llm.openai_compatible import (
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
)

EVAL_SCHEMA_VERSION = "klara.three-way-eval.v1"
DEFAULT_DEEPSEEK_MODEL = "deepseek/deepseek-v4-pro"
DEFAULT_QWEN_MODEL = "qwen/qwen3.7-flash"
DEFAULT_KLARA_MODEL = "klara/klara-124m"

DEFAULT_SYSTEM_PROMPT = (
    "You are Klara under a frozen-tool evaluation. Use only the supplied tools. "
    "When a task asks you to call a tool, call exactly that tool with the exact "
    "required arguments, then answer using only the returned observation. Do not "
    "invent tool results."
)


class ModelAdapter(Protocol):
    """Provider-independent adapter used by the unified harness."""

    @property
    def model(self) -> str:
        """Return the full provider/model reference."""

        ...

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> ModelResponse:
        """Produce one model response for the current transcript."""

        ...


@dataclass(frozen=True)
class ExpectedToolCall:
    """One public tool action expected by a frozen task."""

    name: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "arguments": dict(self.arguments)}


@dataclass(frozen=True)
class EvalTask:
    """One public benchmark task."""

    id: str
    user_turn: str
    reference_answer: str | None = None
    acceptable_answers: tuple[str, ...] = ()
    expected_tool_calls: tuple[ExpectedToolCall, ...] = ()
    must_call_tools: tuple[str, ...] = ()
    may_call_tools: tuple[str, ...] = ()
    max_steps: int | None = None

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvalTask":
        if not isinstance(raw, dict):
            raise ValueError("task must be an object")
        return cls(
            id=str(raw["id"]),
            user_turn=str(raw["user_turn"]),
            reference_answer=(
                str(raw["reference_answer"])
                if raw.get("reference_answer") is not None
                else None
            ),
            acceptable_answers=tuple(
                str(item) for item in raw.get("acceptable_answers", [])
            ),
            expected_tool_calls=tuple(
                ExpectedToolCall(
                    name=str(item["name"]),
                    arguments=dict(item.get("arguments", {})),
                )
                for item in raw.get("expected_tool_calls", [])
                if isinstance(item, dict)
            ),
            must_call_tools=tuple(str(item) for item in raw.get("must_call_tools", [])),
            may_call_tools=tuple(str(item) for item in raw.get("may_call_tools", [])),
            max_steps=(
                int(raw["max_steps"]) if raw.get("max_steps") is not None else None
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "user_turn": self.user_turn,
            "reference_answer": self.reference_answer,
            "acceptable_answers": list(self.acceptable_answers),
            "expected_tool_calls": [item.to_dict() for item in self.expected_tool_calls],
            "must_call_tools": list(self.must_call_tools),
            "may_call_tools": list(self.may_call_tools),
            "max_steps": self.max_steps,
        }


@dataclass(frozen=True)
class EvalBenchmark:
    """A task set plus model-visible tool schema."""

    name: str
    tasks: tuple[EvalTask, ...]
    tools: tuple[ToolSpec, ...] = ()
    system_prompt: str = DEFAULT_SYSTEM_PROMPT

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> "EvalBenchmark":
        if not isinstance(raw, dict):
            raise ValueError("benchmark must be an object")
        tasks = tuple(
            EvalTask.from_dict(item)
            for item in raw.get("tasks", [])
            if isinstance(item, dict)
        )
        if not tasks:
            raise ValueError("benchmark must contain at least one task")
        tools = tuple(
            ToolSpec(
                name=str(item["name"]),
                description=str(item.get("description", item["name"])),
                input_schema=dict(item.get("input_schema") or {"type": "object"}),
            )
            for item in raw.get("tools", [])
            if isinstance(item, dict)
        )
        return cls(
            name=str(raw.get("name", "eval-benchmark")),
            tasks=tasks,
            tools=tools,
            system_prompt=str(raw.get("system_prompt", DEFAULT_SYSTEM_PROMPT)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "system_prompt": self.system_prompt,
            "tools": [tool.to_public_dict() for tool in self.tools],
            "tasks": [task.to_dict() for task in self.tasks],
        }


@dataclass(frozen=True)
class Pricing:
    """Cost accounting used by the harness."""

    currency: str = "USD"
    input_usd_per_million: float = 0.0
    output_usd_per_million: float = 0.0


@dataclass(frozen=True)
class EvalHarness:
    """Immutable harness settings shared by all three model routes."""

    backend: Any
    max_steps: int = 8
    max_tokens: int = 512
    temperature: float = 0.0
    timeout_seconds: int = 120
    retry_attempts: int = 2
    retry_base_delay_seconds: float = 0.0
    retry_max_delay_seconds: float = 0.0
    ordered_tool_calls: bool = False
    pricing: Pricing = field(default_factory=Pricing)
    root: Path = field(default_factory=Path.cwd)

    def __post_init__(self) -> None:
        if self.max_steps < 1:
            raise ValueError("max_steps must be positive")
        if self.max_tokens < 1:
            raise ValueError("max_tokens must be positive")
        if self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be positive")
        if self.retry_attempts < 1:
            raise ValueError("retry_attempts must be at least 1")


class OpenAICompatibleModelAdapter:
    """Shared adapter for DeepSeek and Qwen OpenAI-compatible endpoints."""

    def __init__(
        self,
        *,
        model: str,
        provider: ProviderConfig,
        provider_id: str,
        settings: OpenAICompatibleSettings,
        dotenv_path: str | Path | None,
    ) -> None:
        self._model = ModelRef.parse(model)
        if self._model.provider != provider_id:
            raise ValueError(f"provider_id {provider_id} cannot serve model {model}")
        self._client = OpenAICompatibleLlmClient(
            provider_id=provider_id,
            provider=provider,
            settings=settings,
            dotenv_path=str(dotenv_path) if dotenv_path is not None else None,
        )

    @property
    def model(self) -> str:
        return str(self._model)

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> ModelResponse:
        return self._client.complete(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
            model=self.model,
            thinking_enabled=False,
        )


class DeepSeekModelAdapter(OpenAICompatibleModelAdapter):
    """DeepSeek V4 API adapter backed by ``DEEPSEEK_API_KEY``."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_DEEPSEEK_MODEL,
        provider: ProviderConfig | None = None,
        root: str | Path = ".",
        settings: OpenAICompatibleSettings | None = None,
    ) -> None:
        model_ref = ModelRef.parse(model)
        if model_ref.provider != "deepseek":
            raise ValueError(f"DeepSeek adapter cannot serve {model}")
        provider = provider or load_models_config(Path(root) / "config").providers["deepseek"]
        self._root = Path(root)
        super().__init__(
            model=model,
            provider=provider,
            provider_id="deepseek",
            settings=settings or OpenAICompatibleSettings(),
            dotenv_path=self._root / ".env",
        )


class QwenModelAdapter(OpenAICompatibleModelAdapter):
    """Qwen API adapter using the same OpenAI-compatible boundary."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_QWEN_MODEL,
        provider: ProviderConfig | None = None,
        root: str | Path = ".",
        settings: OpenAICompatibleSettings | None = None,
    ) -> None:
        model_ref = ModelRef.parse(model)
        if model_ref.provider != "qwen":
            raise ValueError(f"Qwen adapter cannot serve {model}")
        provider = provider or load_models_config(Path(root) / "config").providers["qwen"]
        self._root = Path(root)
        super().__init__(
            model=model,
            provider=provider,
            provider_id="qwen",
            settings=settings or OpenAICompatibleSettings(),
            dotenv_path=self._root / ".env",
        )


class KlaraModelAdapter:
    """Reserved adapter for the local trained Klara model.

    The local policy/runtime boundary is not part of this first DeepSeek
    smoke. The interface is intentionally present so the three-way harness
    can add it without changing ``evaluate``.
    """

    def __init__(self, *, model: str = DEFAULT_KLARA_MODEL, **_: Any) -> None:
        self._model = model

    @property
    def model(self) -> str:
        return self._model

    def complete(
        self,
        *,
        system_prompt: str,
        messages: tuple[KlaraMessage, ...],
        tools: tuple[ToolSpec, ...],
    ) -> ModelResponse:
        raise NotImplementedError(
            "KlaraModelAdapter is reserved for the trained local model; "
            "run deepseek or qwen first"
        )


def build_model_adapter(
    model: str,
    *,
    root: str | Path = ".",
    settings: OpenAICompatibleSettings | None = None,
) -> ModelAdapter:
    """Build one adapter from ``klara``, ``qwen``, or ``deepseek`` aliases."""

    normalized = model.strip()
    if not normalized:
        raise ValueError("model must not be empty")
    if normalized == "klara" or normalized.startswith("klara/"):
        return KlaraModelAdapter(model=normalized if "/" in normalized else DEFAULT_KLARA_MODEL)
    if normalized == "qwen" or normalized.startswith("qwen/"):
        target = normalized if "/" in normalized else DEFAULT_QWEN_MODEL
        return QwenModelAdapter(model=target, root=root, settings=settings)
    if normalized == "deepseek" or normalized.startswith("deepseek/"):
        target = normalized if "/" in normalized else DEFAULT_DEEPSEEK_MODEL
        return DeepSeekModelAdapter(model=target, root=root, settings=settings)
    # Provider-less aliases match the public acceptance wording, e.g.
    # model=deepseek-v4-pro, while preserving the repo's provider/model refs.
    if normalized.startswith("deepseek-") and "/" not in normalized:
        return DeepSeekModelAdapter(
            model=f"deepseek/{normalized}",
            root=root,
            settings=settings,
        )
    if normalized.startswith("qwen") and "/" not in normalized:
        return QwenModelAdapter(
            model=f"qwen/{normalized}",
            root=root,
            settings=settings,
        )
    try:
        model_ref = ModelRef.parse(normalized)
    except ValueError as exc:
        raise ValueError(f"unsupported model alias: {model!r}") from exc
    if model_ref.provider == "deepseek":
        return DeepSeekModelAdapter(model=normalized, root=root, settings=settings)
    if model_ref.provider == "qwen":
        return QwenModelAdapter(model=normalized, root=root, settings=settings)
    if model_ref.provider == "klara":
        return KlaraModelAdapter(model=normalized)
    raise ValueError(f"unsupported model provider: {model_ref.provider}")


@dataclass(frozen=True)
class EvalTaskResult:
    """Per-task public metrics and trace."""

    task_id: str
    success: bool
    final_answer: str
    observed_tool_calls: tuple[dict[str, Any], ...]
    tool_call_accuracy: float
    invalid_calls: int
    total_calls: int
    token_usage: dict[str, int]
    latency_ms: int
    cost_usd: float
    error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "success": self.success,
            "final_answer": self.final_answer,
            "observed_tool_calls": list(self.observed_tool_calls),
            "tool_call_accuracy": self.tool_call_accuracy,
            "invalid_calls": self.invalid_calls,
            "total_calls": self.total_calls,
            "token_usage": dict(self.token_usage),
            "latency_ms": self.latency_ms,
            "cost_usd": self.cost_usd,
            "error": self.error,
        }


def load_eval_bundle(path: str | Path) -> tuple[EvalBenchmark, FrozenToolBackend]:
    """Load one JSON file containing both benchmark and frozen fixture entries."""

    raw = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    benchmark = EvalBenchmark.from_dict(raw)
    fixture = FrozenToolFixture.from_dict(raw)
    # The benchmark tool schema is the same tool schema frozen by the contract.
    if {tool.name for tool in fixture.tools} != {tool.name for tool in benchmark.tools}:
        raise ValueError("benchmark tools and frozen fixture tools must match")
    return benchmark, FrozenToolBackend.from_fixture(fixture)


def evaluate(
    model: str,
    benchmark: EvalBenchmark,
    harness: EvalHarness,
    *,
    adapter: ModelAdapter | None = None,
) -> dict[str, Any]:
    """Run one benchmark through one model route and aggregate metrics."""

    if not benchmark.tasks:
        raise ValueError("benchmark must contain tasks")
    adapter_settings = OpenAICompatibleSettings(
        max_tokens=harness.max_tokens,
        temperature=harness.temperature,
        timeout_seconds=harness.timeout_seconds,
        retry_attempts=harness.retry_attempts,
        retry_base_delay_seconds=harness.retry_base_delay_seconds,
        retry_max_delay_seconds=harness.retry_max_delay_seconds,
    )
    resolved_adapter = adapter or build_model_adapter(
        model,
        root=harness.root,
        settings=adapter_settings,
    )
    task_results = tuple(
        harness.run_task(resolved_adapter, task, benchmark)
        for task in benchmark.tasks
    )
    successful_tasks = sum(result.success for result in task_results)
    total_calls = sum(result.total_calls for result in task_results)
    invalid_calls = sum(result.invalid_calls for result in task_results)
    token_usage = _aggregate_usage(result.token_usage for result in task_results)
    total_latency_ms = sum(result.latency_ms for result in task_results)
    cost_usd = sum(result.cost_usd for result in task_results)
    metrics = {
        "task_success": _ratio(successful_tasks, len(task_results)),
        "tool_call_accuracy": _ratio(
            sum(result.tool_call_accuracy for result in task_results),
            len(task_results),
        ),
        "invalid_call_rate": _ratio(invalid_calls, total_calls),
        "token_usage": token_usage,
        "latency": {
            "total_ms": total_latency_ms,
            "mean_ms": _ratio(total_latency_ms, len(task_results)),
        },
        "cost": {
            "currency": harness.pricing.currency,
            "amount_usd": round(cost_usd, 8),
        },
    }
    return {
        "schema_version": EVAL_SCHEMA_VERSION,
        "model": model,
        "adapter_model": resolved_adapter.model,
        "benchmark": benchmark.name,
        "evaluated_at": datetime.now(UTC).isoformat(),
        "counts": {
            "tasks": len(task_results),
            "successful_tasks": successful_tasks,
            "tool_calls": total_calls,
            "invalid_calls": invalid_calls,
        },
        "metrics": metrics,
        "tasks": [result.to_dict() for result in task_results],
    }


def _aggregate_usage(items: Iterable[dict[str, int]]) -> dict[str, int]:
    usage = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    for item in items:
        for key in usage:
            usage[key] += int(item.get(key, 0))
    if usage["total_tokens"] == 0:
        usage["total_tokens"] = usage["prompt_tokens"] + usage["completion_tokens"]
    return usage


def _ratio(numerator: float | int, denominator: int) -> float:
    return float(numerator) / denominator if denominator else 0.0


# Attach the run_task implementation to EvalHarness as a method for readable
# ``harness.run_task(...)`` calls. It is kept separate so the dataclass remains
# serializable and easy to inspect.
def _harness_run_task(
    harness: EvalHarness,
    adapter: ModelAdapter,
    task: EvalTask,
    benchmark: EvalBenchmark,
) -> EvalTaskResult:
    """Run one task to completion or exhaustion."""

    started = perf_counter()
    messages: list[KlaraMessage] = [KlaraMessage(role="user", content=task.user_turn)]
    observed: list[ToolCall] = []
    invalid_calls = 0
    usage: dict[str, int] = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    final_answer = ""
    error: str | None = None

    try:
        max_steps = task.max_steps or harness.max_steps
        for _ in range(max_steps):
            response = adapter.complete(
                system_prompt=benchmark.system_prompt,
                messages=tuple(messages),
                tools=benchmark.tools,
            )
            usage = _add_usage(usage, response.usage)
            if not response.tool_calls:
                final_answer = response.content.strip()
                break

            messages.append(
                KlaraMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            valid_calls: list[ToolCall] = []
            valid_flags: list[bool] = []
            for call in response.tool_calls:
                observed.append(call)
                is_valid = _call_is_valid(call, benchmark.tools)
                if not is_valid:
                    invalid_calls += 1
                valid_calls.append(call)
                valid_flags.append(is_valid)

            results = harness.backend.execute_many(tuple(valid_calls))
            for call, result, was_valid in zip(valid_calls, results, valid_flags):
                if was_valid and not result.ok and _is_frozen_eval_error(result.error or ""):
                    invalid_calls += 1
                messages.append(
                    KlaraMessage(
                        role="tool",
                        content=result.content if result.ok else (result.error or ""),
                        name=result.name,
                        tool_call_id=call.id,
                    )
                )
            if _repeat_tool_call_sequence(tuple(observed), harness.max_steps):
                final_answer = ""
                break
        else:
            error = "max_steps_exhausted"
    except NotImplementedError:
        raise
    except Exception as exc:  # provider/network/schema failures stay visible
        error = f"{type(exc).__name__}: {exc}"

    latency_ms = max(0, int((perf_counter() - started) * 1000))
    accuracy = tool_call_accuracy(
        task,
        tuple(observed),
        ordered=harness.ordered_tool_calls,
    )
    answer_ok = _answer_matches(task, final_answer)
    success = bool(answer_ok and error is None)
    if not task.acceptable_answers and not task.reference_answer:
        success = bool(error is None and accuracy >= 1.0)
    cost_usd = calculate_cost(usage, harness.pricing)
    return EvalTaskResult(
        task_id=task.id,
        success=success,
        final_answer=final_answer,
        observed_tool_calls=tuple(_tool_call_public_dict(call) for call in observed),
        tool_call_accuracy=accuracy,
        invalid_calls=invalid_calls,
        total_calls=len(observed),
        token_usage=usage,
        latency_ms=latency_ms,
        cost_usd=cost_usd,
        error=error,
    )


EvalHarness.run_task = _harness_run_task  # type: ignore[attr-defined]


def tool_call_accuracy(
    task: EvalTask,
    observed_calls: tuple[ToolCall, ...],
    *,
    ordered: bool = False,
) -> float:
    """Return the fraction of expected public tool calls observed."""

    expected = tuple(task.expected_tool_calls)
    observed = tuple(observed_calls)
    if not expected and not observed:
        return 1.0
    if not expected or not observed:
        return 0.0
    remaining = list(observed)
    matched = 0
    cursor = 0
    for want in expected:
        for index, candidate in enumerate(remaining):
            if _expected_matches_observed(want, candidate):
                if ordered and index < cursor:
                    continue
                matched += 1
                remaining.pop(index)
                cursor = index
                break
    denominator = max(len(expected), len(observed))
    return _ratio(matched, denominator)


def _expected_matches_observed(
    expected: ExpectedToolCall,
    observed: ToolCall,
) -> bool:
    return expected.name == observed.name and expected.arguments == dict(observed.arguments)


def _call_is_valid(call: ToolCall, tools: tuple[ToolSpec, ...]) -> bool:
    """Return whether one model call targets a known tool with valid args."""

    spec = next((tool for tool in tools if tool.name == call.name), None)
    if spec is None:
        return False
    return _arguments_valid(call.arguments, spec.input_schema)


def _arguments_valid(arguments: dict[str, Any], schema: dict[str, Any]) -> bool:
    """Small JSON-schema subset validation for tool arguments."""

    if not isinstance(schema, dict):
        return True
    properties = schema.get("properties")
    required = schema.get("required")
    if isinstance(required, list):
        for key in required:
            if key not in arguments:
                return False
    if isinstance(properties, dict):
        for key, value in arguments.items():
            expected = properties.get(key)
            if expected is None:
                if schema.get("additionalProperties") is False:
                    return False
                continue
            if not _json_value_matches(value, expected):
                return False
    return True


def _json_value_matches(value: Any, schema: dict[str, Any]) -> bool:
    expected_type = schema.get("type")
    if expected_type == "string":
        return isinstance(value, str)
    if expected_type == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected_type == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected_type == "boolean":
        return isinstance(value, bool)
    if expected_type == "array":
        return isinstance(value, list)
    if expected_type == "object":
        return isinstance(value, dict)
    return True


def _is_frozen_eval_error(error: str) -> bool:
    return error.startswith(MISSING_FIXTURE_ERROR_PREFIX) or error.startswith(
        UNKNOWN_TOOL_ERROR_PREFIX
    )


def _repeat_tool_call_sequence(
    observed: tuple[ToolCall, ...],
    max_steps: int,
) -> bool:
    """Stop loops that call the same single tool forever."""

    if len(observed) < 3 or max_steps < 3:
        return False
    recent = tuple(
        (call.name, json.dumps(dict(call.arguments), sort_keys=True, ensure_ascii=False))
        for call in observed[-3:]
    )
    return len(set(recent)) == 1


def _tool_call_public_dict(call: ToolCall) -> dict[str, Any]:
    return {"id": call.id, "name": call.name, "arguments": dict(call.arguments)}


def _add_usage(
    current: dict[str, int],
    usage: dict[str, Any] | None,
) -> dict[str, int]:
    if not usage:
        return dict(current)
    prompt = int(usage.get("prompt_tokens", 0))
    completion = int(usage.get("completion_tokens", 0))
    total = int(usage.get("total_tokens", prompt + completion))
    return {
        "prompt_tokens": current["prompt_tokens"] + prompt,
        "completion_tokens": current["completion_tokens"] + completion,
        "total_tokens": current["total_tokens"] + total,
    }


def _answer_matches(task: EvalTask, final_answer: str) -> bool:
    """Return whether a final answer satisfies the public reference facts."""

    expected = list(task.acceptable_answers)
    if task.reference_answer:
        expected.insert(0, task.reference_answer)
    if not expected:
        return bool(final_answer)
    normalized = _normalize_answer(final_answer)
    if not normalized:
        return False
    return any(_normalize_answer(item) in normalized for item in expected if item)


def _normalize_answer(value: str) -> str:
    """Normalize simple answers for deterministic public-fact matching."""

    text = value.casefold().strip()
    text = "".join(text.split())
    return text.replace("“", '"').replace("”", '"')


def calculate_cost(usage: dict[str, int], pricing: Pricing) -> float:
    """Return conservative list-price cost from provider-reported tokens."""

    prompt = int(usage.get("prompt_tokens", 0))
    completion = int(usage.get("completion_tokens", 0))
    return (
        prompt * pricing.input_usd_per_million
        + completion * pricing.output_usd_per_million
    ) / 1_000_000
