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
  use Klara traces and runtime surfaces to study evaluation, trajectory
  distillation, tiny-model training, sparse MoE, low precision, RAG, memory,
  and RL optimization
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
- The UI/window is not a standalone chapter. For the current algorithm path,
  proof comes from CLI output, versioned JSON/JSONL artifacts, tests, and
  Markdown reports. Existing frontend code may remain, but new frontend work is
  not required for an algorithm chapter or lab to be complete.

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
- each material answer claim is linked to supporting evidence or marked as
  unsupported, contradicted, or still uncertain
- insufficient evidence is an explicit outcome

Includes:

- RequestSpec
- EvidenceSearchPlan
- SearchProvider / FetchProvider
- multi-path retrieval
- evidence pack
- source selection
- `Claim` and `ClaimEvidenceLink` contracts
- source provenance, content hash, and retrieval timestamp
- answer writer
- claim-level verifier with `supported | contradicted | insufficient` outcomes
- explicit abstention when required claims do not pass the evidence gate
- DecisionRecord trace
- old AgentLadder Agentic RAG lessons

Excludes:

- arbitrary tool autonomy
- web-scale crawling
- domain-specific truth patches or hidden answer rewriting
- hidden chain-of-thought collection
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
- redacted trace can be exported into a versioned trajectory dataset
- a CLI evaluator can compare a baseline and candidate run
- JSON and Markdown regression reports can be generated without a frontend

Includes:

- API boundaries
- session storage
- streaming and cancellation
- user/auth boundary as a production concern
- privacy and redaction
- observability
- normalized `state -> action -> observation -> policy decision -> outcome`
  trajectory extraction
- schema version, source-run lineage, content hashes, and deterministic splits
- gold examples
- evidence-control, tool-use, quality, latency, token, and cost scorers
- machine-readable JSON plus human-readable Markdown regression reports
- final comprehensive Klara freeze

Excludes:

- live policy mutation
- full production deployment
- training jobs
- an evaluation dashboard or other frontend dependency

## Advanced Labs

Advanced labs are not regular foundation chapters. They are compact runnable
experiments that use Klara's traces, tools, memory, and RAG surfaces.
They keep the same teaching discipline as chapters: one question, one runnable
result, an explicit baseline, versioned data, named metrics, reproducible
artifacts, and a clear exclusion boundary.

### Lab A - Trace Dataset And Evaluation

Question: how do Klara traces become reusable evidence-control and tool-use
evaluation data?

Runnable result:

- one command exports redacted JSONL trajectories deterministically
- one command scores a baseline or compares baseline versus candidate
- the run produces versioned JSON and Markdown reports with per-case failures

Includes:

- trace normalization
- `state/action/observation/policy_decision/outcome` records
- schema version, dataset manifest, hashes, lineage, and leakage-safe splits
- gold labels and deterministic rubric inputs
- tool decision and argument-validity metrics
- Evidence Selection Precision / Recall / F1
- Citation Precision / Recall
- Claim Support Rate, Contradiction Recall, and Abstention Accuracy
- latency, token, and cost summaries
- regression thresholds suitable for CI

Excludes:

- raw prompts, secrets, provider-hidden reasoning, or hidden chain-of-thought
- a required web dashboard

### Lab B - Tiny Pretrain

Question: what is the smallest visible pretraining pipeline?

Runnable result:

- a small decoder-only Transformer written in this repository trains from
  random initialization
- a checkpoint, loss curve, run manifest, and deterministic generation sample
  are produced by documented commands

Includes:

- tokenizer
- custom embeddings, causal self-attention, MLP, normalization, and LM head
- dataset preparation
- pretraining loop
- FP32 dense baseline and seeded run manifest
- loss curves and checkpoint save/load
- simple generation check

Excludes:

- wrapping a pretrained large model and calling it a model built from scratch
- claims about model quality without a held-out baseline

### Lab C - Tool-Use SFT And Trajectory Distillation

Question: can filtered trajectories from several teacher LLMs teach a small
student model tool-use and evidence-control behavior?

Runnable result:

- configured teacher adapters generate the same public trajectory schema
- invalid, unsafe, unsupported, and duplicate trajectories are filtered out
- a dense student is fine-tuned and compared with its pre-SFT baseline on a
  held-out set using Lab A metrics

Includes:

- OpenAI-compatible teacher adapters, including configured Qwen and DeepSeek
- teacher and dataset manifests with model id, prompt version, seed, and hashes
- public `state/action/observation/final` trajectory normalization
- tool-schema, evidence-support, redaction, deduplication, and quality filters
- hard-label SFT as the reproducible distillation baseline
- optional logit/KL distillation only when a teacher actually exposes logits
- held-out tool-use and evidence-control validation
- failure taxonomy

Excludes:

- collecting or training on provider-hidden reasoning or chain-of-thought
- training on the evaluation split
- comparing teachers and students without the same task set and scorer version

### Lab D - Preference / DPO

Question: how does post-training improve answer or policy preferences?

Runnable result:

- a versioned preference dataset trains one small-model update
- before/after results are reported on the same held-out evaluation set

Includes:

- preference pairs
- DPO or ORPO-style objective
- small model update
- before/after eval
- safety gate before use

Excludes:

- replacing evidence verification with answer-style preference
- deploying an unverified learned policy into the runtime

### Lab E - Tiny Sparse MoE

Question: can a small Transformer replace its dense feed-forward block with a
real token-level sparse mixture of experts and beat a controlled dense baseline?

Runnable result:

- the custom tiny decoder can switch between dense FFN and sparse MoE blocks
- a four-expert, top-2 routed model trains end to end
- one report compares quality, active parameters/FLOPs, throughput, routing
  balance, and expert specialization against the dense baseline

Includes:

- custom expert MLPs, router logits, top-k dispatch, weighted combine, and
  shape/gradient tests
- four experts with top-2 token routing as the primary configuration
- load-balancing auxiliary loss and router z-loss
- expert utilization, router entropy, token drop/capacity, and specialization
  metrics
- parameter-matched or active-FLOP-matched dense baseline
- optional trajectory-distilled MoE student using Lab C data

Excludes:

- four prompt personas or API calls presented as a token-level MoE model
- distributed expert parallelism or production fused kernels

### Lab F - RAG Optimization

Question: how do retrieval choices change recall, faithfulness, and latency?

Runnable result:

- one benchmark command compares retrieval configurations on a frozen corpus
  and query set
- recall, evidence support, citation quality, latency, and cost are reported

Includes:

- retrieval benchmark
- chunking ablation
- hybrid/RRF tuning
- query rewrite
- reranking
- multi-hop retrieval
- multimodal/figure-aware extension when available

Excludes:

- tuning on the held-out test queries
- reporting answer quality without retrieval and evidence metrics

### Lab G - Memory And RL Policy

Question: can memory and policy improve from experience?

Runnable result:

- one offline experiment compares a fixed baseline with a learned or adaptive
  memory/tool policy under a bounded task set

Includes:

- mem0-style memory baseline
- reflection/consolidation
- dream-like offline memory review
- bandit-style tool/retrieval policy
- GRPO/PPO-style toy policy experiment when feasible

Excludes:

- online self-modification of the production runtime
- an RL claim without a frozen baseline and held-out task set

### Lab H - FP16 And FP4 Low-Precision MoE

Question: what quality, size, memory, and throughput trade-offs appear when the
tiny dense and MoE models move from FP32 to FP16 and a reproducible FP4 path?

Runnable result:

- the same checkpoint can be evaluated in FP32 and FP16
- MoE expert weights can be quantized to a documented FP4 E2M1 block-scaled
  representation and packed two values per byte
- a report compares quality, model bytes, peak memory, latency, and throughput
  across FP32, FP16, and FP4-weight/FP16-activation (`W4A16`) runs

Includes:

- FP16 automatic mixed precision and gradient scaling where hardware supports it
- reference FP4 E2M1 encode/decode, block scales, nibble packing, and round-trip
  tests
- post-training weight quantization as the baseline
- optional fake-quantization/QAT experiment when the baseline loses too much
  quality
- dense-versus-MoE and precision ablations using the same evaluation manifest
- a clearly separated optional native-FP4 backend when supported hardware and
  libraries are actually available

Excludes:

- claiming native FP4 arithmetic or speed from an emulated W4A16 path
- writing a production CUDA/Triton fused kernel in the one-week scope
- comparing precision modes with different data, seeds, or scorer versions

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

Target labs: A through H plus final freeze.

Outcome:

- trace dataset
- tiny pretrain
- tool-use SFT and trajectory distillation
- preference/DPO
- tiny sparse MoE
- FP16 and FP4 low-precision evaluation
- RAG optimization
- memory/RL policy experiment
- final documentation, README cleanup, and freeze notes

## Current One-Week Algorithm Completion Overlay

Target window: August 11, 2026 through August 17, 2026.

This is a narrow implementation overlay on the existing roadmap, not a new
chapter sequence. It does not mark Chapters 4 through 18 complete. Algorithm
artifacts are incubated in their canonical Lab locations and later integrated
when the matching foundation chapter is built.

No new frontend is part of this window. The required proof surfaces are CLI
commands, tests, JSON/JSONL datasets, checkpoints, static plots where useful,
and Markdown reports.

### Day 1 - Trace And Reproducibility Contract

Canonical slots: Chapter 3, Chapter 18, and Lab A.

- freeze the latest Chapter 3 public/private trace boundary
- define the versioned trajectory, run-manifest, redaction, and lineage schemas
- add deterministic export and dataset-validation commands

Exit gate: a fixture run exports stable, redacted JSONL and passes schema,
ordering, id-linkage, and leakage checks.

### Day 2 - Evidence Control And Evaluation

Canonical slots: Chapters 12 and 13 plus Lab A.

- implement the smallest `Claim`, `EvidenceRecord`, `ClaimEvidenceLink`,
  verifier, contradiction, and abstention contracts outside `klara.core`
- create a small gold set covering supported, contradicted, insufficient,
  stale, and irrelevant evidence
- implement the evidence, citation, contradiction, and abstention metrics

Exit gate: the evidence controller cannot finalize required unsupported claims,
and the evaluator produces JSON plus Markdown results from the gold set.

### Day 3 - Tiny Dense Baseline

Canonical slot: Lab B.

- build the custom decoder-only Transformer and training loop
- run a seeded FP32 pretraining baseline
- save the model config, data hash, checkpoint, loss curve, and generation sample

Exit gate: a clean command can reproduce training, checkpoint reload, held-out
loss, and deterministic sample generation.

### Day 4 - Multi-Teacher Trajectory Distillation

Canonical slot: Lab C.

- generate public trajectories from configured Qwen/DeepSeek/OpenAI-compatible
  teachers using one task manifest
- filter by schema validity, tool validity, evidence support, redaction, and
  deduplication
- fine-tune the dense student and compare it with the Day 3 baseline

Exit gate: the student evaluation uses a held-out split and the same frozen Lab
A scorer version; no provider-hidden reasoning enters the dataset.

### Day 5 - Tiny Sparse MoE

Canonical slot: Lab E.

- replace the dense FFN with the four-expert, top-2 sparse MoE block
- add routing, auxiliary-loss, utilization, entropy, capacity, and gradient tests
- train against a controlled dense baseline

Exit gate: all experts receive traffic, routing does not collapse, checkpoint
reload is stable, and the dense/MoE comparison uses the same data and budget.

### Day 6 - FP16 And FP4

Canonical slot: Lab H.

- run supported FP16 AMP training/evaluation
- implement and test FP4 E2M1 block quantization plus packed storage
- evaluate the primary W4A16 path on dense and MoE checkpoints

Exit gate: the report separates real FP16 execution, FP4 storage/quantization,
and any emulated compute path; it does not claim unsupported native FP4 speed.

### Day 7 - End-To-End Gate And Freeze

Canonical slots: Chapter 18 and Labs A, C, E, and H.

- run the evidence-control, distillation, dense/MoE, and precision matrix
- produce the final JSON/Markdown comparison and failure taxonomy
- verify clean-setup commands, tests, manifests, hashes, checkpoints, and docs
- write freeze notes stating exactly what is implemented, measured, and deferred

Exit gate: every reported number links to a run manifest and artifact; every
required command runs without a frontend; unsupported or unmeasured claims are
explicitly excluded from the freeze.

### One-Week Definition Of Done

| Workstream | Canonical home | Required artifact | Acceptance gate |
| --- | --- | --- | --- |
| Evidence control | Chapters 12-13 | contracts, verifier, gold cases, decision trace | unsupported required claims block or abstain |
| Trace/evaluation | Chapter 18 + Lab A | versioned JSONL, scorer CLI, JSON/Markdown report | deterministic export and regression thresholds |
| Distillation | Lab C | teacher manifest, filtered dataset, student checkpoint | held-out improvement reported against dense baseline |
| Tiny MoE | Lab E | custom 4-expert top-2 model and routing report | no collapse; fair dense/MoE comparison |
| FP16/FP4 | Lab H | FP16 run, FP4 codec/packed weights, ablation report | precision semantics and hardware path are truthful |

## Keep / Rebuild / Defer

Keep:

- Klara persona and calm observable identity
- one loop as the runtime center
- chapter/freeze documentation habit
- existing frontend code where it already works, without making new frontend
  work a dependency of the algorithm completion path
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
- native FP4 kernels and distributed expert parallelism until the reference
  low-precision and single-device MoE baselines are measured

Drop or archive:

- chapter-specific orchestration inside core
- product-specific ZENO services or naming
- hidden memory behavior before the memory chapter
- UI pages that encode one old chapter as a permanent runtime contract
