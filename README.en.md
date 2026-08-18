# Klara / AgentLadder

Language: [Chinese](./README.md) | English

An open-source full-stack agent harness built from scratch, using one public event stream and trajectory-based evaluation to go all the way from trajectory distillation to a self-trained sparse MoE model.

## What This Is

Klara is not a single demo. It is a progressive course line where every chapter leaves behind a runnable, testable, and explainable Klara version.

- **Foundation Track (Chapter 1~18)**: from a minimal LLM loop through tool calling, hooks/trace, harness, todo, context, memory, RAG, task system, subagents/teams, MCP, and a production runtime and eval bridge.
- **Advanced Labs**: evidence evaluation, trajectory distillation, tiny pretraining, sparse MoE, and FP16/FP4.
- **Klara MoE**: a self-trained 4-expert top-2 sparse MoE, compared against Qwen QLoRA and DeepSeek baselines.

## Chapter Navigation

| Chapter | Topic | Doc |
| --- | --- | --- |
| 1 | Minimal LLM Loop | [ch01-minimal-agent-loop](./docs/chapters/ch01-minimal-agent-loop.en.md) |
| 2 | Tool Calling | [ch02-tool-calling](./docs/chapters/ch02-tool-calling.en.md) |
| 3 | Hooks and Trace | [ch03-hooks-and-trace](./docs/chapters/ch03-hooks-and-trace.en.md) |
| 4 | Harness and Config | [ch04-harness-and-config](./docs/chapters/ch04-harness-and-config.en.md) |
| 5 | Todo Planning | [ch05-todo-planning](./docs/chapters/ch05-todo-planning.en.md) |
| 6 | System Prompt and Context Assembly | [ch06-system-prompt-and-context-assembly](./docs/chapters/ch06-system-prompt-and-context-assembly.en.md) |
| 7 | Context Compression | [ch07-context-compression](./docs/chapters/ch07-context-compression.en.md) |
| 8 | Error Recovery and Fallback | [ch08-error-recovery-and-fallback](./docs/chapters/ch08-error-recovery-and-fallback.en.md) |
| 9 | Skills Procedural Memory | [ch09-skills-procedural-memory](./docs/chapters/ch09-skills-procedural-memory.en.md) |
| 10 | Memory System | [ch10-memory-system](./docs/chapters/ch10-memory-system.en.md) |
| 12 | Controlled Agentic RAG | [ch12-controlled-agentic-rag](./docs/chapters/ch12-controlled-agentic-rag.en.md) |
| 13 | Research Agent | [ch13-research-agent](./docs/chapters/ch13-research-agent.en.md) |
| 14 | Durable Tasks | [ch14-durable-tasks](./docs/chapters/ch14-durable-tasks.en.md) |
| 15 | Background Scheduler | [ch15-background-scheduler](./docs/chapters/ch15-background-scheduler.en.md) |
| 16 | Subagents and Teams | [ch16-subagents-teams-worktrees](./docs/chapters/ch16-subagents-teams-worktrees.en.md) |
| 17 | MCP and External Tools | [ch17-mcp-and-external-tools](./docs/chapters/ch17-mcp-and-external-tools.en.md) |
| 18 | Production Runtime and Eval Bridge | [ch18-production-runtime-and-eval-bridge](./docs/chapters/ch18-production-runtime-and-eval-bridge.en.md) |
| Appendix | Permission Engine | [permission-engine](./docs/chapters/permission-engine.en.md) |

## Advanced Labs

- [Algorithm Suite: evidence, distillation, MoE, and FP16/FP4](./docs/labs/algorithm-suite.en.md)
- [Agent Product Freeze Readiness](./docs/labs/agent-product-freeze-readiness.en.md)
- [Prompt Context Recovery Hardening](./docs/labs/prompt-context-recovery-hardening.en.md)

## Quick Start

Prepare `.env`, then start the backend and frontend:

```powershell
.\scripts\dev.ps1
```

Open:

```text
http://127.0.0.1:5123
```

## Roadmap

See [Klara Roadmap](./docs/skills/roadmap.md) for the full course plan.

## Branches

The project is split progressively by chapter:

```text
main
 -> chapter-2-tool-calling
 -> codex/ch03-algorithm-roadmap
 -> codex/ch04-harness-config
 -> ...
 -> codex/ch18-production-runtime
 -> codex/agent-product-*
 -> codex/klara-*
```
