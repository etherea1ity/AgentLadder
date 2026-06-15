# Klara Architecture Roadmap

This branch is intentionally documentation-only.

It is the clean restart space for Klara's technical architecture and teaching route. It does not contain application code, old AgentLadder source files, frontend assets, RAG indexes, data files, or runtime artifacts.

## Purpose

Klara is the product/persona and learning agent.

AgentLadder is the curriculum that teaches how Klara is built one capability layer at a time.

ReAct/ZENO is a reference implementation for runtime architecture ideas, especially loop, harness, hooks, context, capability profiles, memory, skills, background jobs, streaming, and trace. Klara should borrow the architecture principles without copying the product identity or domain-specific services.

## Core Decision

Klara restarts from a loop-first architecture:

```text
Loop -> Harness -> Hooks -> Tools -> Context -> Memory -> Skills -> RAG
     -> Evidence -> Policy/Fallback -> Background Jobs -> Research
     -> MCP -> Production -> Eval -> Post-training/RL
```

RAG is not Klara's core identity. RAG is a knowledge capability/tool that Klara learns after the loop, harness, hooks, tools, and context foundations are in place.

## Documents

- `docs/architecture/klara-technical-roadmap.md` - chapter-by-chapter technical route.
- `docs/architecture/klara-future-folder-map.md` - target repository and package layout.
- `docs/architecture/ch01-minimal-loop-spec.md` - first implementation chapter scope.
- `docs/architecture/klara-reference-synthesis.md` - lessons from ReAct, OpenClaw, Claw Code, Hermes, and Claude-Code-style architecture.
- `docs/chapters/ch01-minimal-agent-loop.md` - Chapter 1 reading guide for the minimal loop implementation.

## Current Implementation

The implementation branch starts with Chapter 1 only:

- `src/klara/core` contains the minimal loop, messages, tools, events, hooks,
  policy, and tool executor.
- `src/klara/app` contains the thin harness and local default `UserContext`.
- `src/klara/capabilities` exposes the Chapter 1 `debug_echo` fake tool.
- `tests/klara` verifies loop behavior, hook isolation, harness assembly, and
  the core import boundary.

Chapter 1 details live in `docs/chapters/ch01-minimal-agent-loop.md`.
