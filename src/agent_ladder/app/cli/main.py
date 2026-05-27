from __future__ import annotations

import argparse
import sys
from pathlib import Path

from agent_ladder.core.runtime.minimal_agent import MinimalAgent
from agent_ladder.core.tracing.jsonl_tracer import JsonlTracer
from agent_ladder.infra.config.loader import load_config
from agent_ladder.llm.providers.dashscope import DashScopeClient


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "ask":
        return ask_command(args.question)

    parser.print_help()
    return 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agent-ladder",
        description="AgentLadder v0.1 Minimal Agent CLI",
    )
    subparsers = parser.add_subparsers(dest="command")

    ask_parser = subparsers.add_parser("ask", help="Ask the minimal agent one question")
    ask_parser.add_argument("question", help="Question to send to the LLM")

    return parser


def ask_command(question: str) -> int:
    config = load_config()
    llm_client = DashScopeClient(config.llm)

    tracer = None
    if config.tracing.enabled:
        tracer = JsonlTracer(Path(config.tracing.path))

    agent = MinimalAgent(llm_client=llm_client, tracer=tracer)
    result = agent.ask(question)

    print("Question:")
    print(result.ask.question)
    print()
    print("Answer:")
    print(result.answer.answer)
    print()
    print("Run:")
    print(f"run_id={result.run.run_id}")
    print(f"ask_id={result.run.ask_id}")
    print(f"model={result.run.model}")
    print(f"latency_ms={result.run.latency_ms}")
    print(f"prompt_tokens={result.run.prompt_tokens}")
    print(f"completion_tokens={result.run.completion_tokens}")
    print(f"total_tokens={result.run.total_tokens}")
    print(f"token_source={result.run.token_source}")
    print(f"trace_saved={config.tracing.enabled}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
