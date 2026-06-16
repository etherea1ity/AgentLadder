# Klara Chapter Roadmap Reference

## Teaching North Star

Klara grows from a visible ReAct-style loop into a production-ready agent runtime.

The teaching order follows the learner's natural questions:

```text
Can Klara run?
-> Can Klara use tools?
-> Can we intercept and observe lifecycle points?
-> Can one real run be assembled cleanly?
-> Can context fit?
-> Can Klara remember?
-> Can Klara learn procedures?
-> Can Klara read knowledge?
-> Can Klara reason over evidence?
-> Can Klara recover safely?
-> Can Klara work in the background?
-> Can Klara research?
-> Can Klara use external ecosystems?
-> Can Klara run in production?
-> Can traces become eval data?
-> Can eval improve policy through post-training/RL?
```

Compact main line:

```text
Loop -> Tools -> Hooks -> Harness -> Context -> Memory -> Skills
-> RAG -> Evidence -> Policy/Fallback -> Routines -> Research
-> MCP/Plugins -> Production -> Eval -> Post-training/RL
```

RAG is not Klara's core identity. RAG is a knowledge capability that arrives after loop, tools, hooks, context, memory, and skills have stable boundaries.

## Boundary Rule

Each chapter has one main question. Supporting mechanisms are allowed only when they make that question runnable and testable.

Move a topic earlier only if the current chapter cannot be understood or tested without it. Move a topic later if it distracts from the chapter's main question.

## Chapter Route

### Chapter 1 - Minimal LLM Loop

Main question: what is the smallest real Klara runtime heartbeat?

Includes:

- user / assistant / tool message shape
- LLM request and response shape
- optional minimal `debug_echo` tool path to prove the loop can continue
- tool observation as a message
- `prepare_next_turn` as identity
- final answer versus max-turn stop reason
- public lifecycle events
- observer hook for JSONL trace and frontend projection
- minimal full-stack run path

Excludes:

- formal tool ecosystem
- permission hooks
- memory
- RAG
- context compression
- skill system
- production auth
- RL

Why here: readers first need to see a running loop, not a framework.

### Chapter 2 - Tool Calling, Registry, And Capability Partitioning

Main question: how does a model request action, and how does runtime safely decide what actions exist?

Includes:

- model-visible tool schema
- tool registry
- tool executor
- tool result contract
- tool error contract
- unknown tool handling
- tool observation returned to the next LLM turn
- tool namespaces and capability profiles
- visible-tool selection for a chapter/profile
- simple capability partitioning algorithm: choose a small allowed tool set from a larger registry
- starter tools: `clock`, `calculator`, `debug_echo`, `clarify`, fake `search`
- trace events for tool selection, tool start, tool result, and tool error

Excludes:

- `PreToolUse` permission hooks
- external side effects such as shell/filesystem writes
- MCP
- real RAG
- long-term memory

Why here: after the loop, the next ReAct idea is action and observation. Tool selection also introduces the first practical "partitioning" problem without needing full context/memory yet.

### Chapter 3 - Hooks And Lifecycle Control

Main question: where can Klara observe, block, modify, or stop runtime behavior without rewriting the loop?

Includes:

- `SessionStart`
- `UserPromptSubmit`
- `PreToolUse`
- `PostToolUse`
- `Stop`
- `PreCompact`
- `SessionEnd`
- observer hooks versus decision hooks
- hook result contract: allow, block, continue, stop, add context, rewrite safe input
- hook failure isolation
- stop-hook recursion guard
- timeout/cancel shape for hook execution
- public versus private hook payloads
- trace hook remains the simplest observer hook

Excludes:

- full permission policy engine
- full context compression implementation
- memory write policies
- production audit backend

Why here: tools create real lifecycle pressure. Now hooks have something meaningful to intercept.

### Chapter 4 - Harness And Runtime Context

Main question: how is one real Klara run assembled before the loop starts?

Includes:

- persona prompt loading
- response style and Klara identity boundaries
- local `UserContext`
- workspace/project profile bootstrap
- model selection
- capability profile selection
- visible tools
- hook list
- trace sink selection
- session message loading
- runtime context object
- frontend/backend run creation boundary

Excludes:

- durable memory
- context compression
- full auth/account system
- production storage design

Why here: after loop, tools, and hooks are understood, harness becomes concrete: it is the app-layer assembly point for all of them.

### Chapter 5 - Context Engine And Compression

Main question: what should Klara carry into the next LLM turn when the transcript grows?

Includes:

- context budget estimation
- message window
- priority order
- tool-result micro-compaction
- session summary
- compaction threshold
- `PreCompact` hook integration
- context budget trace events
- private versus public context boundaries

Priority order:

```text
current user input
-> current tool results
-> recent visible messages
-> compact profile/context
-> session summary
-> searchable history references
```

Excludes:

- durable memory store
- RAG retrieval
- RL-based context policy

Why here: the loop can now act and be intercepted; the next failure mode is context overflow and noisy history.

### Chapter 6 - Memory System

Main question: how does Klara gain durable continuity without treating chat history as memory?

Includes:

- short-term context versus memory
- profile memory
- durable memory
- event memory
- memory search
- remember/update/delete semantics
- sensitivity classes
- memory lifecycle
- explicit memory tool
- post-run memory review hook

Excludes:

- procedural skills
- RAG over documents
- automatic saving of every chat message

Why here: memory depends on context and hooks, but should arrive before skills and knowledge retrieval so continuity is not confused with documents.

### Chapter 7 - Skills / Procedural Memory

Main question: how does Klara learn repeatable ways of doing work?

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
- skill activation trace

Excludes:

- factual memory
- RAG document retrieval
- plugin/MCP ecosystem

Why here: after Klara can remember facts, she can learn procedures. Skills are "how to do work"; memory is "what should be remembered."

### Chapter 8 - RAG As Knowledge Tool

Main question: how does Klara read a local knowledge base as one capability?

Includes:

- `local_knowledge_search`
- `read_source`
- document metadata
- chunking
- embedding
- BM25 retrieval
- vector retrieval
- hybrid retrieval
- reranking
- context building
- SourceCard
- Citation
- AnswerFrame

Excludes:

- evidence-heavy multi-step workflow
- policy learning
- unrestricted web research

Why here: RAG becomes understandable once tools, context, memory, and skills already have separate meanings.

### Chapter 9 - Controlled Evidence / Agentic RAG

Main question: how does Klara handle evidence-heavy tasks with runtime-owned workflow rather than a free agent loop?

Includes:

- route
- plan
- retrieve
- rewrite/query expansion
- evidence pack
- source selection
- answer writing
- verification
- fallback
- DecisionRecord trace
- frontend source cards and evidence trace

Excludes:

- arbitrary tool autonomy
- RL optimization
- production data governance

Why here: this preserves the useful old AgentLadder Agentic RAG lessons, but places them after the general runtime foundations.

### Chapter 10 - Policy, Fallback, And Safe Perturbation

Main question: how does Klara stay stable when tools, retrieval, models, or evidence are uncertain?

Includes:

- tool/model route policy
- retry rules
- fallback chains
- budget policy
- failure taxonomy
- safe degradation
- local perturbation experiments
- engineering rollback points
- policy trace

Excludes:

- learned policy training
- production incident system

Why here: after evidence workflows, failure and recovery are concrete rather than abstract.

### Chapter 11 - Background Jobs And Routines

Main question: how can Klara do bounded work outside the foreground chat turn?

Includes:

- scheduler
- cron triggers
- webhook triggers
- API triggers
- routine profiles
- restricted capability sets
- audit trace
- notification/delivery
- routine result summaries

Excludes:

- unconstrained autonomy
- background work without trace
- production queue scaling

Why here: routines need policy, hooks, trace, and restricted capabilities.

### Chapter 12 - Research Agent

Main question: how does Klara run a bounded research workflow?

Includes:

- search/read/synthesize/check loop
- source tracking
- uncertainty tracking
- evidence trace
- note cards
- report generation
- follow-up question handling

Excludes:

- unbounded browsing
- arbitrary external side effects
- post-training

Why here: research combines tools, evidence, policy, and routine-like iteration.

### Chapter 13 - MCP, Plugins, And External Tools

Main question: how does Klara connect to external tool ecosystems without losing boundaries?

Includes:

- MCP clients
- MCP servers
- plugin manifests
- resource discovery
- adapters
- permission classes
- external audit events
- tool sandboxing rules

Excludes:

- full production deployment
- arbitrary unrestricted tool execution

Why here: external ecosystems should arrive only after internal tool, hook, policy, and audit concepts exist.

### Chapter 14 - Production Runtime

Main question: what changes when Klara must run for real users?

Includes:

- API boundaries
- users and auth boundary
- sessions
- storage
- streaming
- privacy and redaction
- observability
- deployment safety
- operational runbooks

Excludes:

- teaching-only shortcuts
- policy learning mutation

Why here: user management belongs here, not in the early learning chapters.

### Chapter 15 - Eval Data Flywheel

Main question: how do traces become evaluation data?

Includes:

- trace dataset extraction
- gold examples
- scorers
- rubrics
- failure taxonomy
- regression suites
- reports
- policy candidate evaluation

Excludes:

- live policy mutation
- RL training loop

Why here: eval requires stable traces from many earlier chapters.

### Chapter 16 - Post-training / RL For Agent Policy

Main question: how can eval and feedback improve Klara's policy choices?

Includes:

- preference data
- reward signals
- route policy evaluation
- tool choice policy
- stop decision policy
- retrieval parameter policy
- fallback policy
- offline optimization
- deployment gate for learned policies

Excludes:

- training Klara's persona from scratch
- direct mutation of production behavior from raw eval

Why here: RL/post-training is the capstone after trace, eval, and policy boundaries exist.
