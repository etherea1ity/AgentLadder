# Klara Runtime Restart Plan - 2026-06-15

## Decision

Klara should restart from a **Minimal ReAct Runtime** foundation, but Klara should not become a renamed copy of ReAct/ZENO.

The correct identity split is:

- **Klara**: the product/persona, a calm learning-oriented artificial friend inspired by the idea of an observant presence that grows by watching, reading, remembering, and acting carefully.
- **AgentLadder**: the teaching ladder, the curriculum that explains each layer of an agent system one chapter at a time.
- **ReAct**: the runtime reference, useful for loop/harness/capability boundaries, but not a source to copy wholesale.

The restart should preserve Klara's own voice: calm, precise, honest, branch-aware, and observable. She should feel like a real growing agent inside the AgentLadder curriculum, not like a generic developer demo and not like ZENO with different nouns.

## Evidence From AgentLadder

AgentLadder is already a teaching repo, not only an app. The roadmap says the repo should grow from one LLM call through RAG, Agentic RAG, Memory, Research, MCP, Production, Eval, and RL, with one frozen branch per major theme (`agent-ladder-roadmap.md:3`, `agent-ladder-roadmap.md:23`).

Klara already has a strong persona base. `data/knowledge/global/klara-overview.md` describes her as the Artificial Friend of Agent Ladder: calm, precise, honest, observant, branch-aware, and not an already-complete super-agent. It also says Klara is a teaching device: the learner watches how the run is structured, logged, traced, and improved.

The old Chapter 1 is structurally useful but too small as a long-term foundation. `src/agent_ladder/core/runtime/minimal_agent.py` teaches AskState, LLM call, AnswerState, RunLog, and JSONL trace. That is still valuable, but it does not yet teach the core agent loop shape that later chapters need.

Chapter 2 and Chapter 3 contain lessons that should survive. `src/agent_ladder/core/runtime/klara_agent.py` shows the RAG writer path, while `src/agent_ladder/rag/agentic/runtime.py` shows a controlled Agentic RAG runtime with planning, evidence packing, writing, verification, and trace decisions. These are useful lessons, but they should not define the generic core runtime.

The current Chapter 3 README is clear that Klara should not be a free agent loop for evidence work: runtime owns workflow, budget, failure policy, trace, and schema validation (`README.md:7`). That principle should remain true for evidence-heavy chapters.

## Evidence From ReAct

ReAct has the cleaner runtime skeleton. Its README defines the loop as:

```text
user message -> assistant turn -> tool results? -> prepare_next_turn -> continue/stop
```

Its architecture contract keeps the core business-free: core owns only the provider/tool/prepare loop; app builds prompts and context; services own retrieval/business access; backend owns HTTP/SSE/session/history surfaces (`docs/ARCHITECTURE.md:45`, `docs/ARCHITECTURE.md:61`).

The parts worth borrowing are:

- `AgentLoop` as a small generic loop (`src/zeno_agent/core/loop.py`)
- `AgentHarness` as the app assembly boundary (`src/zeno_agent/app/harness.py`)
- capability profiles from `config/capabilities.toml`
- tool wrapper versus service separation
- memory versus skills separation
- frontend-safe streaming projection
- architecture boundary tests

The parts not worth copying are:

- ZENO naming and product persona
- ZenoWell/health/product tools
- biometrics and product-specific services
- deployment-specific paths and environment names
- provider configuration that belongs to ZENO rather than Klara
- product safety prompts that are not part of AgentLadder's teaching scope

## Why Chapter 1 Should Be Minimal ReAct Runtime

Chapter 1 should not begin with full RAG, memory, research, or MCP. It should also not remain only a single `client.chat()` wrapper.

The right Chapter 1 is:

```text
User message
-> KlaraLoop
-> LLM turn
-> optional tool call
-> observation/tool result
-> prepare_next_turn
-> final answer
-> trace
```

The first lesson can still start with a no-tool single turn. That no-tool turn is the simplest case of the same loop. Then Chapter 1 adds one tiny tool, such as a calculator or clock, so learners see why ReAct exists without drowning in RAG or memory.

This makes later chapters cleaner:

- RAG becomes a capability, not the core loop.
- Memory becomes a context/memory layer, not hidden prompt mutation.
- Research becomes a profile with search/read/evidence tools, not a new app.
- MCP becomes another tool/capability surface, not a rewrite.
- Eval and RL can consume trace events from the beginning.

## New Teaching Route

### Chapter 1 - Minimal ReAct Runtime

Klara learns the smallest real agent loop. The chapter teaches messages, model calls, optional tool calls, observations, stop conditions, `prepare_next_turn`, and JSONL trace.

Acceptance:

- no-tool chat works
- one-tool chat works
- mock LLM works offline
- real LLM works when configured
- trace records public lifecycle events
- core has no RAG, memory, backend, or product imports

### Chapter 2 - Klara Harness And Capability Profiles

Klara learns how a product runtime assembles a turn. The chapter introduces session history, prompt assembly, model selection, capability profiles, tool registry, event hooks, and public SSE events.

Acceptance:

- CLI and API both run through `KlaraHarness`
- capability exposure is config/profile-driven
- frontend receives safe public events
- boundary tests prevent core from importing app/backend/services

### Chapter 3 - Klara's Sun Library As Knowledge Capability

Klara learns local knowledge retrieval as a capability. This preserves the old RAG lesson, but moves it behind the service/capability boundary.

Acceptance:

- local markdown knowledge loads with metadata
- chunking, indexing, dense/BM25/hybrid retrieval remain teachable
- SourceCard, Citation, and AnswerFrameV1 remain
- Run Margin shows sources and trace without exposing private reasoning

### Chapter 4 - Controlled Evidence Runtime / Agentic RAG

Klara learns controlled evidence work. This is where current v0.3 ideas belong: RequestSpec, EvidenceSearchPlan, SearchProvider, FetchProvider, EvidencePack, AnswerWriter, Verifier, and DecisionRecord.

Acceptance:

- writer only sees EvidencePack, not raw corpus internals
- verifier checks claim/source support
- insufficient evidence is an explicit outcome
- trace records planning, search, selection, writing, verification, and fallback decisions

### Chapter 5 - Memory Agent

Klara learns that message history is not memory. The chapter introduces profile memory, durable memory, event memory, session summary, recall, write policy, and delete/update semantics.

Acceptance:

- memory writes are explicit or policy-approved
- high-sensitivity content is not casually injected
- Klara can explain what she remembers and how it can be changed
- deletion semantics are product-consistent

### Chapter 6 - Skills / Procedural Memory

Klara learns procedural memory: compact skill list, on-demand skill view, and controlled skill management.

Acceptance:

- skills are separate from memory
- prompts receive compact skill metadata first
- full skill instructions load only when needed
- user skills and built-in course skills have clear boundaries

### Chapter 7 - Research Agent

Klara learns planned research across local knowledge and web/page reading. This chapter should add source ranking, credibility, evidence tables, contradiction handling, and long-form synthesis.

### Chapter 8 - MCP Tool Agent

Klara learns external tool ecosystems: MCP clients, servers, adapters, permission checks, audit logs, and tool error surfaces.

### Chapter 9 - Production Agent

Klara learns production reliability: user isolation, storage adapters, auth, rate limits, cancellation, retries, timeouts, observability, deployment, and redaction.

### Chapter 10 - Eval And Policy Learning

Klara learns how traces become evaluation data and how evaluation can improve routing, retrieval, tool choice, and policy.

## Keep / Rebuild / Drop

Keep:

- Klara persona and visual identity
- AgentLadder as the teaching ladder
- roadmap/freeze/chapter documentation habit
- AskState, AnswerState, RunLog, JSONL trace idea
- RAG contracts around sources, citations, and answer frames
- Chapter 3 EvidencePack, verifier, and decision trace lessons
- single chat surface with Run Margin

Rebuild:

- generic core runtime as `KlaraLoop`
- app assembly as `KlaraHarness`
- tool/capability exposure as profiles
- event model shared by trace and SSE
- RAG as knowledge capability/service
- frontend trace panels around generic events instead of v0.3-specific state

Drop or archive:

- chapter-specific orchestration inside the generic core
- standalone wrong-chain Chapter 3 routes/pages
- v0.3-only UI storage/event naming as permanent contracts
- direct ZENO product/service code
- hidden memory behavior before the memory chapter

## Architecture Principle

Klara can eventually resemble ZENO in capability depth, but not in identity or coupling.

The target shape is:

```text
klara_core
  generic loop, messages, tools, events

klara_app
  harness, prompt assembly, context assembly, session lifecycle

klara_capabilities
  registry, profiles, model-facing tool wrappers

klara_services
  knowledge, papers, web, research, external systems

klara_memory
  profile, durable memory, event memory, session summary, recall

klara_backend
  HTTP, SSE, sessions, history, frontend-safe trace summaries

klara_ui
  chat, compose, run margin, source/evidence views

docs/chapters
  teaching narrative and freeze notes
```

The core rule: **the loop should not know what Klara knows; the harness decides what Klara can see; capabilities decide what Klara can do; traces show what happened.**

## First Implementation Stage After This Plan

1. Inventory and protect the current v0.3 working tree.
2. Decide whether to restart numbering at `v0.1-minimal-react-runtime` or continue with a foundation branch before `v0.4-memory-agent`.
3. Write `docs/architecture/klara-runtime-foundation.md`.
4. Add boundary tests before moving runtime code.
5. Implement `KlaraLoop` with mock-first tests.
6. Implement `KlaraHarness` with CLI first.
7. Connect API/SSE and UI after the loop/harness contract is stable.
8. Reintroduce local knowledge as a capability, not as core runtime logic.

Recommended branch name if this is a true curriculum reboot:

```text
v0.1-minimal-react-runtime
```

Recommended branch name if preserving old chapter numbering:

```text
phase/v0.4-klara-runtime-foundation
```

## Risks

- Copying ReAct too directly would erase Klara's identity.
- Keeping the old `KlaraAgent` as the center would make later memory/tools/research chapters harder.
- Starting Chapter 1 with too much ReAct complexity would hurt the teaching route.
- Not protecting untracked v0.3 assets could lose useful paper/docs work.
- Generic tool loops can become too free; evidence-heavy chapters still need bounded controlled runtimes.

## Success Criteria

The restart is successful when:

- a learner can understand Chapter 1 without knowing RAG
- Klara feels like Klara in prompt, UI, trace, and docs
- AgentLadder still reads like a course, not a product dump
- ReAct's architecture lessons are visible, but ZENO product details are absent
- every later chapter has a stable home in the architecture
- trace remains public, useful, and safe from the first chapter

