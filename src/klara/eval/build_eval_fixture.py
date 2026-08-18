"""Build frozen-tool eval fixtures from ``data/tasks/hidden_dev_pool.json``.

The source pool contains 200 dev and 800 hidden tasks with task-level
``expected_behavior`` labels but no concrete tool arguments or frozen tool
observations. This builder materializes both missing pieces deterministically:

* ``tasks.user_turn`` comes from ``instruction``.
* ``tasks.must_call_tools`` / ``tasks.may_call_tools`` are mapped from
  ``expected_behavior.must_call`` and ``expected_behavior.must_not_call``.
* ``tasks.expected_tool_calls`` are derived from each task's instruction with
  stable, no-network argument stubs.
* Each generated call receives a deterministic frozen ``entries`` result, so
  every eval run against the same fixture observes identical tool outputs.

Run from the repository root::

    python src/klara/eval/build_eval_fixture.py
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
import sys
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
SRC_ROOT = REPOSITORY_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

FIXTURE_SCHEMA_VERSION = "klara.frozen-tool-fixture.v1"
DEFAULT_SYSTEM_PROMPT = (
    "You are Klara under a frozen-tool evaluation. Use only the supplied tools. "
    "When a task asks you to call a tool, call exactly that tool with the exact "
    "required arguments, then answer using only the returned observation. Do not "
    "invent tool results and do not call extra tools."
)

POOL_PATH = REPOSITORY_ROOT / "data" / "tasks" / "hidden_dev_pool.json"
OUTPUT_DIR = REPOSITORY_ROOT / "data" / "eval" / "fixtures"

# These are the exact eight tool names frozen by ``docs/resume/klara-eval-contract.md``.
FROZEN_TOOL_NAMES = (
    "web_search",
    "web_fetch",
    "memory_search",
    "current_time",
    "evidence_submit",
    "update_activity",
    "skills_list",
    "skill_view",
)

# Public model-visible schemas. They intentionally mirror the runtime tool
# schemas so real model calls that use the common optional fields stay valid.
TOOL_SPECS: tuple[dict[str, Any], ...] = (
    {
        "name": "web_search",
        "description": "Search the public web and return a small result list.",
        "input_schema": {
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
    },
    {
        "name": "web_fetch",
        "description": "Fetch one public HTTP(S) page and return readable text.",
        "input_schema": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "candidate_id": {"type": "string"},
                "source_id": {"type": "string"},
                "max_chars": {"type": "integer", "minimum": 200, "maximum": 12000},
                "query_terms": {"type": "array", "items": {"type": "string"}},
                "extract_mode": {"type": "string", "enum": ["plain", "relevant_snippets", "summary_snippets"]},
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    {
        "name": "memory_search",
        "description": "Search the user's local memory for a fact.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "mode": {
                    "type": "string",
                    "enum": ["hybrid", "lexical", "vector", "recent", "full_context", "semantic_recency", "mem0_compatible"],
                },
                "at_time": {"type": "string", "format": "date-time"},
                "limit": {"type": "integer", "minimum": 1, "maximum": 20},
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
    {
        "name": "current_time",
        "description": "Return the current local time as an ISO-8601 timestamp.",
        "input_schema": {
            "type": "object",
            "properties": {
                "timezone": {"type": "string"},
            },
            "required": [],
            "additionalProperties": False,
        },
    },
    {
        "name": "evidence_submit",
        "description": "Submit a proposed answer, claims, links, citations, or abstention for verification.",
        "input_schema": {
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
                            "judgment": {"type": "string", "enum": ["supported", "contradicted", "insufficient"]},
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
    },
    {
        "name": "update_activity",
        "description": "Append one public thinking update for the current step.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {"type": "string"},
            },
            "required": ["text"],
            "additionalProperties": False,
        },
    },
    {
        "name": "skills_list",
        "description": "List the names of all available Klara skills.",
        "input_schema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "skill_view",
        "description": "Return the public detail of one skill.",
        "input_schema": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "reference": {"type": "string"},
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
)


def _slug(value: str, length: int = 10) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()[:length]


def _clean_topic(value: str) -> str:
    value = re.sub(r"\s+", " ", value).strip()
    value = value.strip(" .;,'\"")
    value = re.sub(r"^my note on\s+", "", value, flags=re.IGNORECASE)
    value = re.sub(r"^note on\s+", "", value, flags=re.IGNORECASE)
    return value.strip(" .;,'\"")


def _query_after_for(instruction: str) -> str:
    """Return a compact query/topic from the natural-language instruction."""
    lowered = instruction.casefold()
    matches = list(re.finditer(r"\bfor\s+", lowered))
    if matches:
        tail = instruction[matches[-1].end() :]
        return _clean_topic(tail)
    return ""


def _topic_after_about(instruction: str) -> str:
    lowered = instruction.casefold()
    matches = list(re.finditer(r"\babout\s+", lowered))
    if matches:
        tail = instruction[matches[-1].end() :]
        tail = re.split(r"\s+(?:and|with|use|abstain)\b", tail, maxsplit=1, flags=re.IGNORECASE)[0]
        return _clean_topic(tail)
    return _clean_topic(instruction)


def _argument_stub(tool_name: str, instruction: str, task_id: str) -> dict[str, Any]:
    text = re.sub(r"\s+", " ", instruction).strip()
    if tool_name == "current_time":
        match = re.search(r"\b(?:in|for|timezone)\s+([A-Za-z_]+/[A-Za-z_]+)", text)
        if match:
            return {"timezone": match.group(1)}
        return {}

    if tool_name == "skills_list":
        return {}

    if tool_name == "skill_view":
        match = re.search(r"skill_view\s+for\s+['\"]([^'\"]+)['\"]", text, flags=re.IGNORECASE)
        if not match:
            match = re.search(r"for\s+['\"]([^'\"]+)['\"]", text)
        if match:
            return {"name": match.group(1)}
        return {"name": "repo_ops"}

    if tool_name == "web_fetch":
        match = re.search(r"https?://[^\s,;'\"]+", text)
        if match:
            return {"url": match.group(0).rstrip(".,;'\")]")}
        return {"url": f"https://example.com/frozen-{_slug(task_id)}"}

    if tool_name == "web_search":
        query = _query_after_for(text)
        if not query:
            query = re.sub(
                r"^(?:use\s+)?web_search(?:\s+to)?\s*",
                "",
                text,
                flags=re.IGNORECASE,
            )
            query = _clean_topic(query)
        if not query:
            query = _clean_topic(text) or f"frozen task {task_id}"
        return {"query": query}

    if tool_name == "memory_search":
        query = _query_after_for(text)
        if not query:
            query = _clean_topic(text)
        if not query:
            query = f"frozen task {task_id}"
        args: dict[str, Any] = {"query": query}
        mode = re.search(r"\bmode\s+['\"]([^'\"]+)['\"]", text, flags=re.IGNORECASE)
        if mode:
            args["mode"] = mode.group(1)
        limit = re.search(r"\blimit\s+(\d+)", text, flags=re.IGNORECASE)
        if limit:
            args["limit"] = int(limit.group(1))
        elif re.search(r"\bsmall\s+limit\b", text, flags=re.IGNORECASE):
            args["limit"] = 3
        return args

    if tool_name == "update_activity":
        topic = _topic_after_about(text) or _query_after_for(text) or _clean_topic(text)
        return {"text": topic}

    if tool_name == "evidence_submit":
        topic = _topic_after_about(text) or _query_after_for(text) or _clean_topic(text)
        claim_id = f"claim-{_slug(task_id, 8)}"
        return {
            "final_text": topic,
            "claims": [
                {
                    "claim_id": claim_id,
                    "text": f"{topic} is supported by the frozen fixture.",
                    "required": True,
                }
            ],
            "links": [],
            "citations": [],
            "abstain": False,
        }

    raise ValueError(f"unsupported frozen tool: {tool_name}")


def _frozen_result(tool_name: str, arguments: dict[str, Any], task_id: str) -> dict[str, Any]:
    """Return one deterministic, no-network tool observation."""
    key = _slug(f"{tool_name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}", 10)
    if tool_name == "web_search":
        query = arguments.get("query", "frozen query")
        content = {
            "results": [
                {
                    "title": f"Frozen result {index} for {query}",
                    "url": f"https://example.com/{key}/{index}",
                    "snippet": f"Deterministic frozen web result for {query}.",
                }
                for index in (1, 2)
            ]
        }
    elif tool_name == "web_fetch":
        url = arguments.get("url", "https://example.com/frozen")
        content = {
            "final_url": url,
            "status": 200,
            "content_type": "text/html",
            "title": f"Frozen page {key}",
            "text": f"Deterministic frozen fetched text for {url}.",
            "truncated": False,
        }
    elif tool_name == "memory_search":
        query = arguments.get("query", "frozen query")
        content = {
            "results": [
                {
                    "fact": query,
                    "value": f"frozen memory value for {query}",
                    "score": 1.0,
                }
            ]
        }
    elif tool_name == "current_time":
        timezone = arguments.get("timezone", "UTC")
        content = {
            "timezone": timezone,
            "datetime": "2026-08-17T12:00:00+00:00",
            "weekday": "Monday",
            "utc_offset": "+00:00",
        }
    elif tool_name == "evidence_submit":
        content = {
            "accepted": True,
            "evidence_id": f"evidence-{key}",
            "claims": len(arguments.get("claims", [])),
            "links": len(arguments.get("links", [])),
            "citations": len(arguments.get("citations", [])),
            "abstain": arguments.get("abstain", False),
        }
    elif tool_name == "update_activity":
        content = {
            "updated": True,
            "text": arguments.get("text", "frozen activity update"),
        }
    elif tool_name == "skills_list":
        content = ["repo_ops", "web-research", "evidence-review"]
    elif tool_name == "skill_view":
        name = arguments.get("name", "unknown")
        content = {
            "name": name,
            "status": "active",
            "description": f"Deterministic frozen skill stub for {name}.",
            "body_content_exposed": False,
        }
    else:
        raise ValueError(f"unsupported frozen tool: {tool_name}")

    return {
        "content": json.dumps(content, ensure_ascii=False, sort_keys=True),
        "ok": True,
    }


def _task_from_pool_item(item: dict[str, Any]) -> dict[str, Any]:
    task_id = str(item["task_id"])
    instruction = str(item["instruction"])
    expected_behavior = item.get("expected_behavior") or {}
    must_call = [str(name) for name in expected_behavior.get("must_call", [])]
    must_not_call = [str(name) for name in expected_behavior.get("must_not_call", [])]
    available_tools = [str(name) for name in item.get("available_tools", [])]
    may_call = [name for name in available_tools if name not in set(must_not_call)]

    expected_tool_calls = [
        {"name": name, "arguments": _argument_stub(name, instruction, task_id)}
        for name in must_call
    ]

    return {
        "id": task_id,
        "user_turn": instruction,
        "reference_answer": None,
        "acceptable_answers": [],
        "expected_tool_calls": expected_tool_calls,
        "must_call_tools": must_call,
        "may_call_tools": may_call,
    }


def build_fixture(split: str, pool: list[dict[str, Any]]) -> dict[str, Any]:
    """Build one full fixture document for ``dev`` or ``hidden``."""
    if split not in {"dev", "hidden"}:
        raise ValueError(f"unsupported split: {split}")

    selected = [item for item in pool if item.get("split") == split]
    tasks = [_task_from_pool_item(item) for item in selected]

    entries: dict[str, dict[str, Any]] = {}
    for task in tasks:
        for expected in task["expected_tool_calls"]:
            name = expected["name"]
            arguments = expected["arguments"]
            key = f"{name}:{json.dumps(arguments, sort_keys=True, ensure_ascii=False)}"
            entries.setdefault(
                key,
                {
                    "tool_name": name,
                    "arguments": arguments,
                    "result": _frozen_result(name, arguments, task["id"]),
                },
            )

    name = f"{split}_frozen_tool_fixture"
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "name": name,
        "task_set": name,
        "system_prompt": DEFAULT_SYSTEM_PROMPT,
        "tools": TOOL_SPECS,
        "tasks": tasks,
        "entries": list(entries.values()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--pool",
        type=Path,
        default=POOL_PATH,
        help="Path to hidden_dev_pool.json",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=OUTPUT_DIR,
        help="Directory for generated fixture JSON files",
    )
    args = parser.parse_args(argv)

    if not args.pool.exists():
        raise FileNotFoundError(f"task pool not found: {args.pool}")

    pool = json.loads(args.pool.read_text(encoding="utf-8-sig"))
    if not isinstance(pool, list):
        raise ValueError("hidden_dev_pool.json must contain a JSON array")

    args.output_dir.mkdir(parents=True, exist_ok=True)
    outputs: list[Path] = []
    for split in ("dev", "hidden"):
        document = build_fixture(split, pool)
        destination = args.output_dir / f"{split}_fixture.json"
        destination.write_text(
            json.dumps(document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        outputs.append(destination)
        print(
            f"{split}: {len(document['tasks'])} tasks, "
            f"{len(document['entries'])} frozen entries -> {destination}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
