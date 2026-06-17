from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from agent_ladder.core.runtime.minimal_agent import MinimalAgent
from agent_ladder.core.tracing.jsonl_tracer import JsonlTracer
from agent_ladder.infra.config.loader import load_config
from agent_ladder.llm.providers.dashscope import DashScopeClient
from agent_ladder.rag.agentic.runtime import AgenticRAGRuntime


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.command == "ask":
        return ask_command(args.question)
    if args.command == "ask-agentic":
        return ask_agentic_command(args.question, paper_root=args.paper_root)

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

    agentic_parser = subparsers.add_parser("ask-agentic", help="Ask the Chapter 3 controlled Agentic RAG runtime")
    agentic_parser.add_argument("question", help="Question to send to Agentic RAG")
    agentic_parser.add_argument("--paper-root", default=None, help="Paper corpus root. Defaults to AGENT_LADDER_PAPER_ROOT or fixtures.")

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


def ask_agentic_command(question: str, *, paper_root: str | None = None) -> int:
    config = load_config()
    selected_paper_root = paper_root or os.environ.get("AGENT_LADDER_PAPER_ROOT") or "data/papers/fixtures"
    runtime = AgenticRAGRuntime(trace_path=config.tracing.path, paper_root=selected_paper_root)
    result = runtime.run(question, save_trace=config.tracing.enabled)
    frame = result.answer_frame
    state = result.state

    print("Question:")
    print(question)
    print()
    print("Answer:")
    print(frame.final_text)
    print()
    print("Sources:")
    for source in frame.sources:
        print(f"- {source.source_id}: {source.title} [{source.source_type}]")
    print()
    print("Visual Sources:")
    visual_sources = frame.visual_sources
    if visual_sources:
        for visual in visual_sources:
            print(f"- {visual.visual_id}: {visual.label}, page={visual.page}, image_path={visual.image_path}, caption={visual.caption}")
    else:
        print("- none")
    print()
    print("Run info:")
    print(f"route={state.route.route if state.route else 'unknown'}")
    print(f"run_mode={state.run_mode}")
    print(f"search_units={len(state.search_plan.search_units) if state.search_plan else 0}")
    print(f"retrieval_attempts={len(state.retrieval_attempts)}")
    print(f"evidence_items={len(state.evidence_pack.items) if state.evidence_pack else 0}")
    print(f"verification_status={state.verification.status if state.verification else 'unknown'}")
    print(f"latency_ms={result.latency_ms}")
    print(f"trace_saved={result.trace_saved}")
    print(f"paper_root={selected_paper_root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
