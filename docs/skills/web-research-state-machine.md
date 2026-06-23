# Klara Web Research State Machine Skill

## Invocation Contract

Any goal that changes Klara web research must explicitly include:

```text
Use docs/skills/web-research-state-machine.md as the controlling skill.
Keep the goal prompt short. Follow the skill for architecture, trace standards,
test plan, complex-search validation, and forbidden shortcuts.
```

The goal prompt should not restate this whole document. Put the architecture,
state machine, trace contract, validation suite, and forbidden shortcuts here.
The goal only names the branch/chapter target, the work scope, and the required
validation report.

## Problem Statement

Klara's current web weakness is not mainly "bad search." The deeper problem is
that web-backed answers do not yet have a runtime-owned research state.

The basic loop is already correct for simple tool use:

```text
user
-> LLM
-> tool_calls?
   -> tools
   -> observations
   -> next LLM turn
-> no tool_calls = final answer
```

For current-information answers, that is not enough. The runtime needs to know:

- which search results are only candidates
- which pages were fetched
- whether fetched text is relevant and readable
- whether enough independent evidence exists
- whether sources conflict
- whether the model is allowed to finalize
- whether budget is exhausted and uncertainty must be stated

This must be a generic research-control system. Do not solve it with sports
rules, World Cup patches, keyword answer correction, or a hidden
`web_deep_search` agent inside one tool.

## Non-Negotiable Boundaries

Allowed:

- generic evidence readiness policy
- source/candidate ids
- fetched-source quality scoring
- before-final readiness checks
- budget exhaustion with explicit uncertainty
- context compaction for long web observations
- provider limitation reporting
- trace events for decisions and evidence state

Forbidden:

- domain-specific fact rules
- "World Cup" or fixture/result patches
- answer text scanning to correct one topic
- hidden semantic guards that rewrite final answers
- black-box nested search agents that hide the search/fetch trajectory
- hooks that secretly own research state or mutate final answers
- prompt-only fixes without a replayable state/trace contract

## Architecture

Keep `KlaraLoop` as the only agent loop.

Recommended shape:

```text
KlaraLoop
  -> LLM chooses next action
  -> ToolExecutor runs web_search / web_fetch
  -> EvidenceLedger records candidates and fetched sources
  -> WebResearchPolicy evaluates readiness and gaps
  -> prepare_next_turn injects compact research state
  -> before-final policy blocks premature factual answers
```

Concrete web logic belongs outside `src/klara/core`, preferably under
`src/klara/services/web/`. Core may expose only a tiny generic controller
protocol.

Allowed in core:

- generic controller/middleware protocol
- generic before-final decision plumbing
- controller-provided system prompt suffix assembly
- controller-provided next-turn preparation

Not allowed in core:

- web-specific types
- search provider selection
- source ranking
- domain rules
- factual answer correction

## Hooks, Trace, And Training Boundary

The controller decides research state. Tools produce observations. Hooks observe
and persist.

Use hooks for:

- JSONL trace persistence
- API/frontend event projection
- metrics and duration capture
- developer debug surfaces
- optional permission/safety placement

Do not use hooks as a hidden research state machine. A hook may persist
`web_research.state_updated`, but it must not secretly decide source readiness,
mutate model-visible transcripts, patch final answers, or choose domain-specific
facts. Those decisions belong to controller/policy code so they are testable,
replayable, and visible in traces.

Training-grade trace should flow like this:

```text
tool/controller/core fact
-> KlaraLoop event / controller event
-> HookManager fanout
-> JsonlTraceHook canonical trace
-> API projector / Developer debug projection
-> optional future training export
```

If the API run event projector ignores custom web events, update the projector.
Do not move control decisions into the projector just to make UI display easier.

## Training-Grade Trajectory Contract

Trace must support later eval, SFT, preference data, and RL-style trajectory
conversion. It is not enough for trace to be human-readable debug text.

Every trajectory should be reconstructable as:

```text
state -> action -> observation -> policy decision -> next state -> final answer
```

Required properties:

- stable `run_id`, `turn_index`, event ids, tool call ids, candidate ids, and
  source ids
- deterministic event order
- timestamps for run, turn, LLM call, tool call, fetch, decision, and final
- model name, token usage when available, latency, and selected tools
- JSON-compatible observations that can be parsed from JSONL
- redacted but auditable tool arguments and observations
- separate payload shapes for search candidates and fetched sources
- explicit final-readiness events with `allowed|blocked|budget_exhausted`
- generic reason codes such as `no_fetched_sources`, `low_quality_sources`,
  `need_independent_sources`, `budget_exhausted`
- prompt-visible compact research state reconstructable from trace events
- no reliance on UI prose as the only record of what happened

Recommended event families:

```text
web_research.started
web_research.state_updated
web_search.started
web_search.completed
web_fetch.started
web_fetch.completed
evidence.candidate_recorded
evidence.source_recorded
evidence.readiness_evaluated
final_answer.blocked
final_answer.allowed
context.compacted
```

For future training exports:

- `state` = model-visible messages plus compact research state
- `action` = model tool call or final-answer attempt
- `observation` = tool result or controller feedback
- `policy_decision` = readiness result and budget state
- `reward/eval signal` = later human/eval labels, factuality, citation quality,
  source coverage, latency, cost

## State Machine

Use a generic state machine:

```text
IDLE
-> WEB_REQUIRED
-> PLAN_QUERIES
-> SEARCHING
-> RANK_CANDIDATES
-> FETCHING
-> EXTRACTING
-> VERIFYING
-> NEED_MORE_SEARCH | NEED_MORE_FETCH | READY_TO_ANSWER | BUDGET_EXHAUSTED
-> FINAL_ALLOWED | FINAL_BLOCKED
```

Mapping to the existing loop:

```text
LLM turn            = PLAN_QUERIES / choose next actions
web_search tool     = SEARCHING
web_fetch tool      = FETCHING + EXTRACTING
prepare_next_turn   = RANK_CANDIDATES + VERIFYING + compact state injection
no tool_calls       = candidate final answer
before-final policy = FINAL_ALLOWED / FINAL_BLOCKED
```

The model still chooses tool calls. Runtime only decides whether evidence state
is ready enough to accept a final answer.

## Research Modes And Budgets

Start with three modes:

```text
off    - no web research state is active
quick  - one or a few fetched sources may be enough
deep   - multiple independent sources and coverage checks are needed
```

Activation may be simple and capability-level:

- explicit search/current/latest/today/news/scores/schedule/version/price
  requests -> `quick`
- research/compare/comprehensive/report/multi-source requests -> `deep`
- ordinary stable conversation -> `off`

This classifier must not encode domain truth.

Default quick budget:

```text
max_search_calls = 3
max_fetch_calls = 5
min_fetched_sources = 1
min_independent_domains = 1
```

Default deep budget:

```text
max_search_calls = 8
max_fetch_calls = 16
min_fetched_sources = 3
min_independent_domains = 2
```

Budget exhaustion is a controlled stop:

```text
Search budget exhausted.
Write the best answer from fetched evidence only.
State what remains uncertain.
Do not invent unsupported facts.
```

## Core Data Contracts

### WebResearchState

```python
from dataclasses import dataclass, field
from typing import Literal

ResearchMode = Literal["off", "quick", "deep"]
ResearchStatus = Literal[
    "idle",
    "web_required",
    "searching",
    "fetching",
    "verifying",
    "need_more_search",
    "need_more_fetch",
    "ready",
    "budget_exhausted",
]


@dataclass
class WebResearchBudget:
    max_search_calls: int = 6
    max_fetch_calls: int = 12
    min_fetched_sources: int = 2
    min_independent_domains: int = 2
    max_candidate_results: int = 40


@dataclass
class WebResearchState:
    active: bool = False
    mode: ResearchMode = "off"
    status: ResearchStatus = "idle"
    goal: str = ""
    now_utc: str = ""
    user_timezone: str = ""
    searched_queries: list[str] = field(default_factory=list)
    fetched_source_ids: list[str] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    runtime_feedback: str = ""
    budget: WebResearchBudget = field(default_factory=WebResearchBudget)
```

### EvidenceLedger

```python
from dataclasses import dataclass, field


@dataclass
class SearchCandidate:
    candidate_id: str
    search_id: str
    query: str
    title: str
    url: str
    canonical_url: str
    snippet: str
    provider: str
    rank: int
    published_at: str | None = None
    freshness_enforced: bool = False
    source_type: str = "unknown"
    fetched: bool = False


@dataclass
class SourceRecord:
    source_id: str
    candidate_id: str | None
    url: str
    final_url: str
    title: str
    fetched_at: str
    text_preview: str
    relevant_snippets: list[str]
    extraction_quality: float
    no_relevant_terms_found: bool
    trust: str = "untrusted_external_content"


@dataclass
class EvidenceLedger:
    candidates: dict[str, SearchCandidate] = field(default_factory=dict)
    sources: dict[str, SourceRecord] = field(default_factory=dict)
```

Minimum ledger behavior:

- record candidates from `web_search`
- record fetched sources from `web_fetch`
- mark candidates as fetched by candidate id or canonical URL
- compute fetched source count
- compute independent domain count
- return top unfetched candidates
- build compact prompt summaries

Do not add claim extraction in V1. Source ids, snippets, quality, and domain
coverage are enough for the first stable research loop.

## Search Provider Boundary

`web_search` is candidate discovery. Search snippets are not final evidence.

Provider abstraction should support:

```text
query
count
freshness / date_after / date_before
language / country
allowed_domains / blocked_domains
search_depth
require_freshness_enforced
```

Provider routing rules:

- prefer configured account-backed providers when available
- keep DuckDuckGo Lite as no-key fallback
- if `require_freshness_enforced=True`, do not silently fall back to a provider
  that cannot enforce freshness
- surface provider limitations in observations

Candidate future providers:

- Tavily for agentic search depth and raw/cleaned content
- Brave for freshness, country, language, and result context
- Exa for semantic search and content/highlight retrieval
- DuckDuckGo Lite for no-key fallback and teaching

## Web Search V2 Contract

Input additions:

```text
count: 1..20
freshness: day | week | month | year | any
date_after
date_before
language
country
allowed_domains
blocked_domains
search_depth: basic | advanced
require_freshness_enforced
```

Output shape:

```json
{
  "observation_kind": "web_search_candidates",
  "evidence_status": "candidate_snippets_only",
  "search_id": "search_001",
  "query": "...",
  "provider": "tavily",
  "freshness_enforced": true,
  "searched_at": "2026-06-23T15:12:00Z",
  "result_count": 10,
  "results": [
    {
      "candidate_id": "cand_001",
      "rank": 1,
      "title": "...",
      "url": "...",
      "canonical_url": "...",
      "snippet": "...",
      "published_at": "...",
      "source_type": "official|news|docs|forum|aggregator|unknown",
      "must_fetch_before_citing": true
    }
  ],
  "trust": "untrusted_external_content"
}
```

Important:

- preserve provider rank unless a separate ranking service is added
- do not rank by domain-specific policy inside the tool
- do not put few-shot routing examples in the schema
- do not cite search-only candidates in final answers

## Web Fetch V2 Contract

`web_fetch` produces evidence records.

Input additions:

```text
candidate_id
source_id
extract_mode: plain | relevant_snippets | summary_snippets
query_terms
max_chars
```

Output shape:

```json
{
  "observation_kind": "web_fetched_source",
  "source_id": "src_001",
  "candidate_id": "cand_001",
  "url": "...",
  "final_url": "...",
  "status": 200,
  "content_type": "text/html",
  "title": "...",
  "text": "...",
  "text_length": 8421,
  "truncated": false,
  "extract_mode": "relevant_snippets",
  "query_terms": ["..."],
  "no_relevant_terms_found": false,
  "extraction_quality": {
    "score": 0.81,
    "looks_like_js_shell": false,
    "has_title": true,
    "has_relevant_terms": true,
    "text_length": 8421
  },
  "fetched_at": "2026-06-23T15:13:00Z",
  "trust": "untrusted_external_content"
}
```

Quality scoring V1:

- positive signal for HTTP 2xx
- positive signal for non-empty title
- positive signal for enough readable text
- positive signal when query terms are found
- lower score for JavaScript shell/navigation pages
- expose `no_relevant_terms_found` for policy decisions

## WebResearchPolicy

Decision contract:

```python
from dataclasses import dataclass


@dataclass(frozen=True)
class ResearchDecision:
    ready: bool
    status: str
    gaps: list[str]
    next_hint: str
```

V1 checks:

- no fetched sources -> need more fetch
- too few independent domains for deep mode -> need more search or fetch
- all fetched pages are low quality -> need more search
- fetched pages have no relevant terms -> need more search
- budget exhausted -> allow uncertain final answer
- otherwise -> ready

The next model turn receives `gaps` and `next_hint`, then the model chooses the
next `web_search` or `web_fetch` call.

## Generic Loop Controller Protocol

Use a generic controller rather than hardcoding web behavior into the loop:

```python
from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FinalAnswerDecision:
    allowed: bool = True
    reason: str = ""
    feedback: str = ""


class LoopController(Protocol):
    def on_run_start(self, *, user_input: str, run_id: str) -> None:
        ...

    def system_prompt_suffix(self) -> str:
        ...

    def on_tool_results(self, *, results: tuple[ToolResult, ...]) -> None:
        ...

    def before_final_answer(self, *, content: str) -> FinalAnswerDecision:
        ...

    def prepare_next_turn(self, messages: list[KlaraMessage]) -> list[KlaraMessage]:
        ...
```

Loop integration rules:

- call `on_run_start` once after `run_id` exists
- append controller `system_prompt_suffix()` to the base system prompt per turn
- call `on_tool_results` after tool execution
- call controller `prepare_next_turn` where the identity step currently lives
- call `before_final_answer` before accepting a no-tool assistant answer
- if blocked and budget remains, do not append the premature assistant answer
- emit `final_answer.blocked`
- continue to the next model turn with controller feedback in the prompt suffix

## WebResearchController

The concrete web controller owns:

- `WebResearchState`
- `EvidenceLedger`
- activation mode
- tool observation parsing
- readiness evaluation
- compact prompt suffix generation
- premature final blocking
- budget-exhausted final allowance

Prompt suffix shape:

```text
<web_research_runtime>
status: need_more_fetch
mode: quick
goal: summarize the latest public information about ...
now_utc: 2026-06-23T15:20:00Z
user_timezone: Asia/Shanghai

rules:
- Search result snippets are candidate leads, not final evidence.
- Use web_fetch on relevant candidate URLs before factual claims.
- Prefer fetched sources over search snippets.
- Do not cite or rely on a source that was only seen as a search candidate.
- If evidence is incomplete and budget remains, continue searching/fetching.
- If budget is exhausted, answer from fetched evidence and mark uncertainty.

progress:
- searched_queries: [...]
- fetched_source_count: 0
- independent_domain_count: 0

remaining_gaps:
- Need at least one fetched source.

next_hint:
Fetch the most relevant unfetched candidate before answering.

top_unfetched_candidates:
- cand_001 | title | domain | snippet preview

recent_fetched_sources:
- src_001 | title | final_url | quality
</web_research_runtime>
```

Keep the suffix compact, ideally below 1500 to 2500 characters.

## Context Compaction

Deep search will overflow context unless web observations are compacted.

Model-visible next-turn context should keep:

```text
recent web_fetch -> fuller observation
older web_fetch  -> source id + title + final_url + fetched_at + snippets + quality
web_search       -> search id + top candidates + fetched markers
```

Compacted fetch observation shape:

```json
{
  "observation_kind": "web_fetched_source_compacted",
  "source_id": "src_001",
  "title": "...",
  "final_url": "...",
  "fetched_at": "...",
  "relevant_snippets": ["...", "..."],
  "extraction_quality": 0.81
}
```

Do not overwrite raw stored messages or raw traces. Compaction only changes the
model-visible next-turn transcript.

## Why Not A Black-Box `web_deep_search` Tool

Avoid:

```text
LLM calls web_deep_search(question)
-> hidden search/fetch/verify loop runs inside the tool
-> tool returns a finished report
-> LLM rewrites it
```

Problems:

- the main trace cannot show each search/fetch step clearly
- hooks and permission placement are bypassed
- the model cannot adjust direction from intermediate observations
- citations and evidence ids are harder to align with frontend debug
- future memory, RAG, eval, approval, and training now have two loops to govern

Primitive tools plus a research controller are more teachable and more aligned
with Klara's runtime architecture.

## Implementation Test Plan

Loop/controller:

- current-information request activates web research state
- stable non-web chat leaves web research off
- search-only observations block factual final answer
- blocked final answer does not append premature assistant content
- blocked final answer emits a trace event
- max turn/tool budget produces uncertain finalization
- controller suffix is appended per turn, not written to history

Search:

- `web_search` emits `candidate_id`, `search_id`, and
  `must_fetch_before_citing`
- provider rank is preserved
- DuckDuckGo Lite marks `freshness_enforced=false`
- `require_freshness_enforced=true` does not silently fall back to DuckDuckGo
- date/freshness hints are surfaced in observations

Fetch:

- `web_fetch` emits `source_id`, `candidate_id`, text length, and quality
- relevant snippets are extracted when terms match
- `no_relevant_terms_found=true` lowers readiness
- JavaScript shell pages lower quality
- SSRF and local-network safety still pass

Policy:

- quick mode requires at least one relevant fetched source
- deep mode requires multiple sources and independent domains
- low-quality sources trigger `need_more_search`
- budget exhaustion permits final answer with uncertainty
- final answers do not cite search-only candidates

Context:

- old web fetch observations are compacted
- compacted observations preserve source ids and snippets
- raw stored messages are not overwritten by compaction
- trace/debug still shows raw payloads in developer-only surfaces

## Complex Search Validation Suite

Unit tests are not enough. The implementation goal is complete only after
running complex searches through the local API/UI and auditing traces.

Use prompts that stress different research shapes:

- latest schedule/results: old model memory is likely wrong
- broad current summary: requires multiple fetched sources
- specific follow-up: extends evidence without relying on stale snippets
- conflicting sources: requires conflict-aware synthesis
- official-source miss: official page is empty/navigation; continue elsewhere
- software/current docs: freshness and provenance matter
- comparison/report query: requires independent source coverage

Minimum manual prompts:

```text
最近世界杯怎么样了？给我按比赛总结、比分、精彩评论、球员表现整理。

给我详细的世界杯最新赛程，优先使用最新可访问来源；如果官方页为空，继续找其他可靠来源。

找一下 Python / React / OpenAI SDK 的最新重要变化，要求列来源并说明哪些信息来自哪个页面。

比较两个最近的 AI agent / browser-use / coding-agent 项目，给出来源、差异、风险和结论。

找一个当前新闻事件的多来源总结；如果来源冲突，明确指出冲突点。
```

For every prompt, capture `run_id` and inspect `data/app/run_events.jsonl` or
`data/traces/runs.jsonl`.

Trace must show:

- at least one `web_search` for current-information requests
- search results recorded as candidates, not final evidence
- `web_fetch` records with source ids, text length, quality, and source/candidate
  linkage
- low-quality or empty pages lowering readiness
- generic final-readiness decision before no-tool finalization
- `final_answer.blocked` or equivalent when evidence is insufficient and budget
  remains
- compacted model-visible web context after multiple fetched pages
- no domain-specific rules in trace payloads, prompts, or code paths

Required final trace table:

```text
prompt | run_id | search_count | fetch_count | good_sources | blocked_finals | final_status | notes
```

If a complex prompt still answers from model memory, search snippets only, or a
single low-quality page, the goal is not complete even if all unit tests pass.

## Chapter Placement

Do not fold this into Chapter 3. Chapter 3 is hooks, trace, activity, and debug
boundaries.

Recommended route:

- Chapter 7 Context Compression: compact web observations.
- Chapter 12 Controlled Agentic RAG: evidence readiness and verifier patterns.
- Chapter 13 Research Agent: full web research state machine, provider
  abstraction, evidence ledger, final readiness, report synthesis.
- Advanced Lab F RAG Optimization: evaluate retrieval/search providers.

## Minimal Goal Prompt

Use this instead of pasting the full architecture into a goal:

```text
Implement Klara Web Research V2 on the current chapter branch.

Use docs/skills/web-research-state-machine.md as the controlling skill. Follow
that skill for architecture, trace/post-training standards, data contracts,
forbidden shortcuts, tests, complex-search validation, and final report format.

Scope:
- implement the generic loop/controller integration required by the skill
- upgrade web_search/web_fetch contracts required by the skill
- add EvidenceLedger, WebResearchState, WebResearchPolicy, and context
  compaction
- keep the solution generic; do not add domain guards, answer patches, or a
  black-box web_deep_search tool
- preserve existing thinking/activity/debug behavior except where trace
  projection is required by the skill

Validation:
- run the unit/integration tests required by the skill
- run the skill's complex-search validation prompts through the local app
- inspect JSONL traces by run_id
- produce the required trace table and concise final report

Stop condition:
The goal is complete only when automated tests pass and the complex-search trace
table satisfies the skill's training-grade trajectory requirements.
```
