"""Adapters for BFCL/ToolBench and a deterministic synthetic task-pool builder.

The frozen evaluation contract exposes exactly eight tools: web_search,
web_fetch, memory_search, current_time, evidence_submit, update_activity,
skills_list, and skill_view.  BFCL and ToolBench are large public task
collections whose native function schemas do not generally match those eight
tools.  This module therefore implements two things:

1. Best-effort adapters that map real BFCL v3 JSONL and ToolBench
   instruction/API records into the unified task JSON when their public
   function/API names can be mapped onto the frozen tools.
2. A deterministic synthetic task-pool builder that always produces
   executable tasks over the frozen tools and is used when public tasks
   cannot provide enough compatible coverage.
"""

from __future__ import annotations

import argparse
import json
import random
import re
from pathlib import Path
from typing import Any, Iterable, Mapping

FROZEN_TOOL_NAMES: tuple[str, ...] = (
    "web_search",
    "web_fetch",
    "memory_search",
    "current_time",
    "evidence_submit",
    "update_activity",
    "skills_list",
    "skill_view",
)

TASK_CATEGORIES: tuple[str, ...] = (
    "single_tool",
    "multi_tool",
    "sequential",
    "argument_constraint",
    "failure_retry",
    "multi_turn",
    "no_tool",
    "evidence_synthesis",
)

DEFAULT_COUNTS: dict[str, int] = {
    "single_tool": 250,
    "multi_tool": 250,
    "sequential": 250,
    "argument_constraint": 200,
    "failure_retry": 150,
    "multi_turn": 150,
    "no_tool": 100,
    "evidence_synthesis": 100,
}

DEFAULT_POOL_PATH: Path = Path("data/tasks/task_pool.json")

UNIFIED_KEYS = frozenset({"task_id", "source", "instruction", "available_tools", "expected_behavior"})
BEHAVIOR_KEYS = frozenset({"must_call", "must_not_call", "success_condition"})

_TOOL_INDEX = {name: i for i, name in enumerate(FROZEN_TOOL_NAMES)}


class TaskAdapterError(ValueError):
    """Raised when a source record cannot be converted to a valid task."""


# ---------------------------------------------------------------------------
# Real BFCL / ToolBench adapters
# ---------------------------------------------------------------------------


def normalize_tool_name(name: str) -> str:
    """Normalize a public function/API name for keyword matching."""

    value = re.sub(r"[^0-9a-zA-Z]+", "_", str(name).lower()).strip("_")
    value = re.sub(r"_+", "_", value)
    return value


def map_public_tool_name(name: str, description: str = "") -> str | None:
    """Map a public function/API name to one of the eight frozen tools.

    The matcher is intentionally conservative.  Real BFCL/ToolBench records
    with unrelated native functions return ``None`` so callers can skip them
    instead of producing a misleading task.
    """

    normalized = normalize_tool_name(name)
    text = f"{normalized} {str(description or '').lower()}"

    if any(token in normalized for token in ("web_search", "search_engine", "google_search", "bing_search")):
        return "web_search"
    if any(token in normalized for token in ("web_fetch", "fetch_url", "get_webpage", "read_url", "scrape_url", "browse_url")):
        return "web_fetch"
    if "memory_search" in normalized or "search_memory" in normalized:
        return "memory_search"
    if normalized in {"current_time", "get_current_time", "get_time", "system_time", "clock_time"}:
        return "current_time"
    if normalized in {"evidence_submit", "submit_evidence", "verify_evidence"}:
        return "evidence_submit"
    if normalized in {"update_activity", "post_activity", "append_activity"}:
        return "update_activity"
    if normalized in {"skills_list", "list_skills", "get_skills"}:
        return "skills_list"
    if normalized in {"skill_view", "view_skill", "load_skill", "get_skill"}:
        return "skill_view"

    # Less exact but still safe: a generic search API maps to web_search unless
    # it is clearly a memory or skills search.
    if "search" in normalized and not any(word in normalized for word in ("memory", "skill")):
        return "web_search"
    if normalized in {"get_time", "now", "datetime", "date_today"}:
        return "current_time"

    return None


def _bfcl_user_turns(record: Mapping[str, Any]) -> list[str]:
    """Extract user text from BFCL v3 ``question`` message lists."""

    raw_question = record.get("question")
    if not isinstance(raw_question, list):
        return []
    turns: list[str] = []
    for turn in raw_question:
        if not isinstance(turn, list):
            continue
        chunks: list[str] = []
        for message in turn:
            if not isinstance(message, dict):
                continue
            role = str(message.get("role", "")).lower()
            if role in {"user", "human"}:
                content = message.get("content")
                if isinstance(content, str) and content.strip():
                    chunks.append(content.strip())
        if chunks:
            turns.append(" ".join(chunks))
    return turns


def _bfcl_instruction(record: Mapping[str, Any]) -> str:
    turns = _bfcl_user_turns(record)
    if not turns:
        raise TaskAdapterError("BFCL record has no user question text")
    if len(turns) == 1:
        return turns[0]
    return "\n".join(f"[TURN {index}] {turn}" for index, turn in enumerate(turns, start=1))


def _bfcl_mapped_tools(record: Mapping[str, Any]) -> list[str]:
    """Return mapped frozen tools in call order when the record is compatible."""

    path = record.get("path")
    if isinstance(path, list):
        ordered: list[str] = []
        for item in path:
            mapped = map_public_tool_name(str(item))
            if mapped and mapped not in ordered:
                ordered.append(mapped)
        if ordered:
            return ordered

    functions = record.get("function")
    if not isinstance(functions, list):
        return []
    ordered = []
    for function in functions:
        if not isinstance(function, dict):
            continue
        name = str(function.get("name", ""))
        mapped = map_public_tool_name(name, str(function.get("description", "")))
        if mapped and mapped not in ordered:
            ordered.append(mapped)
    return ordered


def adapt_bfcl_record(record: Mapping[str, Any], *, fallback_index: int | None = None) -> dict[str, Any] | None:
    """Convert one BFCL v3 record into the unified task JSON.

    Records whose native functions cannot be mapped to the frozen tools are
    skipped (``None``).  This avoids silently inventing tool semantics.
    """

    try:
        instruction = _bfcl_instruction(record)
    except TaskAdapterError:
        return None

    must_call = _bfcl_mapped_tools(record)
    if not must_call:
        return None

    source_id = str(record.get("id") or fallback_index or "")
    task_id = f"bfcl_{source_id}" if source_id else f"bfcl_task_{fallback_index or 0}"
    return _make_task(
        task_id=task_id,
        source="bfcl",
        instruction=instruction,
        available_tools=list(must_call),
        must_call=list(must_call),
        must_not_call=[],
        success_condition=(
            "Call the mapped frozen tool(s) with arguments matching the "
            "instruction and return a complete answer."
        ),
    )


def adapt_bfcl_jsonl(path: str | Path) -> list[dict[str, Any]]:
    """Adapt BFCL v3 JSONL (or a JSON array) from disk."""

    raw = Path(path).read_text(encoding="utf-8").strip()
    records: list[Mapping[str, Any]]
    if raw.startswith("["):
        parsed = json.loads(raw)
        if not isinstance(parsed, list):
            raise TaskAdapterError(f"{path}: expected a JSON array")
        records = [item for item in parsed if isinstance(item, dict)]
    else:
        records = [json.loads(line) for line in raw.splitlines() if line.strip()]
    tasks: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        task = adapt_bfcl_record(record, fallback_index=index)
        if task is not None:
            tasks.append(task)
    return tasks

def _toolbench_record_dict(record: Any) -> dict[str, Any] | None:
    """Convert a pandas row or plain mapping to a dict."""

    if hasattr(record, "to_dict"):
        try:
            value = record.to_dict()
        except Exception:
            return None
        return value if isinstance(value, dict) else None
    if isinstance(record, Mapping):
        return dict(record)
    return None


def _parse_toolbench_api_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return []
        value = parsed
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def adapt_toolbench_record(record: Any, *, fallback_index: int | None = None) -> dict[str, Any] | None:
    """Convert one ToolBench instruction/API row into the unified task JSON."""

    data = _toolbench_record_dict(record)
    if data is None:
        return None
    query = str(data.get("query") or "").strip()
    if not query:
        return None

    apis = _parse_toolbench_api_list(data.get("api_list"))
    relevant_raw = data.get("relevant_apis")
    relevant_names: set[str] = set()
    if isinstance(relevant_raw, str):
        try:
            parsed_relevant = json.loads(relevant_raw)
        except json.JSONDecodeError:
            parsed_relevant = []
        for item in parsed_relevant:
            if isinstance(item, list):
                relevant_names.update(str(part).strip() for part in item)
            elif isinstance(item, str):
                relevant_names.add(item)
    elif isinstance(relevant_raw, list):
        for item in relevant_raw:
            if isinstance(item, list):
                relevant_names.update(str(part).strip() for part in item)
            elif isinstance(item, str):
                relevant_names.add(item)

    available: list[str] = []
    for api in apis:
        api_name = str(api.get("api_name") or api.get("name") or "")
        tool_name = str(api.get("tool_name") or api.get("category_name") or "")
        mapped = map_public_tool_name(api_name, str(api.get("api_description", "")))
        if mapped is None:
            mapped = map_public_tool_name(tool_name, str(api.get("api_description", "")))
        if mapped and mapped not in available:
            available.append(mapped)

    if not available:
        return None

    must_call: list[str] = []
    for api in apis:
        api_name = str(api.get("api_name") or api.get("name") or "")
        tool_name = str(api.get("tool_name") or api.get("category_name") or "")
        in_relevant = any(
            (api_name and api_name.lower() == relevant.lower())
            or (tool_name.lower() == relevant.lower())
            for relevant in relevant_names
        )
        mapped = map_public_tool_name(api_name, str(api.get("api_description", "")))
        if mapped is None:
            mapped = map_public_tool_name(tool_name, str(api.get("api_description", "")))
        if mapped and in_relevant and mapped not in must_call:
            must_call.append(mapped)
    if not must_call:
        must_call = list(available)

    query_id = str(data.get("query_id") or data.get("id") or fallback_index or "")
    task_id = f"toolbench_{query_id}" if query_id else f"toolbench_task_{fallback_index or 0}"
    return _make_task(
        task_id=task_id,
        source="toolbench",
        instruction=query,
        available_tools=available,
        must_call=must_call,
        must_not_call=[],
        success_condition=(
            "Use the mapped frozen tool(s) to satisfy the user request and "
            "return a grounded answer."
        ),
    )


def adapt_toolbench_parquet(path: str | Path) -> list[dict[str, Any]]:
    """Adapt ToolBench benchmark parquet files when ``pyarrow`` is available."""

    try:
        import pyarrow.parquet as pq  # type: ignore
    except ImportError as exc:
        raise TaskAdapterError("pyarrow is required for ToolBench parquet files") from exc

    table = pq.read_table(str(path))
    records = table.to_pylist()
    tasks: list[dict[str, Any]] = []
    for index, record in enumerate(records):
        task = adapt_toolbench_record(record, fallback_index=index)
        if task is not None:
            tasks.append(task)
    return tasks


# ---------------------------------------------------------------------------
# Unified task construction / normalization
# ---------------------------------------------------------------------------


def _stable_tool_order(tools: Iterable[str]) -> list[str]:
    unique = list(dict.fromkeys(str(tool) for tool in tools))
    return sorted(unique, key=lambda name: _TOOL_INDEX.get(name, 999))


def _make_task(
    *,
    task_id: str,
    source: str,
    instruction: str,
    available_tools: Iterable[str],
    must_call: Iterable[str],
    must_not_call: Iterable[str],
    success_condition: str,
) -> dict[str, Any]:
    """Construct a unified task while keeping required tools visible."""

    available = list(dict.fromkeys(str(tool) for tool in available_tools))
    required = list(dict.fromkeys(str(tool) for tool in must_call))
    forbidden = list(dict.fromkeys(str(tool) for tool in must_not_call))
    available = _stable_tool_order(list(dict.fromkeys(required + forbidden + available)))
    return {
        "task_id": str(task_id),
        "source": str(source),
        "instruction": str(instruction).strip(),
        "available_tools": available,
        "expected_behavior": {
            "must_call": required,
            "must_not_call": forbidden,
            "success_condition": str(success_condition).strip(),
        },
    }


def normalize_task(task: Mapping[str, Any]) -> dict[str, Any]:
    """Normalize and strictly validate one unified task dict."""

    if set(task.keys()) != UNIFIED_KEYS:
        missing = UNIFIED_KEYS - set(task.keys())
        extra = set(task.keys()) - UNIFIED_KEYS
        raise TaskAdapterError(f"unified task keys invalid; missing={sorted(missing)} extra={sorted(extra)}")
    behavior = task.get("expected_behavior")
    if not isinstance(behavior, Mapping) or set(behavior.keys()) != BEHAVIOR_KEYS:
        raise TaskAdapterError("expected_behavior must contain exactly must_call, must_not_call, success_condition")
    source = str(task.get("source"))
    if source not in {"bfcl", "toolbench"}:
        raise TaskAdapterError("source must be 'bfcl' or 'toolbench'")
    available = list(task.get("available_tools") or [])
    must_call = list(behavior.get("must_call") or [])
    must_not_call = list(behavior.get("must_not_call") or [])
    if not all(isinstance(tool, str) for tool in available):
        raise TaskAdapterError("available_tools must be a list of strings")
    if not all(tool in FROZEN_TOOL_NAMES for tool in available):
        raise TaskAdapterError("available_tools contains a tool outside the frozen schema")
    if len(available) != len(set(available)):
        raise TaskAdapterError("available_tools contains duplicates")
    if not all(isinstance(tool, str) and tool in available for tool in must_call):
        raise TaskAdapterError("must_call contains an unavailable or non-string tool")
    if not all(isinstance(tool, str) and tool in available for tool in must_not_call):
        raise TaskAdapterError("must_not_call contains an unavailable or non-string tool")
    return _make_task(
        task_id=str(task.get("task_id")),
        source=source,
        instruction=str(task.get("instruction")),
        available_tools=available,
        must_call=must_call,
        must_not_call=must_not_call,
        success_condition=str(behavior.get("success_condition")),
    )


# ---------------------------------------------------------------------------
# Synthetic task-pool builder
# ---------------------------------------------------------------------------

_TOPICS = (
    "renewable energy storage",
    "recent advances in RNA vaccines",
    "EU AI Act enforcement",
    "solar cell efficiency records",
    "quantum error correction",
    "open-source agent runtimes",
    "browser automation safety",
    "GPU memory optimization",
    "diffusion model inference",
    "personal knowledge management",
)

_QUERIES = (
    "official documentation",
    "recent peer-reviewed article",
    "industry benchmark",
    "latest stable release",
    "regulatory guidance",
    "reproducible evaluation",
    "security advisory",
)

_URLS = (
    "https://example.com/research/latest",
    "https://arxiv.org/abs/2401.00001",
    "https://news.ycombinator.com/item?id=1",
    "https://en.wikipedia.org/wiki/Function_calling",
    "https://github.com/example/klara/releases",
)

_TIMEZONES = ("Asia/Shanghai", "America/New_York", "Europe/London", "Asia/Tokyo", "UTC", "Australia/Sydney")

_SKILL_NAMES = ("repository_work",)

_NO_TOOL_ITEMS = (
    "What is 17 multiplied by 23?",
    "Summarize this sentence in one clause: 'The model should prefer the smallest sufficient tool set.'",
    "Rewrite the following sentence in a more formal register: 'Check the page and tell me what it says.'",
    "List three risks of using unverified web sources.",
    "What is the result of (8 + 12) / 4?",
    "Explain in two sentences what a function-calling benchmark measures.",
    "Convert 150 minutes into hours and minutes.",
    "Name three properties of a good citation.",
)

def _pick_distractors(rng: random.Random, exclude: Iterable[str], count: int) -> list[str]:
    excluded = set(exclude)
    candidates = [tool for tool in FROZEN_TOOL_NAMES if tool not in excluded]
    return rng.sample(candidates, min(count, len(candidates)))


def _source_for(index: int) -> str:
    return "bfcl" if index % 2 == 0 else "toolbench"


def _task_id(source: str, category: str, index: int) -> str:
    return f"{source}_{category}_{index:04d}"


def _fill(template: str, rng: random.Random) -> str:
    context = {
        "topic": rng.choice(_TOPICS),
        "query": rng.choice(_QUERIES),
        "url": rng.choice(_URLS),
        "timezone": rng.choice(_TIMEZONES),
        "skill": rng.choice(_SKILL_NAMES),
        "count": str(rng.randint(2, 8)),
        "year": str(rng.choice((2023, 2024, 2025, 2026))),
    }
    return template.format(**context)


def _gen_single_tool(rng: random.Random, count: int) -> list[dict[str, Any]]:
    templates: dict[str, tuple[str, ...]] = {
        "web_search": (
            "Find the latest official information about {topic}.",
            "Search the web for a {query} covering {topic}; keep the query specific.",
            "Use web search to find up to {count} candidate sources for {topic}.",
        ),
        "web_fetch": (
            "Fetch {url} and report its title plus one specific factual claim.",
            "Open {url} and extract only the main point relevant to {topic}.",
            "Fetch {url} with a reasonable character limit and quote the first relevant sentence.",
        ),
        "memory_search": (
            "Search my saved memory for any preference or durable fact about {topic}.",
            "Look in memory for notes I previously saved about {topic}.",
            "Use memory_search with mode 'hybrid' and a small limit for my note on {topic}.",
        ),
        "current_time": (
            "Return the current date, time, weekday, and UTC offset in {timezone}.",
            "What is the exact current time in {timezone}?",
            "Give me today's date and local time in {timezone}.",
        ),
        "evidence_submit": (
            "Submit the proposed answer '{topic}' as final_text with one claim and abstain=false.",
            "Call evidence_submit with one supported claim about {topic}; use empty links/citations and abstain=false.",
        ),
        "update_activity": (
            "Before any other work, append one concise public thinking update about {topic}.",
            "Use update_activity to post the next progress step for the current task.",
        ),
        "skills_list": (
            "List the procedural skills available in the current catalog.",
            "Call skills_list and report the available skill names and versions.",
        ),
        "skill_view": (
            "Load the skill named '{skill}' and report its version, scope, and loaded status.",
            "Use skill_view for '{skill}' and summarize what the body is for.",
        ),
    }
    tools = list(FROZEN_TOOL_NAMES)
    tasks: list[dict[str, Any]] = []
    for index in range(count):
        tool = tools[index % len(tools)]
        instruction = _fill(rng.choice(templates[tool]), rng)
        distractors = _pick_distractors(rng, exclude={tool}, count=2)
        source = _source_for(index)
        tasks.append(
            _make_task(
                task_id=_task_id(source, "single_tool", index),
                source=source,
                instruction=instruction,
                available_tools=[tool, *distractors],
                must_call=[tool],
                must_not_call=distractors,
                success_condition=f"Call exactly '{tool}' once and avoid the distractor tools.",
            )
        )
    return tasks


def _gen_multi_tool(rng: random.Random, count: int) -> list[dict[str, Any]]:
    pairs = (
        (("web_search", "current_time"), "Search the web for {topic} and independently report the current time in {timezone}."),
        (("memory_search", "skills_list"), "Search my saved memory for notes about {topic} and list the current skills."),
        (("web_search", "web_fetch"), "Search the web for {topic}, then fetch {url}; both steps are required but independent."),
        (("evidence_submit", "update_activity"), "Post a short activity update about {topic}, then submit the final evidence note."),
        (("skill_view", "skills_list"), "List available skills and load '{skill}' as a separate observation."),
        (("web_search", "memory_search"), "Find public information about {topic} on the web and also search private memory for related notes."),
    )
    tasks: list[dict[str, Any]] = []
    for index in range(count):
        pair, template = pairs[index % len(pairs)]
        instruction = _fill(template, rng)
        source = _source_for(index)
        tasks.append(
            _make_task(
                task_id=_task_id(source, "multi_tool", index),
                source=source,
                instruction=instruction,
                available_tools=list(pair),
                must_call=list(pair),
                must_not_call=[],
                success_condition=f"Call every required tool ({', '.join(pair)}) at least once; order is not scored.",
            )
        )
    return tasks


def _gen_sequential(rng: random.Random, count: int) -> list[dict[str, Any]]:
    chains = (
        (
            ("web_search", "web_fetch", "evidence_submit"),
            "First search the web for {topic}. Then fetch the top candidate URL. Finally submit one supported claim with evidence_submit.",
        ),
        (
            ("skills_list", "skill_view", "update_activity"),
            "First call skills_list. Then load '{skill}' with skill_view. Finally call update_activity to report what you loaded.",
        ),
        (
            ("memory_search", "current_time", "update_activity"),
            "First search memory for {topic}. Then get the current time in {timezone}. Finally post an update_activity summary.",
        ),
        (
            ("current_time", "web_search", "web_fetch"),
            "First get the current time in {timezone}. Then search for recent {topic} news. Then fetch the most authoritative result.",
        ),
    )
    tasks: list[dict[str, Any]] = []
    for index in range(count):
        chain, template = chains[index % len(chains)]
        instruction = _fill(template, rng)
        source = _source_for(index)
        tasks.append(
            _make_task(
                task_id=_task_id(source, "sequential", index),
                source=source,
                instruction=instruction,
                available_tools=list(chain),
                must_call=list(chain),
                must_not_call=[],
                success_condition=f"Call tools in the order {list(chain)} and use the result of each step.",
            )
        )
    return tasks


def _gen_argument_constraint(rng: random.Random, count: int) -> list[dict[str, Any]]:
    templates = (
        ("web_search", "Search for {topic} using freshness 'month', country 'US', language 'en', and count {count}.", "search arguments must include freshness, country, language, and count"),
        ("web_search", "Search for {topic} but restrict results to allowed_domains ['example.com'] and block no domains.", "search must pass allowed_domains=['example.com']"),
        ("web_search", "Search for {topic} with date_after '{year}-01-01' and date_before '{year}-12-31'.", "search must include date_after and date_before constraints"),
        ("web_fetch", "Fetch {url} with max_chars 600 and extract_mode 'relevant_snippets'.", "fetch must set max_chars=600 and extract_mode='relevant_snippets'"),
        ("web_fetch", "Fetch {url} with query_terms ['{topic}', 'official'] and max_chars 1000.", "fetch must pass two query_terms and max_chars=1000"),
        ("memory_search", "Search memory for {topic} using mode 'lexical' and limit {count}.", "memory_search must use mode='lexical' and the requested limit"),
        ("memory_search", "Search memory for {topic} using mode 'hybrid' and limit 3.", "memory_search must use mode='hybrid' and limit=3"),
        ("current_time", "Return the current time in timezone '{timezone}'.", "current_time must receive timezone='{timezone}'"),
        ("skill_view", "Load skill '{skill}' and request the reference 'checklist.md' when available.", "skill_view must pass name and reference='checklist.md'"),
        ("evidence_submit", "Submit a final answer with one claim_id 'c1', one link for c1, one citation for c1, and abstain=false.", "evidence_submit must contain one claim, link, and citation with abstain=false"),
        ("update_activity", "Call update_activity with exactly one text field: 'Prepared the constrained tool call for {topic}.'", "update_activity must contain a non-empty text field"),
    )
    tasks: list[dict[str, Any]] = []
    for index in range(count):
        tool, template, condition_template = templates[index % len(templates)]
        instruction = _fill(template, rng)
        condition = condition_template.format(topic=instruction[:80], timezone=rng.choice(_TIMEZONES), count="5")
        source = _source_for(index)
        tasks.append(
            _make_task(
                task_id=_task_id(source, "argument_constraint", index),
                source=source,
                instruction=instruction,
                available_tools=[tool],
                must_call=[tool],
                must_not_call=[],
                success_condition=f"Only call '{tool}' with correct constrained arguments: {condition}.",
            )
        )
    return tasks

def _gen_failure_retry(rng: random.Random, count: int) -> list[dict[str, Any]]:
    templates = (
        ("web_search", "Search for an extremely narrow phrase about {topic}. If the result count is zero, simplify the query and retry before answering."),
        ("web_fetch", "Try fetching a deliberately fragile URL derived from {url}. If the fetch fails, search the web for the page title and retry a corrected URL."),
        ("current_time", "Call current_time with timezone 'Not/A_Real_Zone'. After it fails, retry with '{timezone}'."),
        ("skill_view", "Call skill_view for a missing skill named 'does_not_exist'. After it fails, call skills_list and then retry skill_view for an available skill."),
        ("memory_search", "Search memory with an empty query. After the expected failure, retry with a meaningful query about {topic}."),
    )
    tasks: list[dict[str, Any]] = []
    for index in range(count):
        _, template = templates[index % len(templates)]
        instruction = _fill(template, rng)
        source = _source_for(index)
        if template.startswith("web_fetch"):
            tools = ["web_fetch", "web_search"]
            must_call = ["web_fetch", "web_search"]
            condition = "A failed web_fetch must be followed by a corrected web_search or fetch attempt."
        elif template.startswith("skill_view"):
            tools = ["skill_view", "skills_list"]
            must_call = ["skill_view", "skills_list"]
            condition = "The first skill_view may fail; the agent must recover by listing skills and retrying."
        else:
            if template.startswith("web_search"):
                tools = ["web_search"]
            elif template.startswith("memory_search"):
                tools = ["memory_search"]
            else:
                tools = ["current_time"]
            must_call = list(tools)
            condition = "The first call may fail; the agent must inspect the error and retry with corrected arguments."
        tasks.append(
            _make_task(
                task_id=_task_id(source, "failure_retry", index),
                source=source,
                instruction=instruction,
                available_tools=tools,
                must_call=must_call,
                must_not_call=[],
                success_condition=condition,
            )
        )
    return tasks


def _gen_multi_turn(rng: random.Random, count: int) -> list[dict[str, Any]]:
    templates = (
        (
            ("current_time", "web_search", "web_fetch", "evidence_submit"),
            "[TURN 1] What is the current time in {timezone}?\n[TURN 2] Search the web for recent news about {topic}.\n[TURN 3] Fetch the most authoritative result from turn 2.\n[TURN 4] Submit one supported claim from the fetched source.",
        ),
        (
            ("memory_search", "current_time", "update_activity"),
            "[TURN 1] Do I have any saved notes about {topic}?\n[TURN 2] What is the current time in {timezone}?\n[TURN 3] Post a public activity update that combines both answers.",
        ),
        (
            ("skills_list", "skill_view", "update_activity"),
            "[TURN 1] List the available skills.\n[TURN 2] Load '{skill}' in detail.\n[TURN 3] Post an activity update describing what the skill covers.",
        ),
        (
            ("web_search", "web_fetch", "evidence_submit"),
            "[TURN 1] Search for the official {query} for {topic}.\n[TURN 2] Fetch the best candidate URL.\n[TURN 3] Submit a short evidence note with one supported claim.",
        ),
    )
    tasks: list[dict[str, Any]] = []
    for index in range(count):
        chain, template = templates[index % len(templates)]
        instruction = _fill(template, rng)
        source = _source_for(index)
        tasks.append(
            _make_task(
                task_id=_task_id(source, "multi_turn", index),
                source=source,
                instruction=instruction,
                available_tools=list(chain),
                must_call=list(chain),
                must_not_call=[],
                success_condition=f"Satisfy every turn while preserving context across turns using {list(chain)}.",
            )
        )
    return tasks


def _gen_no_tool(rng: random.Random, count: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for index in range(count):
        instruction = _NO_TOOL_ITEMS[index % len(_NO_TOOL_ITEMS)]
        source = _source_for(index)
        if index % 2 == 0:
            available: list[str] = []
            forbidden: list[str] = []
        else:
            available = _pick_distractors(rng, exclude=set(), count=3)
            forbidden = list(available)
        tasks.append(
            _make_task(
                task_id=_task_id(source, "no_tool", index),
                source=source,
                instruction=instruction,
                available_tools=available,
                must_call=[],
                must_not_call=forbidden,
                success_condition="Answer directly without calling any tool.",
            )
        )
    return tasks


def _gen_evidence_synthesis(rng: random.Random, count: int) -> list[dict[str, Any]]:
    tasks: list[dict[str, Any]] = []
    for index in range(count):
        instruction = (
            f"Research {rng.choice(_TOPICS)}. Perform at least two different web searches, "
            "fetch at least two independent sources from different domains, and then call "
            "evidence_submit with final_text, two claims, two links with source_id values, "
            "two citations, and abstain=false. Cite only fetched source text."
        )
        source = _source_for(index)
        tools = ["web_search", "web_fetch", "evidence_submit"]
        tasks.append(
            _make_task(
                task_id=_task_id(source, "evidence_synthesis", index),
                source=source,
                instruction=instruction,
                available_tools=tools,
                must_call=tools,
                must_not_call=[],
                success_condition=(
                    "Search and fetch multiple independent sources, then submit evidence "
                    "with claims, links, citations, and abstain=false."
                ),
            )
        )
    return tasks


_GENERATORS = {
    "single_tool": _gen_single_tool,
    "multi_tool": _gen_multi_tool,
    "sequential": _gen_sequential,
    "argument_constraint": _gen_argument_constraint,
    "failure_retry": _gen_failure_retry,
    "multi_turn": _gen_multi_turn,
    "no_tool": _gen_no_tool,
    "evidence_synthesis": _gen_evidence_synthesis,
}


def build_synthetic_task_pool(
    counts: Mapping[str, int] | None = None,
    *,
    seed: int = 42,
) -> list[dict[str, Any]]:
    """Build a deterministic synthetic task pool over the frozen tools."""

    effective_counts = dict(DEFAULT_COUNTS)
    if counts:
        unknown = set(counts) - set(TASK_CATEGORIES)
        if unknown:
            raise TaskAdapterError(f"unknown task categories: {sorted(unknown)}")
        effective_counts.update({key: int(value) for key, value in counts.items() if int(value) > 0})

    rng = random.Random(seed)
    tasks: list[dict[str, Any]] = []
    for category in TASK_CATEGORIES:
        count = int(effective_counts.get(category, 0))
        if count <= 0:
            continue
        generator = _GENERATORS[category]
        generated = generator(rng, count)
        tasks.extend(normalize_task(task) for task in generated)
    return tasks


def write_task_pool(
    path: str | Path = DEFAULT_POOL_PATH,
    counts: Mapping[str, int] | None = None,
    *,
    seed: int = 42,
) -> Path:
    """Build the synthetic pool and write it as UTF-8 JSON."""

    target = Path(path)
    tasks = build_synthetic_task_pool(counts=counts, seed=seed)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return target


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build-pool", action="store_true", help="write data/tasks/task_pool.json")
    parser.add_argument("--path", type=Path, default=DEFAULT_POOL_PATH)
    parser.add_argument("--seed", type=int, default=42)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.build_pool:
        target = write_task_pool(args.path, seed=args.seed)
        print(f"wrote {target.resolve()}")
        return 0
    print("Use --build-pool to write the synthetic task pool.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
