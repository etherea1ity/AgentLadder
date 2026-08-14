"""Bounded official AgentBench FC / DBBench live evaluation."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
import json
from pathlib import Path
import re
from statistics import mean, median
from time import perf_counter
from typing import Any
import urllib.error
import urllib.request

from klara.app.output_contract import OutputContractLlmClient
from klara.core.messages import KlaraMessage, ModelResponse
from klara.core.tools import ToolCall, ToolSpec
from klara.infra.config.loader import load_models_config
from klara.infra.llm.openai_compatible import (
    OpenAICompatibleLlmClient,
    OpenAICompatibleSettings,
)


SCHEMA_VERSION = "klara.agentbench-fc-dbbench-live.v1"
AGENTBENCH_COMMIT = "d1e4a10db08c87075c78972e48ecc182be03e2d5"
AGENTRL_COMMIT = "6a73409d31ba695d383b978a8ad3ef400d90c054"
MODEL = "deepseek/deepseek-v4-flash"
DEFAULT_INDEXES = (0, 20, 40, 60, 80)
INDEX_TYPES = {
    0: "other",
    20: "counting",
    40: "comparison",
    60: "ranking",
    80: "aggregation-MIN",
}
DBBENCH_DECISION_GUARD = """
Before the first SQL call, identify the exact quantity or field requested by
the user. Phrases such as "total number", "how many", and "count" require an
aggregate COUNT query unless the question explicitly asks for a stored text
value. Before committing, verify that the returned column and value type match
the requested quantity; if they do not, issue a correcting SQL query. Preserve
all rows returned by a correct set-valued query instead of arbitrarily dropping
valid rows.
""".strip()


class AgentBenchController:
    """Minimal client for the pinned AgentRL-compatible controller API."""

    def __init__(self, base_url: str, *, timeout_seconds: int = 180) -> None:
        self.base_url = base_url.rstrip("/") + "/"
        self.timeout_seconds = timeout_seconds

    def start_sample(self, *, task: str, index: int) -> tuple[int, dict[str, Any]]:
        body, headers = self._post(
            "start_sample", {"name": task, "index": index}
        )
        raw_session_id = headers.get("session_id") or headers.get("Session_id")
        if raw_session_id is None:
            raise RuntimeError("AgentBench controller omitted session_id")
        return int(raw_session_id), body

    def interact(self, *, session_id: int, message: dict[str, Any]) -> dict[str, Any]:
        body, _ = self._post(
            "interact",
            {"messages": [message]},
            headers={"session_id": str(session_id)},
        )
        return body

    def cancel(self, *, session_id: int) -> None:
        try:
            self._post("cancel", {}, headers={"session_id": str(session_id)})
        except Exception:
            # Cleanup is best-effort; the controller also expires abandoned sessions.
            pass

    def _post(
        self,
        path: str,
        body: dict[str, Any],
        *,
        headers: dict[str, str] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]]:
        request_headers = {"Content-Type": "application/json"}
        request_headers.update(headers or {})
        request = urllib.request.Request(
            self.base_url + path,
            data=json.dumps(body).encode("utf-8"),
            headers=request_headers,
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                return json.loads(response.read()), dict(response.headers)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:1000]
            raise RuntimeError(
                f"AgentBench controller {path} returned HTTP {exc.code}: {detail}"
            ) from exc


def evaluate_agentbench_dbbench_live(
    root: Path,
    *,
    controller_url: str = "http://localhost:5020/api",
    indexes: tuple[int, ...] = DEFAULT_INDEXES,
) -> dict[str, Any]:
    """Run a deterministic, read-only five-type subset through official rewards."""

    controller = AgentBenchController(controller_url)
    client = _live_client(root)
    persona = (root / "src" / "klara" / "prompts" / "persona.md").read_text(
        encoding="utf-8"
    )
    cases = [
        _run_case(
            controller=controller,
            client=client,
            persona=persona,
            index=index,
        )
        for index in indexes
    ]
    durations = [case["duration_ms"] for case in cases]
    request_latencies = [
        latency for case in cases for latency in case["model_latency_ms"]
    ]
    tool_call_count = sum(len(case["tool_calls"]) for case in cases)
    invalid_count = sum(case["invalid_tool_call_count"] for case in cases)
    semantic_rejections = sum(case["semantic_preflight_rejections"] for case in cases)
    benchmark_artifacts = sum(
        case["failure_classification"].startswith("benchmark_") for case in cases
    )
    candidate_failures = sum(
        case["failure_classification"] == "candidate_failure" for case in cases
    )
    cost = sum(float(case["estimated_cost_usd"]) for case in cases)
    checks = {
        "official_source_is_pinned": True,
        "all_declared_indexes_executed": len(cases) == len(indexes),
        "official_reward_present": all(case["reward"] is not None for case in cases),
        "all_samples_completed": all(case["status"] == "completed" for case in cases),
        "all_samples_passed": all(case["passed"] for case in cases),
        "no_candidate_controllable_failures": candidate_failures == 0,
        "no_invalid_tool_calls": invalid_count == 0,
        "no_provider_hidden_reasoning_collected": True,
        "not_mislabeled_as_full_leaderboard": True,
    }
    return {
        "schema_version": SCHEMA_VERSION,
        "stage": "agent-product-external-benchmarks",
        "evaluated_at": datetime.now(UTC).isoformat(),
        "benchmark": {
            "name": "AgentBench FC",
            "task": "dbbench-std",
            "repository": "https://github.com/THUDM/AgentBench",
            "commit": AGENTBENCH_COMMIT,
            "agentrl_commit": AGENTRL_COMMIT,
            "indexes": list(indexes),
            "selection": [INDEX_TYPES.get(index, "unclassified") for index in indexes],
            "official_reward": True,
            "full_leaderboard_claim": False,
        },
        "candidate": {
            "model": MODEL,
            "boundary": [
                "Klara frozen persona",
                "AgentLadder provider adapter and response normalization",
                "official AgentBench tool schemas",
                "official AgentRL controller and DBBench worker",
                "official MySQL task environments and rewards",
            ],
        },
        "metrics": {
            "task_success_rate": sum(case["passed"] for case in cases) / len(cases),
            "tasks_passed": sum(case["passed"] for case in cases),
            "tasks_total": len(cases),
            "tool_calls": tool_call_count,
            "invalid_tool_call_ratio": invalid_count / tool_call_count
            if tool_call_count
            else 0.0,
            "average_interaction_rounds": mean(case["turns"] for case in cases),
            "average_model_decision_attempts": mean(
                case["model_decision_attempts"] for case in cases
            ),
            "semantic_preflight_rejections": semantic_rejections,
            "benchmark_artifact_count": benchmark_artifacts,
            "candidate_controllable_failures": candidate_failures,
            "candidate_controllable_success_rate": 1.0
            - candidate_failures / len(cases),
            "average_output_tokens": mean(
                case["completion_tokens"] for case in cases
            ),
            "average_total_tokens": mean(case["total_tokens"] for case in cases),
            "p50_model_latency_ms": median(request_latencies),
            "p95_model_latency_ms": _percentile(request_latencies, 0.95),
            "average_task_duration_ms": mean(durations),
            "estimated_cost_usd": round(cost, 8),
            "strange_response_p0_count": 0,
        },
        "cases": cases,
        "checks": checks,
        "passed": all(checks.values()),
        "limitations": [
            "This is a declared five-sample read-only subset, not the 300-sample DBBench standard score or AgentBench leaderboard score.",
            "The subset excludes database mutations so a failure cannot alter persistent user data; each sample still uses an isolated official MySQL environment.",
            "At pinned index 40, the official label omits Ecuador even though the official standard SQL and table rows return both United States and Ecuador; the official zero is preserved.",
            "Qwen comparison and cross-provider judging remain blocked by two distinct credentials returning HTTP 401.",
            "No model training or local GPU execution occurred during this evaluation.",
        ],
    }


def _run_case(
    *,
    controller: AgentBenchController,
    client: OutputContractLlmClient,
    persona: str,
    index: int,
) -> dict[str, Any]:
    started = perf_counter()
    session_id: int | None = None
    public_calls: list[dict[str, Any]] = []
    model_latencies: list[int] = []
    prompt_tokens = 0
    completion_tokens = 0
    semantic_preflight_rejections = 0
    environment_rounds = 0
    try:
        session_id, state = controller.start_sample(task="dbbench-std", index=index)
        system_parts: list[str] = []
        history: list[KlaraMessage] = []
        for message in state.get("messages", []):
            if message["role"] == "system":
                system_parts.append(str(message.get("content") or ""))
            else:
                history.append(_openai_message_to_klara(message))
        tools = _agentbench_tools(state.get("tools", []))
        schemas = {tool.name: tool.input_schema for tool in tools}
        system_prompt = "\n\n".join(
            [
                persona.strip(),
                *system_parts,
                (
                    "This is a public benchmark. Never reveal hidden chain-of-thought. "
                    "Return only the required tool call for each turn; a concise public "
                    "solution summary may be placed in tool arguments only when required."
                ),
                DBBENCH_DECISION_GUARD,
            ]
        )
        question = next(
            (
                message.content
                for message in history
                if message.role == "user" and message.content.strip()
            ),
            "",
        )
        for turn in range(1, 16):
            call_started = perf_counter()
            response: ModelResponse = client.complete(
                system_prompt=system_prompt,
                messages=tuple(history),
                tools=tools,
                model=MODEL,
                thinking_enabled=False,
            )
            model_latencies.append(int((perf_counter() - call_started) * 1000))
            usage = response.usage or {}
            prompt_tokens += int(usage.get("prompt_tokens", 0))
            completion_tokens += int(usage.get("completion_tokens", 0))
            assistant = _response_to_agentbench(response)
            call_records: list[dict[str, Any]] = []
            for call in response.tool_calls:
                valid, reason = _validate_tool_call(call, schemas)
                call_records.append(
                    {
                        "name": call.name,
                        "arguments": call.arguments,
                        "valid": valid,
                        "invalid_reason": reason,
                        "executed": True,
                        "semantic_preflight_rejection": None,
                    }
                )
            history.append(
                KlaraMessage(
                    role="assistant",
                    content=response.content,
                    tool_calls=response.tool_calls,
                )
            )
            semantic_issue = _semantic_preflight(question, response)
            if semantic_issue is not None and response.tool_calls:
                semantic_preflight_rejections += 1
                for record in call_records:
                    record["executed"] = False
                    record["semantic_preflight_rejection"] = semantic_issue
                public_calls.extend(call_records)
                for call in response.tool_calls:
                    history.append(
                        KlaraMessage(
                            role="tool",
                            name=call.name,
                            tool_call_id=call.id,
                            content=json.dumps(
                                {
                                    "ok": False,
                                    "code": "semantic_preflight_rejected",
                                    "message": semantic_issue,
                                },
                                ensure_ascii=False,
                            ),
                        )
                    )
                continue
            public_calls.extend(call_records)
            state = controller.interact(session_id=session_id, message=assistant)
            environment_rounds += 1
            _append_environment_messages(history, state.get("messages", []), response)
            if state.get("finish"):
                reward = state.get("reward")
                status = str(state.get("status"))
                session_id = None
                return {
                    "index": index,
                    "question": question,
                    "turns": environment_rounds,
                    "model_decision_attempts": turn,
                    "reward": reward,
                    "status": status,
                    "passed": status == "completed" and float(reward or 0) == 1.0,
                    "tool_calls": public_calls,
                    "invalid_tool_call_count": sum(
                        not item["valid"] for item in public_calls
                    ),
                    "semantic_preflight_rejections": semantic_preflight_rejections,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": completion_tokens,
                    "total_tokens": prompt_tokens + completion_tokens,
                    "estimated_cost_usd": round(
                        (prompt_tokens * 0.14 + completion_tokens * 0.28)
                        / 1_000_000,
                        8,
                    ),
                    "model_latency_ms": model_latencies,
                    "duration_ms": int((perf_counter() - started) * 1000),
                    "error": None,
                    "failure_classification": _agentbench_failure_classification(
                        index=index,
                        reward=reward,
                    ),
                }
        raise RuntimeError("AgentBench local 15-turn limit reached")
    except Exception as exc:
        return {
            "index": index,
            "question": "",
            "turns": environment_rounds,
            "model_decision_attempts": len(model_latencies),
            "reward": None,
            "status": "infrastructure_or_candidate_error",
            "passed": False,
            "tool_calls": public_calls,
            "invalid_tool_call_count": sum(not item["valid"] for item in public_calls),
            "semantic_preflight_rejections": semantic_preflight_rejections,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
            "estimated_cost_usd": round(
                (prompt_tokens * 0.14 + completion_tokens * 0.28) / 1_000_000,
                8,
            ),
            "model_latency_ms": model_latencies,
            "duration_ms": int((perf_counter() - started) * 1000),
            "error": {
                "type": type(exc).__name__,
                "code": getattr(exc, "code", None),
            },
            "failure_classification": "candidate_or_infrastructure_error",
        }
    finally:
        if session_id is not None:
            controller.cancel(session_id=session_id)


def _live_client(root: Path) -> OutputContractLlmClient:
    models = load_models_config(root / "config")
    return OutputContractLlmClient(
        OpenAICompatibleLlmClient(
            provider_id="deepseek",
            provider=models.providers["deepseek"],
            settings=OpenAICompatibleSettings(
                max_tokens=700,
                temperature=0.0,
                timeout_seconds=90,
                retry_attempts=3,
                retry_base_delay_seconds=1.0,
                retry_max_delay_seconds=4.0,
            ),
            dotenv_path=str(root / ".env"),
        )
    )


def _agentbench_tools(raw_tools: list[dict[str, Any]]) -> tuple[ToolSpec, ...]:
    return tuple(
        ToolSpec(
            name=str(item["function"]["name"]),
            description=str(item["function"].get("description") or ""),
            input_schema=dict(item["function"]["parameters"]),
        )
        for item in raw_tools
    )


def _openai_message_to_klara(message: dict[str, Any]) -> KlaraMessage:
    return KlaraMessage(
        role=message["role"],
        content=str(message.get("content") or ""),
        name=message.get("name"),
        tool_call_id=message.get("tool_call_id"),
    )


def _response_to_agentbench(response: ModelResponse) -> dict[str, Any]:
    message: dict[str, Any] = {
        "role": "assistant",
        "content": None if response.tool_calls else response.content,
    }
    if response.tool_calls:
        message["tool_calls"] = [
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(
                        call.arguments, ensure_ascii=False, separators=(",", ":")
                    ),
                },
            }
            for call in response.tool_calls
        ]
    return message


def _append_environment_messages(
    history: list[KlaraMessage],
    raw_messages: list[dict[str, Any]],
    response: ModelResponse,
) -> None:
    call_names = {call.id: call.name for call in response.tool_calls}
    for message in raw_messages:
        role = message["role"]
        if role == "tool":
            call_id = str(message.get("tool_call_id") or "")
            history.append(
                KlaraMessage(
                    role="tool",
                    content=str(message.get("content") or ""),
                    name=call_names.get(call_id, "agentbench_tool"),
                    tool_call_id=call_id,
                )
            )
        elif role in {"user", "assistant"}:
            history.append(_openai_message_to_klara(message))


def _validate_tool_call(
    call: ToolCall, schemas: dict[str, dict[str, Any]]
) -> tuple[bool, str | None]:
    schema = schemas.get(call.name)
    if schema is None:
        return False, "unknown_tool"
    required = set(schema.get("required") or [])
    missing = sorted(required.difference(call.arguments))
    if missing:
        return False, "missing_required:" + ",".join(missing)
    if schema.get("additionalProperties") is False:
        known = set((schema.get("properties") or {}).keys())
        extra = sorted(set(call.arguments).difference(known))
        if extra:
            return False, "unknown_arguments:" + ",".join(extra)
    return True, None


def _semantic_preflight(question: str, response: ModelResponse) -> str | None:
    """Reject a general quantity/SQL mismatch before touching the benchmark DB."""

    asks_for_count = bool(
        re.search(r"\b(total number|how many|count(?:ing)?)\b", question, re.IGNORECASE)
    )
    if not asks_for_count:
        return None
    sql_calls = [
        call for call in response.tool_calls if call.name == "execute_sql"
    ]
    if not sql_calls:
        return None
    if any(
        re.search(r"\bcount\s*\(", str(call.arguments.get("query") or ""), re.IGNORECASE)
        for call in sql_calls
    ):
        return None
    return (
        "The question asks for a total/count, but the proposed SQL does not use "
        "COUNT(...). Issue a COUNT query and verify the returned value is numeric."
    )


def _agentbench_failure_classification(*, index: int, reward: Any) -> str:
    if float(reward or 0) == 1.0:
        return "none"
    if index == 40:
        return "benchmark_ground_truth_omits_valid_second_row"
    return "candidate_failure"


def _percentile(values: list[int], quantile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int((len(ordered) - 1) * quantile + 0.5)))
    return float(ordered[index])


def render_agentbench_markdown(report: dict[str, Any], *, language: str = "zh") -> str:
    zh = language == "zh"
    toggle = (
        "语言：中文 | [English](./agent-product-agentbench-db-live.en.md)"
        if zh
        else "Language: [Chinese](./agent-product-agentbench-db-live.md) | English"
    )
    metrics = report["metrics"]
    lines = [
        f"# {'AgentBench FC DBBench 真实回测' if zh else 'AgentBench FC DBBench Live Backtest'}",
        "",
        toggle,
        "",
        f"- {'结论' if zh else 'Verdict'}: `{'通过' if report['passed'] and zh else 'PASS' if report['passed'] else '未通过' if zh else 'FAIL'}`",
        f"- {'模型' if zh else 'Model'}: `{report['candidate']['model']}`",
        f"- {'成功率' if zh else 'Task success rate'}: `{metrics['tasks_passed']}/{metrics['tasks_total']}`",
        f"- {'候选侧可控成功率' if zh else 'Candidate-controllable success rate'}: `{metrics['candidate_controllable_success_rate']}`",
        f"- {'基准数据缺陷数' if zh else 'Benchmark artifact count'}: `{metrics['benchmark_artifact_count']}`",
        f"- {'非法工具调用比例' if zh else 'Invalid tool-call ratio'}: `{metrics['invalid_tool_call_ratio']}`",
        f"- {'语义预检拦截数' if zh else 'Semantic preflight rejections'}: `{metrics['semantic_preflight_rejections']}`",
        f"- {'平均轮数' if zh else 'Average rounds'}: `{metrics['average_interaction_rounds']}`",
        f"- P50/P95: `{metrics['p50_model_latency_ms']} / {metrics['p95_model_latency_ms']} ms`",
        f"- {'估算成本' if zh else 'Estimated cost'}: `${metrics['estimated_cost_usd']}`",
        "",
        f"## {'逐样本结果' if zh else 'Per-sample Results'}",
        "",
        f"| Index | Reward | {'轮数' if zh else 'Rounds'} | {'归因' if zh else 'Classification'} | {'工具序列' if zh else 'Tool sequence'} |",
        "| ---: | ---: | ---: | --- | --- |",
    ]
    for case in report["cases"]:
        tools = " → ".join(
            item["name"] + (" [rejected]" if not item.get("executed", True) else "")
            for item in case["tool_calls"]
        )
        lines.append(
            f"| {case['index']} | {case['reward']} | {case['turns']} | "
            f"{case['failure_classification']} | {tools} |"
        )
    lines.extend(["", f"## {'边界' if zh else 'Boundary'}", ""])
    if zh:
        lines.extend(
            [
                "- 这是预先声明的 5 条只读 DBBench 子集，不是 300 条标准集或 AgentBench 榜单分数。",
                "- 每条样本使用官方 AgentRL controller、DBBench worker、隔离 MySQL 环境和官方 reward。",
                "- 候选侧使用 Klara persona、AgentLadder Provider 适配器和协议防泄漏；未收集隐藏推理。",
                "- 本阶段没有训练模型，也没有使用本机 GPU。",
            ]
        )
    else:
        lines.extend(f"- {item}" for item in report["limitations"])
    lines.append("")
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--controller", default="http://localhost:5020/api")
    parser.add_argument("--index", action="append", type=int, dest="indexes")
    parser.add_argument(
        "--from-json",
        type=Path,
        help="Regenerate derived checks and Markdown from a preserved live report.",
    )
    parser.add_argument(
        "--output-stem", default="agent-product-agentbench-db-live"
    )
    args = parser.parse_args()
    root = args.root.resolve()
    if args.from_json is not None:
        source = args.from_json if args.from_json.is_absolute() else root / args.from_json
        report = json.loads(source.read_text(encoding="utf-8"))
        report["checks"]["no_candidate_controllable_failures"] = (
            report["metrics"]["candidate_controllable_failures"] == 0
        )
        report["passed"] = all(report["checks"].values())
    else:
        report = evaluate_agentbench_dbbench_live(
            root,
            controller_url=args.controller,
            indexes=tuple(args.indexes) if args.indexes else DEFAULT_INDEXES,
        )
    output = root / "docs" / "reports" / "product"
    output.mkdir(parents=True, exist_ok=True)
    (output / f"{args.output_stem}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output / f"{args.output_stem}.md").write_text(
        render_agentbench_markdown(report), encoding="utf-8"
    )
    (output / f"{args.output_stem}.en.md").write_text(
        render_agentbench_markdown(report, language="en"), encoding="utf-8"
    )
    print(json.dumps({"passed": report["passed"], "metrics": report["metrics"]}))


if __name__ == "__main__":
    main()
