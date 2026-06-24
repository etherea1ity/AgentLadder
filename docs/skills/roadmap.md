# Klara Roadmap Reference

## Teaching North Star

Klara grows as a runnable harness, not as a pile of abstractions.

Each foundation chapter must leave behind a working Klara version that can be
started, tested, and explained in a README. The chapter may keep implementation
small, but it must not be only a design note.

The long-term course has two layers:

```text
Foundation Track:
  build a complete Claude-Code-like Klara harness around one loop

Advanced Labs:
  use Klara traces and runtime surfaces to study training, MoE, RAG,
  memory, and RL optimization
```

The foundation track is about the harness: tools, hooks, context, memory, RAG,
tasks, teams, external tools, production boundaries, and trace/eval data.

The advanced labs are about improving the intelligence and policies that run
inside or around that harness.

## Course Shape

Use this rule when deciding whether a topic deserves its own chapter:

```text
one chapter = one runnable Klara version with one dominant mechanism
```

Do not split internal parts of one mechanism into separate chapters unless each
split creates a meaningful runnable version.

Examples:

- Tool schema, registry, metadata, executor, serial/parallel execution, and tool
  errors belong in one tool-calling chapter.
- Permission should not be an early standalone chapter. It is first represented
  as metadata and hook placement, then taught concretely when external tools,
  background work, MCP, teams, and production risks make approval meaningful.
- The UI/window is not a standalone chapter. The frontend is the visible proof
  surface for each runnable chapter.

## Compact Foundation Line

```text
Loop -> Tool Calling -> Hooks/Trace -> Harness/Config -> Todo
-> Context Assembly -> Context Compression -> Recovery -> Skills -> Memory
-> RAG Tool -> Agentic RAG -> Research -> Task System
-> Background/Scheduler -> Subagents/Teams -> MCP -> Production/Eval Bridge
```

RAG is not Klara's core identity. RAG is a knowledge capability that becomes
clear after the loop, tools, hooks, context, memory, and skills have homes.

## Foundation Track

### Chapter 1 - Minimal LLM Loop

Main question: what is the smallest real Klara runtime heartbeat?

Runnable result:

- chat can call a configured LLM
- one minimal tool path can return an observation
- the loop can continue or stop
- trace/UI receives public lifecycle events

Includes:

- user / assistant / tool message shape
- LLM request and response shape
- model response with optional tool calls
- tool observation as a message
- `prepare_next_turn` as identity
- bounded stop reason
- observer hook for JSONL trace and frontend projection

Excludes:

- formal tool ecosystem
- permission policy
- RAG
- memory
- context compression
- skills
- training/RL

### Chapter 2 - Tool Calling

Main question: how does Klara expose actions to the model and turn tool calls
back into observations?

Runnable result:

- model can call a local current-time tool
- model can search the public web and fetch a chosen page through read-only
  network tools
- tool errors return model-visible observations
- registry exposes only visible tools
- tool traces show start/result/error

Includes:

- one-package-per-tool layout
- model-visible `ToolSpec`
- Klara-visible `ToolMetadata`
- tool registry
- tool executor
- tool result/error contract
- unknown tool handling
- serial versus parallel execution planning
- starter local current-time tool
- starter read-only network tools: `web_search` for ranked URLs and `web_fetch`
  for reading one public page
- network tool metadata such as `side_effect=network` and
  `output_trust=untrusted`

Excludes:

- full permission approval
- shell/filesystem mutation tools
- paid or account-backed search provider routing
- MCP transport
- real RAG

### Chapter 3 - Hooks And Trace

Main question: where can Klara observe or influence lifecycle behavior without
rewriting the loop?

Runnable result:

- hooks receive lifecycle events
- trace and frontend projections are produced from the same public events
- tool start/result cards appear in the run surface
- trace records per-run, per-turn, and per-tool duration/usage metrics
- GPT-style thinking block shows `Thinking...`, then `Thought for Xs` only
  when visible public activity exists
- hook failure does not crash the loop
- `UserPromptSubmit` / `PreToolUse` / `PostToolUse` / `Stop` placements are real
- public/private hook payload boundary is explicit
- trace event schema is stable enough for teaching and replay
- current web-evidence traces separate search candidates from fetched page text without runtime semantic guards
- provider reasoning summaries can appear as `Model thinking`
- main-model public commentary appears as Klara activity before or between tool
  calls
- runtime action transcript appears as compact safe Agent activity

Includes:

- observer hooks
- `UserPromptSubmit`
- `PreToolUse` placement
- `PostToolUse`
- `Stop`
- hook failure isolation
- public versus private hook payloads
- trace event schema
- trace metrics: duration, latency, usage totals, token source
- API/SSE projection from public events
- frontend GPT-style thinking block plus developer trace panel
- source-quality signals for current web evidence
- assistant activity projection from model text plus tool calls
- sanitized runtime action transcript for Activity Drawer

Excludes:

- complete permission engine
- Todo Planning
- agent task ledger
- context compression implementation
- memory write policy
- full provider streaming adapter
- fake periodic thinking text
- raw chain-of-thought display
- default completed-summary generator

### Chapter 4 - Harness And Config

Main question: how is one real Klara run assembled before the loop starts?

Runnable result:

- CLI/API/frontend runs all go through `KlaraHarness`
- provider and model choices come from config
- persona and capability profile are assembled outside core

Includes:

- persona prompt loading
- model/provider routing
- `.env` and config loading
- capability profile selection
- visible tools
- hook list
- trace sink selection
- runtime context object
- frontend/backend run creation boundary

Excludes:

- durable memory
- auth/user management
- production storage design

### Chapter 5 - Todo Planning

Main question: how does Klara keep the current task from drifting?

Runnable result:

- model can call `todo_write`
- current session shows todo state
- todo updates are visible in trace/UI

Includes:

- todo item contract
- pending / in-progress / completed states
- one active item convention
- current-session persistence
- todo trace events
- frontend plan display

Excludes:

- durable task graph
- multi-agent task claiming
- background jobs

### Chapter 6 - System Prompt And Context Assembly

Main question: what does Klara assemble before a model turn?

Runnable result:

- system prompt is assembled at runtime
- workspace/project/user context can be injected safely
- the loop still receives prepared dependencies only

Includes:

- prompt sections
- persona section
- workspace profile
- current session summary placeholder
- capability summary
- context boundary between public trace and private prompt material

Excludes:

- compression
- long-term memory
- RAG retrieval

### Chapter 7 - Context Compression

Main question: what should Klara carry forward when the transcript grows?

Runnable result:

- long runs trigger compaction
- recent messages stay visible
- older material is summarized or trimmed according to policy

Includes:

- token or character budget estimate
- message window
- priority order
- tool-result micro-compaction
- session summary
- `PreCompact` hook placement
- context budget trace events

Excludes:

- durable memory store
- RAG retrieval
- learned context policy

### Chapter 8 - Error Recovery And Fallback

Main question: how does Klara recover when a provider, prompt, or tool fails?

Runnable result:

- transient provider failures retry
- prompt-too-long can trigger compaction and retry
- fallback model path is visible in trace

Includes:

- retry taxonomy
- timeout handling
- prompt-too-long recovery
- fallback model route
- tool failure observation
- public failure trace

Excludes:

- production incident response
- learned fallback policy

### Chapter 9 - Skills / Procedural Memory

Main question: how does Klara learn repeatable procedures without stuffing every
instruction into the prompt?

Runnable result:

- skills can be listed
- one skill can be loaded on demand
- loaded skill content affects a later model turn

Includes:

- skill metadata
- skill catalog
- `skills_list`
- `skill_view`
- built-in skills
- project skills
- precedence rules
- progressive disclosure
- skill activation trace

Excludes:

- factual memory
- RAG document retrieval
- MCP plugin ecosystem

### Chapter 10 - Memory System

Main question: how does Klara gain durable continuity without treating chat
history as memory?

Runnable result:

- user can ask Klara to remember, search, update, and delete memory
- memory writes are explicit or policy-approved
- Klara can explain what she remembers

Includes:

- short-term context versus memory
- profile memory
- event memory
- durable memory records
- remember/search/update/delete
- sensitivity classes
- memory review hook
- deletion semantics

Excludes:

- automatic saving of every chat message
- RAG over document collections
- advanced consolidation research

### Chapter 11 - RAG As Knowledge Tool

Main question: how does Klara read a local knowledge base as one capability?

Runnable result:

- local documents can be indexed
- Klara can answer with source cards and citations
- RAG appears as a tool/capability, not as the core loop

Includes:

- local document loader
- metadata sidecars
- chunking
- embedding
- BM25 retrieval
- vector retrieval
- hybrid retrieval
- simple reranking
- context builder
- SourceCard
- Citation
- AnswerFrame

Excludes:

- evidence-heavy multi-step workflow
- unrestricted web research
- RAG optimization benchmark lab

### Chapter 12 - Controlled Agentic RAG

Main question: how does Klara handle evidence-heavy work with runtime-owned
workflow instead of a free agent loop?

Runnable result:

- request is normalized
- search/fetch/evidence/write/verify steps are visible
- insufficient evidence is an explicit outcome

Includes:

- RequestSpec
- EvidenceSearchPlan
- SearchProvider / FetchProvider
- multi-path retrieval
- evidence pack
- source selection
- answer writer
- verifier
- DecisionRecord trace
- old AgentLadder Agentic RAG lessons

Excludes:

- arbitrary tool autonomy
- web-scale crawling
- RL optimization

### Chapter 13 - Research Agent

Main question: how does Klara run bounded research across local knowledge and
web/page reading?

Runnable result:

- Klara can search, fetch, rank, synthesize, and produce a report
- source uncertainty is visible
- contradictions can be called out

Includes:

- web search
- page fetch/read
- WebResearchState
- EvidenceLedger
- search provider abstraction
- final-readiness policy
- source ranking
- evidence table
- contradiction handling
- report generation
- follow-up question handling

Excludes:

- unbounded browsing
- arbitrary external side effects
- post-training

### Chapter 14 - Task System

Main question: how does Klara persist larger goals as ordered work?

Runnable result:

- tasks are written to disk
- dependencies and status are visible
- task records survive process restart

Includes:

- TaskRecord
- task states
- blocked-by dependencies
- claim/complete contract
- task board
- trace events

Excludes:

- team agents
- background execution
- scheduler

### Chapter 15 - Background Work And Scheduler

Main question: how can Klara run bounded work outside the foreground turn?

Runnable result:

- slow jobs run in background
- completion notification is injected into chat
- simple scheduled jobs can fire later

Includes:

- background job runner
- notification queue
- queue processor
- cron-like schedule
- session-only versus durable jobs
- routine profile
- bounded capability set

Excludes:

- worker fleet scaling
- production queue infrastructure
- autonomous task claiming

### Chapter 16 - Subagents, Teams, And Worktrees

Main question: when one context is not enough, how does Klara delegate safely?

Runnable result:

- one-shot subagent can run with clean context
- persistent teammate can communicate through a mailbox
- task/worktree isolation prevents obvious interference

Includes:

- one-shot subagent
- isolated messages
- summary-only return
- persistent teammate
- MessageBus / inbox
- team protocol
- autonomous task claiming
- worktree isolation
- permission bubbling placeholder

Excludes:

- production orchestration fleet
- learned multi-agent routing

### Chapter 17 - MCP And External Tools

Main question: how does Klara connect external tool ecosystems without losing
the same runtime boundaries?

Runnable result:

- one MCP-like external tool source can be connected
- dynamic tools appear in the same tool pool
- external tool calls are traced and guarded

Includes:

- MCP client concept
- server/tool discovery
- adapter boundary
- dynamic tool naming
- external audit events
- allow/deny/ask policy placement
- tool error surfaces

Excludes:

- complete OAuth/resource subscription coverage
- production plugin marketplace

### Chapter 18 - Production Runtime And Eval Bridge

Main question: what changes when Klara must be reliable, and how do traces
become improvement data?

Runnable result:

- local production-shaped run path works
- redacted trace can be exported into an eval dataset
- regression report can be generated

Includes:

- API boundaries
- session storage
- streaming and cancellation
- user/auth boundary as a production concern
- privacy and redaction
- observability
- eval dataset extraction
- gold examples
- scorers/rubrics
- regression report
- final comprehensive Klara freeze

Excludes:

- live policy mutation
- full production deployment
- training jobs

## Advanced Labs

Advanced labs are not regular foundation chapters. They are compact runnable
experiments that use Klara's traces, tools, memory, and RAG surfaces.

### Lab A - Trace Dataset And Evaluation

Question: how do Klara traces become reusable data?

Includes:

- trace normalization
- state/action/outcome records
- train/eval split
- rubric scoring
- regression dashboard artifact

### Lab B - Tiny Pretrain

Question: what is the smallest visible pretraining pipeline?

Includes:

- tokenizer
- tiny transformer
- dataset preparation
- pretraining loop
- loss curves
- simple generation check

### Lab C - Tool-Use SFT

Question: can Klara traces teach a small model tool-use format?

Includes:

- tool-call trace filtering
- supervised examples
- SFT run
- held-out tool-call validation
- failure taxonomy

### Lab D - Preference / DPO

Question: how does post-training improve answer or policy preferences?

Includes:

- preference pairs
- DPO or ORPO-style objective
- small model update
- before/after eval
- safety gate before use

### Lab E - MoE Router

Question: can several small experts behave like a routed system?

Includes:

- expert roles
- router/gating model
- load balancing check
- expert specialization eval
- distillation option

### Lab F - RAG Optimization

Question: how do retrieval choices change recall, faithfulness, and latency?

Includes:

- retrieval benchmark
- chunking ablation
- hybrid/RRF tuning
- query rewrite
- reranking
- multi-hop retrieval
- multimodal/figure-aware extension when available

### Lab G - Memory And RL Policy

Question: can memory and policy improve from experience?

Includes:

- mem0-style memory baseline
- reflection/consolidation
- dream-like offline memory review
- bandit-style tool/retrieval policy
- GRPO/PPO-style toy policy experiment when feasible

## One-Month Execution Plan

Target window: June 16, 2026 through July 15, 2026.

The schedule optimizes for runnable teaching versions, not production
completeness.

### Week 1 - June 16 to June 22

Target chapters: 2 through 6.

Outcome:

- real tool calling
- hooks and trace
- harness/config
- todo planning
- prompt/context assembly

### Week 2 - June 23 to June 29

Target chapters: 7 through 12.

Outcome:

- context compression
- recovery/fallback
- skills
- memory
- RAG tool
- controlled Agentic RAG

### Week 3 - June 30 to July 6

Target chapters: 13 through 18.

Outcome:

- research agent
- task system
- background/scheduler
- subagents/teams/worktrees
- MCP/external tools
- production/eval bridge

### Week 4 - July 7 to July 15

Target labs: A through G plus final freeze.

Outcome:

- trace dataset
- tiny pretrain
- tool-use SFT
- preference/DPO
- MoE router
- RAG optimization
- memory/RL policy experiment
- final documentation, README cleanup, and freeze notes

## Keep / Rebuild / Defer

Keep:

- Klara persona and calm observable identity
- one loop as the runtime center
- chapter/freeze documentation habit
- existing frontend as proof surface
- old RAG contracts around sources, citations, and answer frames
- old Agentic RAG lessons around EvidencePack, verifier, and DecisionRecord

Rebuild:

- generic runtime as `KlaraLoop`
- app assembly as `KlaraHarness`
- concrete tools as capability packages
- RAG as a knowledge tool/service
- trace as the shared backend/UI/eval substrate

Defer:

- early standalone permission chapter
- full user management before production
- production queue scaling
- model training before trace/eval export exists
- advanced memory/RL until foundation memory and traces exist

Drop or archive:

- chapter-specific orchestration inside core
- product-specific ZENO services or naming
- hidden memory behavior before the memory chapter
- UI pages that encode one old chapter as a permanent runtime contract
