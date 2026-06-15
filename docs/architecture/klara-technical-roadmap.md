# Klara Technical Roadmap

## North Star

Klara is a calm, branch-aware, observable agent runtime. She should grow one technical layer at a time, and each chapter should teach exactly one major concept.

The main line is not RAG. The main line is:

```text
Loop -> Runtime assembly -> Lifecycle control -> Capabilities -> Context
     -> Continuity -> Procedure -> Knowledge -> Evidence -> Policy
     -> Background maintenance -> Research -> External tools -> Production
     -> Evaluation -> Policy learning
```

## Architecture Principles

1. **Loop stays small.** The core loop knows messages, model turns, tool calls, tool results, continuation, stop reasons, and events. It does not know RAG, memory, web, UI, backend, product facts, or persistence adapters.
2. **Harness assembles the run.** Persona, system prompt, runtime context, visible tools, model choice, hooks, trace sinks, and session history are app-layer responsibilities.
3. **Hooks are deterministic control points.** Hooks observe or guard lifecycle events. They are not prompt suggestions.
4. **Capabilities are exposed by profile.** Registration and exposure are separate. A tool can exist without being visible in a given chapter/profile.
5. **Context is engineered before the loop.** Compression, summaries, budget reports, and priority ordering happen outside core.
6. **Memory is not chat history.** Memory must have explicit stores, policies, recall, deletion/update semantics, and sensitivity boundaries.
7. **Skills are procedural memory.** Skills say how to handle repeatable work; memory says what is durably true or useful about the user/project.
8. **RAG is a capability.** RAG can have an internal pipeline, but from Klara's loop it appears as a knowledge tool/service result.
9. **Trace starts on day one.** Trace is not only UI debug output; it becomes the future eval and policy-learning dataset.
10. **Eval and RL optimize policy, not magic intelligence.** The final stage improves routing, tool choice, stop decisions, retrieval parameters, fallback behavior, and answer policy from traces and feedback.

## Chapter Route

### Chapter 1 - Minimal Agent Loop

**Topic:** Klara's smallest runtime heartbeat.

Includes:

- message types: user, assistant, tool
- model request/response shape
- tool call shape
- tool result / observation
- loop continuation and stop reason
- `prepare_next_turn`
- event emission
- JSONL trace
- mock LLM tests

Does not include:

- RAG
- memory
- skills
- real backend/frontend
- production tool permissions

### Chapter 2 - Harness And Runtime Context

**Topic:** How one Klara run is assembled.

Includes:

- Klara persona prompt
- runtime context object
- model configuration
- session message loading
- current chapter/profile context
- trace sink selection
- minimal CLI
- no-tool and one-tool harness runs

Does not include:

- long-term memory
- context compression
- full tool ecosystem

### Chapter 3 - Hooks And Lifecycle Control

**Topic:** Deterministic lifecycle points around the loop.

Includes:

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `Stop`
- `PreCompact`
- `SessionEnd`
- hook manager
- hook failure isolation
- policy hooks versus observability hooks
- public versus private hook payloads

Purpose:

- inject deterministic context
- approve/deny dangerous tools
- validate tool outputs
- save trace artifacts before compaction
- run final completion checks before stop

### Chapter 4 - Tools And Capabilities

**Topic:** How Klara uses abilities.

Includes:

- tool registry
- tool schema
- tool executor
- tool result contract
- tool errors
- capability profiles
- permission classes
- basic tools: `clock`, `calculator`, `clarify`, `debug_echo`, fake `search`

Does not include:

- full RAG implementation
- memory persistence
- external side effects

### Chapter 5 - Context Engine And Compression

**Topic:** How Klara decides what can fit into the next turn.

Includes:

- context budget estimation
- message window
- priority order
- tool-result micro-compaction
- session summary
- compaction threshold
- `PreCompact` hook
- context budget trace events

Priority:

```text
current user input
-> current tool results
-> recent visible messages
-> compact profile/context
-> session summary
-> searchable history references
```

Rule:

Session summary is continuity reference, not instruction.

### Chapter 6 - Memory System

**Topic:** How Klara gains continuity.

Includes:

- short-term context versus memory
- profile memory
- durable memory
- event memory
- memory search
- memory remember/update/delete
- sensitivity classes
- memory lifecycle
- explicit memory tool
- background memory review as a later optional layer

Does not include:

- procedural skills
- blindly saving all chat history

### Chapter 7 - Skills / Procedural Memory

**Topic:** How Klara learns repeatable ways of doing work.

Includes:

- skill metadata
- skill store
- `skills_list`
- `skill_view`
- `skill_manage`
- built-in skills
- user/project skills
- precedence rules
- progressive disclosure
- background skill review

Rule:

Skills are "how to do this class of work"; memory is "what should be remembered."

### Chapter 8 - RAG As Knowledge Tool

**Topic:** How Klara reads local knowledge.

Includes:

- `local_knowledge_search`
- `read_source`
- document metadata
- chunking
- embedding
- BM25/vector/hybrid retrieval
- reranking
- context building
- SourceCard
- Citation
- AnswerFrame

Position:

```text
KlaraLoop -> knowledge tool -> RAG service -> evidence observation -> final answer
```

RAG remains a pipeline internally, but it is not Klara's top-level runtime.

### Chapter 9 - Controlled Evidence / Agentic RAG

**Topic:** How Klara performs bounded evidence work.

Includes:

- request specification
- query planning
- query rewrite
- multi-search
- fetch/read providers
- EvidencePack
- answer writer constrained to evidence
- verifier
- insufficient evidence outcome
- DecisionTrace

Rule:

Evidence-heavy work is controlled by runtime policy. It is not a free-form tool loop.

### Chapter 10 - Policy, Fallback, And Safe Perturbation

**Topic:** How Klara handles uncertainty, failure, and exploration.

Includes:

- route policy
- stop policy
- tool retry policy
- model fallback
- tool fallback
- RAG fallback
- budget exhaustion
- timeout behavior
- safe perturbation for eval

Perturbation examples:

- alternative retriever `top_k`
- alternative reranker thresholds
- alternative tool order
- different route threshold
- one controlled extra search pass

Purpose:

Prepare for eval and policy learning without letting foreground behavior become chaotic.

### Chapter 11 - Background Jobs

**Topic:** How Klara maintains herself outside the foreground turn.

Includes:

- post-turn job scheduler
- memory review job
- skill review job
- summary refresh job
- index refresh job
- eval sampling job
- restricted background capability profiles
- job trace

Rule:

Background jobs may propose or store maintenance artifacts. They must not silently rewrite foreground conversation behavior.

### Chapter 12 - Research Agent

**Topic:** How Klara does longer research tasks.

Includes:

- web search
- page read/fetch
- paper search
- source ranking
- source credibility
- evidence table
- conflict handling
- long-form synthesis
- report generation

Rule:

Research is a composition of capabilities and evidence policy, not a rewrite of the loop.

### Chapter 13 - MCP And External Tools

**Topic:** How Klara connects to external tool ecosystems.

Includes:

- MCP client
- MCP server
- tool adapters
- permission gate
- audit log
- sandbox
- side-effect policy
- external error handling

Rule:

External side effects always require explicit permission and traceable audit.

### Chapter 14 - Production Runtime

**Topic:** How Klara runs reliably for real users.

Includes:

- user partitioning
- storage adapters
- auth
- session history
- SSE/streaming projection
- cancellation
- retry
- timeout
- rate limit
- observability
- redaction
- deployment shape

Rule:

Storage and transport can change, but loop/harness/capability boundaries should remain stable.

### Chapter 15 - Eval Data Flywheel

**Topic:** How Klara knows whether she improved.

Includes:

- trace dataset
- route eval
- tool eval
- RAG eval
- citation eval
- memory eval
- skill eval
- answer eval
- latency/cost eval
- failure taxonomy
- reports

Rule:

Eval consumes traces and creates feedback. It does not directly mutate live policy.

### Chapter 16 - Post-training / RL For Agent Policy

**Topic:** How Klara learns from trajectories.

Includes:

- preference data
- reward design
- offline policy eval
- router policy optimization
- tool policy optimization
- stop policy optimization
- retrieval parameter optimization
- DPO/RL concepts
- safety constraints

Rule:

This chapter optimizes Klara's decision policy. It is not about training a frontier model from scratch.

## Why Hooks And Context Come Early

Hooks and context compression must appear before RAG, memory, skills, and research because they are structural:

- RAG needs tool lifecycle events.
- Memory needs post-turn hooks and context priority.
- Skills need progressive loading and prompt budget control.
- Research needs trace and stop/fallback control.
- Eval/RL need clean event trajectories from the beginning.

If hooks arrive late, every previous chapter will need invasive rewrites. If hooks arrive early, each later chapter attaches to a known lifecycle.

## Minimum First Implementation Scope

The first code chapter should implement only:

```text
KlaraLoop
KlaraMessage
KlaraToolCall
KlaraToolResult
KlaraEvent
HookManager
JsonlTraceHook
prepare_next_turn
one mock LLM
one fake tool
boundary tests
```

Everything else should be documented as future architecture, not implemented in Chapter 1.

