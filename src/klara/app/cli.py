"""Run Klara through the same frozen harness used by the API."""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import os
from pathlib import Path
from typing import Sequence

from klara.app.harness import KlaraHarness, KlaraHarnessConfig
from klara.app.user_context import UserContext
from klara.infra.config.loader import load_models_config, load_runtime_config
from klara.infra.llm.routed_client import RoutedLlmClient
from klara.planning.tool import TodoWriteTool
from klara.planning.todo import TodoItem, TodoOperation, TodoPlan, apply_todo_update
from klara.tools.registry import ToolRegistry


class _CliTodoStore:
    """In-memory current-run plan store for the CLI teaching path."""

    def __init__(self) -> None:
        self.plan: TodoPlan | None = None

    def update_todo_plan(
        self,
        session_id: str,
        operation: TodoOperation,
        items: list[TodoItem],
    ) -> TodoPlan:
        self.plan = apply_todo_update(
            session_id=session_id,
            existing=self.plan,
            operation=operation,
            items=items,
        )
        return self.plan


def build_harness(
    *,
    config_dir: Path,
    model: str | None,
    thinking_enabled: bool | None,
    trace_path: Path,
) -> KlaraHarness:
    """Load config and build one capability-checked product harness."""

    models = load_models_config(config_dir)
    runtime = load_runtime_config(config_dir)
    selected_model = model or models.profile("agent").primary
    timezone = os.getenv("KLARA_TIMEZONE", "local").strip() or "local"
    user_context = replace(UserContext.local_default(), timezone=timezone)
    registry = ToolRegistry.with_default_tools()
    registry.register_tool(TodoWriteTool(session_id="cli-session", store=_CliTodoStore()))
    return KlaraHarness(
        llm=RoutedLlmClient(models=models, dotenv_path=".env"),
        registry=registry,
        models=models,
        config=KlaraHarnessConfig(
            model=selected_model,
            thinking_enabled=thinking_enabled,
            capability_profile=runtime.profile(),
            trace_path=trace_path,
            loop_policy=runtime.loop_policy,
            user_context=user_context,
        ),
    )


def build_parser() -> argparse.ArgumentParser:
    """Build a small Chapter 4 CLI around the product harness."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("question", nargs="?", help="Question for one real Klara run.")
    parser.add_argument("--config-dir", type=Path, default=Path("config"))
    parser.add_argument("--model")
    parser.add_argument("--thinking", action=argparse.BooleanOptionalAction, default=None)
    parser.add_argument("--trace-path", type=Path, default=Path("data/traces/cli-runs.jsonl"))
    parser.add_argument(
        "--profile-only",
        action="store_true",
        help="Print the secret-free frozen profile without calling a provider.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Inspect a profile or execute one run through `KlaraHarness`."""

    args = build_parser().parse_args(argv)
    harness = build_harness(
        config_dir=args.config_dir,
        model=args.model,
        thinking_enabled=args.thinking,
        trace_path=args.trace_path,
    )
    if args.profile_only:
        print(json.dumps(harness.run_profile.to_public_dict(), ensure_ascii=False, indent=2))
        return 0
    if not args.question:
        raise SystemExit("question is required unless --profile-only is used")
    result = harness.run(args.question)
    print(result.final_answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
