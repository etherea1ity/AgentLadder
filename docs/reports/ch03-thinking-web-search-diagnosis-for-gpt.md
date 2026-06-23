# Klara Chapter 3 Thinking / Web Search Diagnosis for GPT Pro

This report is written for a cloud reviewer that can inspect the public GitHub repository but cannot access local JSONL trace files unless they are quoted here.

Repository: https://github.com/etherea1ity/AgentLadder

Branch to inspect: `chapter-3-hooks-and-trace`

Commit analyzed locally: `183ba0f413f2f1c04d9b8b88cfbc13e53c290f45`

Commit title: `Stabilize web research before final answers`

Local workspace used for trace extraction: `C:\Users\brainclos_032\Desktop\AgentLadder`

Date of diagnosis: 2026-06-23, Asia/Shanghai

## What GPT Pro Should Do With This Report

Please analyze the GitHub branch above and use this report as the local trace artifact. The main question is not whether Klara can call `web_search`; it can. The question is why the product experience is still poor for current-events research and why the Thinking / Activity UI does not reflect the real multi-step work.

Focus on these two product surfaces:

1. Web research quality
   - Search query planning
   - Source ranking and source trust
   - Freshness handling
   - Fetch strategy
   - Evidence readiness
   - Claim-level grounding
   - Final answer gating

2. Thinking / Activity display
   - Live preamble
   - Provider reasoning
   - Narrator-generated Klara activity
   - Developer debug separation
   - Why the drawer often contains only one generic preamble
   - Whether runtime facts are being converted into useful public activity

Do not treat this as a request to add a keyword router or hardcoded sports rules. Klara should remain a general agent runtime. The desired direction is a general research state machine and evidence contract, not a World Cup patch.

## User-Observed Bad Outputs

These two examples were copied from the UI. Their original raw JSONL traces are not currently available in the local data folder because local conversation history was cleared before this report was created. Treat them as user-provided product evidence, not raw trace evidence.

### Bad Output A

User:

```text
帮我搜一下世界杯最新赛事
```

Klara:

```text
根据实时数据，2026年世界杯今日赛果如下：

球队C vs 球队D：1 : 1（已结束）
球队E vs 球队F：0 : 2（已结束）
球队G vs 球队H：3 : 2（已结束）
目前正在进行的焦点比赛是：

球队A vs 球队B：2 : 1（进行中，第67分钟），上半区对决，控球优势明显，反击制造威胁。
来源：https://zh-cn-wc26scores.com/live
```

UI metadata:

```text
Developer debug - 85 events - 3 tools
Trace saved
```

Why this matters:

- The answer uses placeholder team names: `球队A`, `球队B`, `球队C`, etc.
- It presents fake-looking live score details and commentary.
- It cites a single suspicious source.
- If this came from a tool result, the final-answer layer did not validate that team names and scores were grounded.
- If this came from the model, the final-answer layer allowed hallucinated current-event content despite the topic requiring fresh evidence.

### Bad Output B

User:

```text
什么ab啊？我连国家都不知道，你这不开玩笑吗？
现在世界杯的所有已经踢完的赛程和即将开始的都列举一下
```

Klara:

```text
好的，根据最新信息，2026年世界杯目前（6月23日）已结束和即将开始的赛程如下：

已结束比赛（6月23日）
小组 I：挪威 3 : 2 塞内加尔（新泽西东卢瑟福）
小组 J：约旦 vs 阿尔及利亚（圣克拉拉）
小组 K：葡萄牙 vs 乌兹别克斯坦（休斯顿）
小组 L：英格兰 vs 加纳（福克斯伯勒）
小组 L：巴拿马 vs 克罗地亚（多伦多）

即将开始比赛（6月24日）
小组 K：哥伦比亚 vs 刚果(金)（瓜达拉哈拉，20:00）
小组 B：瑞士 vs 加拿大（温哥华，12:00）
小组 B：波黑 vs 卡塔尔（西雅图，18:00）
小组 C：苏格兰 vs 巴西（迈阿密，18:00）
小组 C：摩洛哥 vs 海地（亚特兰大，18:00）

来源：https://fifawatch.com/zh/schedule/
```

UI metadata:

```text
Developer debug - 266 events - 10 tools
Trace saved
```

Why this matters:

- The answer labels a section as `已结束比赛`, but several rows have no score, only `vs`.
- It cites one source for many claims.
- It likely performed more work than Bad Output A, but the final result is still not claim-grounded.
- The UI `Thought for 1m 18s` does not explain what happened during the 10 tool calls.

## Local Trace Export

The local JSONL history currently contains two runs after a local history cleanup. Only the second run is a meaningful web-research reproduction.

### Local Run 1: Encoding-Corrupted Probe

Run id: `run_d793ea08845d4ddd9059850fc3212756`

Model: `qwen/qwen-flash`

User prompt stored in JSONL:

```text
??ab???????????????????????????????
```

Final answer:

```text
看起来你可能不小心输入了一些乱码。要不要重新整理一下问题，克拉拉陪你一起解决？
```

Event counts:

```text
run_created: 1
thinking_started: 1
thinking_summary_started: 1
activity_fact_recorded: 4
thinking_preamble_started: 1
hook_placement_started: 2
hook_placement_completed: 2
llm_call_started: 1
llm_call_completed: 1
final_answer.allowed: 1
narrator_started: 1
thinking_preamble_failed: 1
narrator_rejected: 1
thinking_summary_completed: 1
answer_streaming_started: 1
answer_delta: 1
run_completed: 1
```

Interpretation:

- This run is not a reliable product reproduction because the Chinese prompt was corrupted by a PowerShell / terminal encoding path used during testing.
- It is still useful as a warning: if the backend receives corrupted Chinese text, web research classification turns off and no tools are called.

### Local Run 2: World Cup Schedule Reproduction

Run id: `run_1c46b3aea8374b2c8961695bb7f15493`

Model: `qwen/qwen-flash`

User prompt:

```text
现在世界杯赛程怎么样？给我最新的已经结束和即将开始的比赛。
```

Final answer excerpt:

```text
根据最新的赛程与比赛结果，以下是2026年世界杯目前已结束和即将开始的比赛信息（北京时间）：

已结束的比赛（最近几场）

- 6月21日 周日
  - 荷兰 5 - 1 瑞典（小组赛第2轮）
  - 德国 2 - 1 科特迪瓦（小组赛第2轮）
  - 厄瓜多尔 0 - 0 库拉索（小组赛第2轮）
  - 突尼斯 0 - 4 日本（小组赛第2轮）

- 6月20日 周六
  - 美国 2 - 0 澳大利亚（小组赛第2轮）
  - 苏格兰 0 - 1 摩洛哥（小组赛第2轮）
  - 巴西 3 - 0 海地（小组赛第2轮）
  - 土耳其 0 - 1 巴拉圭（小组赛第2轮）

- 6月19日 周五
  - 捷克 1 - 1 南非（小组赛第2轮）
  - 瑞士 4 - 1 波黑（小组赛第2轮）
  - 加拿大 6 - 0 卡塔尔（小组赛第2轮）
  - 墨西哥 1 - 0 韩国（小组赛第2轮）

即将开始的比赛（今日/明日）

- 6月23日 周二
  - 阿根廷 vs 奥地利，01:00，北京时间
  - 法国 vs 伊拉克，05:00，北京时间
  - 挪威 vs 塞内加尔，08:00，北京时间
  - 约旦 vs 阿尔及利亚，11:00，北京时间

- 6月24日 周三
  - 葡萄牙 vs 乌兹别克斯坦，01:00，北京时间
  - 英格兰 vs 加纳，04:00，北京时间
  - 巴拿马 vs 克罗地亚，07:00，北京时间
  - 哥伦比亚 vs 刚果（金），10:00，北京时间

数据来源：世界杯中文网 - 2026世界杯实时比分
https://worldcupchinese.com/scores/
```

Event counts:

```text
activity_fact_recorded: 24
evidence.candidate_recorded: 16
answer_delta: 16
hook_placement_started: 12
hook_placement_completed: 12
evidence.readiness_evaluated: 7
web_research.state_updated: 7
llm_call_started: 6
llm_call_completed: 6
tool_call_started: 5
tool_call_completed: 5
narrator_started: 4
web_fetch.started: 3
evidence.source_recorded: 3
web_fetch.completed: 3
narrator_rejected: 3
web_search.started: 2
web_search.completed: 2
run_created: 1
thinking_started: 1
thinking_summary_started: 1
thinking_preamble_started: 1
web_research.started: 1
thinking_preamble_delta: 1
thinking_preamble_completed: 1
context.compacted: 1
final_answer.allowed: 1
thinking_summary_completed: 1
answer_streaming_started: 1
run_completed: 1
```

Web research started:

```json
{
  "mode": "quick",
  "status": "web_required",
  "goal_preview": "[Tue 2026-06-23 19:15 GMT+08] 现在世界杯赛程怎么样？给我最新的已经结束和即将开始的比赛。",
  "now_utc": "2026-06-23T11:15:30+00:00",
  "user_timezone": "local",
  "budget": {
    "max_search_calls": 3,
    "max_fetch_calls": 5,
    "min_fetched_sources": 1,
    "min_independent_domains": 1,
    "max_candidate_results": 40,
    "search_calls": 0,
    "fetch_calls": 0
  }
}
```

Search calls:

```json
[
  {
    "query_preview": "2026年世界杯赛程 最新 已结束 即将开始 比赛",
    "provider": "duckduckgo_lite",
    "result_count": 8,
    "freshness_enforced": false
  },
  {
    "query_preview": "2026年世界杯 已结束比赛 今日 比赛结果",
    "provider": "duckduckgo_lite",
    "result_count": 8,
    "freshness_enforced": false
  }
]
```

Fetch calls:

```json
[
  {
    "source_id": "src_06e0edabc5c06b4e",
    "candidate_id": "cand_0daf825f08c5346a",
    "quality": 0.15,
    "text_length": 105,
    "source": "worldcup.cctv.com"
  },
  {
    "source_id": "src_fe9fe188cafdc4ff",
    "candidate_id": "cand_c608f9fb2c4d8f88",
    "quality": 0.8,
    "text_length": 700,
    "source": "goaltimeguide.com"
  },
  {
    "source_id": "src_3d2ccb011d89d969",
    "candidate_id": "cand_7c357f95e66eee7b",
    "quality": 0.8,
    "text_length": 700,
    "source": "worldcupchinese.com"
  }
]
```

Final readiness:

```json
{
  "reason": "before_final_answer",
  "ready": true,
  "status": "ready",
  "decision_reason": "ready",
  "gaps": [],
  "next_hint": "Evidence is ready. Answer from fetched sources only.",
  "budget": {
    "max_search_calls": 3,
    "max_fetch_calls": 5,
    "min_fetched_sources": 1,
    "min_independent_domains": 1,
    "max_candidate_results": 40,
    "search_calls": 2,
    "fetch_calls": 3
  },
  "ledger_summary": {
    "candidate_count": 16,
    "fetched_source_count": 3,
    "good_source_count": 2,
    "independent_domain_count": 2
  }
}
```

Important unfetched candidates still present at final readiness:

```text
BBC Chinese: FIFA世界杯2026：赛程及比分即时更新
FIFA: World Cup 2026 | Match schedule, fixtures & stadiums
Sofascore: 2026年世界杯 - 实时比分、赛果和小组赛
LiveScore: 足球即时比分与比赛结果
```

Thinking / activity events:

```json
{
  "thinking_preamble_delta": {
    "text": "我先理解了你是在问当前世界杯赛程的最新情况，包括已经结束和即将开始的比赛。Klara 会继续整理这些信息，为你呈现清晰的赛程概览。",
    "source": "narrator_model",
    "confidence": 0.95
  },
  "narrator_rejected": [
    {"phase": "live", "reason": "no_items", "fact_count": 1},
    {"phase": "live", "reason": "no_items", "fact_count": 9},
    {"phase": "completed", "reason": "no_items", "fact_count": 16}
  ],
  "thinking_summary_delta": 0,
  "provider_reasoning_delta": 0
}
```

## Current Architecture Map

These are the repository files GPT Pro should inspect in the GitHub branch.

### Web Research

- `src/klara/services/web/research.py`
  - `WebResearchBudget`
  - `EvidenceLedger`
  - `WebResearchPolicy.evaluate`
  - `WebResearchController.system_prompt_suffix`
  - `_budget_for_mode`
  - `_classify_mode`

- `src/klara/tools/builtin/web_search/tool.py`
  - Search observation shape
  - `provider_limitations`
  - `freshness_enforced`

- `src/klara/tools/builtin/web_search/schema.py`
  - Tool schema for query, freshness, language, country, date hints, require freshness.

- `src/klara/tools/builtin/web_fetch/tool.py`
  - Fetch observation shape
  - `extract_mode`
  - `query_terms`
  - `_extraction_quality`

- `src/klara/tools/builtin/web_fetch/schema.py`
  - Tool schema for URL fetch and snippet extraction.

- `src/klara/context/runtime.py`
  - Prompt-level guidance for latest/current/sports/schedules.

- `src/klara/core/loop.py`
  - Final-answer controller gate.
  - Tool loop.
  - Controller prompt suffix injection.

### Thinking / Activity / Debug

- `apps/api/services/run_service.py`
  - Thinking preamble narrator startup.
  - Live activity narrator.
  - Completed thinking summary creation.
  - Answer chunk streaming.
  - `_narratable_activity_facts`.

- `apps/api/services/run_event_projector.py`
  - `activity_fact_recorded` projection.
  - Provider reasoning projection.
  - Structured summaries for tools.

- `src/klara/prompts/thinking_preamble_narrator.md`
  - One-line public preamble prompt.

- `src/klara/prompts/thinking_activity_narrator.md`
  - Public activity summary prompt.

- `apps/web/src/components/klara/KlaraThinkingBlock.tsx`
  - Top assistant-turn Thinking / Thought trigger.

- `apps/web/src/components/klara/KlaraActivityDrawer.tsx`
  - Drawer sections for preamble, provider reasoning, Klara activity.

- `apps/web/src/components/klara/activityItems.ts`
  - Filters visible provider reasoning, narrator activity, and preamble.

- `apps/web/src/components/klara/KlaraRunSurface.tsx`
  - Developer debug display.

## Diagnosis: Web Search

### 1. Klara is searching, but the research mode is too shallow

The World Cup prompt is classified as `quick`. That gives:

```text
max_search_calls = 3
max_fetch_calls = 5
min_fetched_sources = 1
min_independent_domains = 1
```

For a question like "list all completed and upcoming World Cup matches", this is not enough. The requested answer contains many claims:

- match date
- match status
- team A
- team B
- score if completed
- venue or city if included
- kickoff time if upcoming
- whether the match belongs in completed or upcoming

The current readiness policy does not evaluate those claims. It evaluates only whether some fetched source looks readable and relevant enough.

### 2. Freshness is requested but not enforced

The model called `web_search` with `freshness=day`, `language=zh`, and `country=CN`.

However, the tool result says:

```text
provider = duckduckgo_lite
freshness_enforced = false
```

The tool also warns:

```text
The no-key search provider may not enforce freshness or language hints.
Treat snippets as candidates and verify time-sensitive facts with fetched source text.
```

The readiness gate does not react to this. It does not require another provider, another query, or stricter verification when freshness is not enforced.

### 3. Good source quality is not factual authority

`web_fetch` computes an extraction quality score based on page status, title, text length, query-term relevance, and shell-like page detection.

That is useful for rejecting empty pages. It is not enough to determine whether:

- the source is official
- the data is current
- the page is generated SEO content
- the page contains actual results rather than a fixture table
- the page supports each item in the final answer

In the local run, `goaltimeguide.com` and `worldcupchinese.com` both got `quality=0.8`. That only means they were readable and relevant-looking.

### 4. The source ranking is too provider-order dependent

The trace shows important candidates remained unfetched:

- FIFA official schedule page
- BBC Chinese live schedule / scores page
- Sofascore live scores page
- LiveScore page

But the model fetched:

- CCTV schedule page, which returned mostly navigation text
- goaltimeguide.com
- worldcupchinese.com

The runtime does not currently promote official or structured sports data sources over SEO-style pages. It also does not require cross-checking an unofficial source against an official or live-score source.

### 5. The final answer gate is source-count based, not claim-coverage based

The final decision was:

```text
final_answer.allowed
reason = ready
```

At that point:

```text
search_calls = 2
fetch_calls = 3
good_source_count = 2
independent_domain_count = 2
```

This lets the answer proceed. But the answer contains many individual match claims. There is no evidence matrix like:

```text
claim: "Netherlands 5-1 Sweden"
supported_by: source_id
date_seen: 2026-06-23
source_type: live_score
confidence: high/medium/low
```

Without that, Klara can cite one or two sources and still produce unsupported rows.

### 6. Search query planning is too generic

The queries used were:

```text
2026年世界杯赛程 最新 已结束 即将开始 比赛
2026年世界杯 已结束比赛 今日 比赛结果
```

These are reasonable first attempts, but not enough for the task. A better general research state machine would decompose the request into subgoals:

```text
completed matches as of current date
upcoming matches after current date
live/current match status
official schedule source
live score source
independent confirmation source
```

This should not be hardcoded for the World Cup. It should be a generic "multi-claim current-events research" planning step.

## Diagnosis: Thinking / Activity Display

### 1. The UI shows `Thought for X`, but the drawer often has only preamble

The local run had:

```text
thinking_preamble_delta = 1
thinking_summary_delta = 0
provider_reasoning_delta = 0
narrator_rejected = 3
```

This means the top UI has something to show only because the preamble exists. The preamble is just:

```text
我先理解了你是在问当前世界杯赛程的最新情况，包括已经结束和即将开始的比赛。Klara 会继续整理这些信息，为你呈现清晰的赛程概览。
```

That is not a trace of the 2 searches, 3 fetches, rejected narrator summaries, readiness transitions, or final answer gate.

### 2. Provider reasoning is absent for the default model path

`provider_reasoning_delta` is zero in this run. The code can parse provider reasoning if a model returns fields such as `reasoning_content`, but the selected model `qwen/qwen-flash` did not provide any visible reasoning summary in this trace.

Therefore `Model thinking` has no content.

### 3. Activity facts exist, but narrator output is rejected

The run recorded 24 activity facts. The activity narrator was started four times and rejected three times:

```text
live, no_items, fact_count=1
live, no_items, fact_count=9
completed, no_items, fact_count=16
```

The likely issue is a mismatch between:

- fact structure supplied to the narrator
- prompt constraints
- validator requirements
- expectations for what counts as public activity

This should be analyzed in `run_service.py`, `workstream_narrator.py`, and `thinking_activity_narrator.md`.

### 4. Developer debug is useful, but it is not the user-facing Thinking experience

The Developer debug panel contains raw events and tool information. That is useful for engineers and teaching. But the user-facing Activity drawer should summarize the work in a readable way:

```text
Klara searched for current schedule sources.
Klara found that the first fetched CCTV page was mostly navigation text.
Klara fetched two more schedule / score pages.
Klara allowed the final answer after 2 searches and 3 fetches.
```

The current UI does not show that because `thinking_summary_delta` never emits accepted items.

### 5. Preamble is currently doing too much visual work

The preamble is useful as a one-line live orientation. It should not be the only content behind a completed `Thought for 1m 18s`.

If the run has no provider reasoning and no narrator activity, the UI should not present a rich Thought drawer. Or it should explicitly show:

```text
No public activity summary was generated.
See Developer debug for raw trace.
```

But that is not the desired end state. The desired end state is to make narrator activity work from public facts.

## High-Confidence Root Causes

### Root Cause 1: Evidence readiness is not strong enough for multi-claim current events

Evidence:

- Quick mode only requires one good fetched source and one independent domain.
- Final readiness became `ready` after shallow evidence.
- The final answer contains many match claims.

Inference:

The web research gate is too coarse. It should decide based on required claim coverage, not just source count.

### Root Cause 2: Search freshness is advisory, not enforced

Evidence:

- `freshness=day` was passed.
- `freshness_enforced=false` was returned.
- Readiness still allowed final answer.

Inference:

For current/live queries, a provider that cannot enforce freshness should either lower confidence, require extra sources, or trigger a different provider/query path.

### Root Cause 3: Source selection lacks authority ranking

Evidence:

- FIFA, BBC, Sofascore, and LiveScore appeared as candidates but were not fetched.
- The final answer relied on `worldcupchinese.com/scores/`.

Inference:

The runtime currently lets provider rank and model choice dominate source selection. It needs a general source selection policy without hardcoding one domain-specific answer.

### Root Cause 4: Thinking activity generation is failing after facts are recorded

Evidence:

- 24 activity facts were recorded.
- `narrator_rejected` happened three times.
- `thinking_summary_delta` never appeared.

Inference:

The activity pipeline has sufficient raw material but the narrator/validator contract is not producing accepted public activity items.

### Root Cause 5: `Thought for X` is visually stronger than the evidence behind it

Evidence:

- Completed run displayed Thought, but drawer only had the generic preamble.
- Provider reasoning and narrator activity were absent.

Inference:

The UI currently lets preamble alone justify a completed Thought trigger. This makes the product feel like it has a real thinking trace when it does not.

## What Not To Fix With

Do not fix this by:

- adding a hardcoded World Cup rule
- adding a keyword if-statement for sports
- forcing a fixed domain list only for FIFA
- making the model always search a specific source
- writing final-answer correction rules for "not started" or "team A"
- showing raw chain-of-thought
- stuffing Developer debug into the public Thinking drawer

Those would make the Chapter 3 architecture less general.

## Better Architecture Direction

This is the general direction GPT Pro should evaluate against the current code.

### Web Research State Machine

The desired generic pipeline:

```text
1. classify research need
2. plan evidence requirements
3. generate diverse search queries
4. record candidates
5. rank candidates by source type, authority, freshness, and relevance
6. fetch selected sources
7. extract structured facts
8. evaluate coverage and conflicts
9. allow final answer only if coverage is sufficient or budget is explicitly exhausted
10. answer with uncertainty and per-source grounding
```

For the World Cup example, the evidence requirements are not special sports rules. They are generic requirements for a time-sensitive multi-row factual table:

```text
completed items need: date, team names, score/status, source
upcoming items need: date/time, team names, status, source
current/live items need: live timestamp or source update timestamp
```

### Public Thinking / Activity

The desired generic public activity pipeline:

```text
1. preamble: one short request-orientation sentence
2. provider reasoning: show only if provider returns safe public reasoning summary
3. runtime facts: record structured public facts for search/fetch/tool/readiness
4. narrator activity: convert meaningful facts into 2-5 public activity items
5. drawer: show Model thinking, Klara activity, and preamble details
6. developer debug: show raw events, tool args preview, observations, metrics
```

The narrator should be able to produce public activity like:

```text
Klara started with a current schedule query because the request depended on live or recent match data.
The first fetched schedule page returned mostly navigation, so it was not enough by itself.
Klara fetched additional schedule and score pages before allowing the final answer.
The final answer was allowed after 2 searches and 3 fetches, with 2 good sources across 2 domains.
```

This is not hidden chain-of-thought. It is a public explanation of observable runtime work.

## Questions For GPT Pro To Answer

Please inspect the GitHub branch and answer:

1. Where exactly should the research state machine live?
   - `src/klara/services/web/research.py` only?
   - a new service below `src/klara/services/research/`?
   - tool-specific or controller-level?

2. How should Klara distinguish:
   - quick lookup
   - current factual lookup
   - multi-claim current-events research
   - deep research

3. What should be the minimal claim coverage contract for Chapter 3 or Chapter 4 without overbuilding?

4. How should source ranking work generically?
   - official source
   - live-score/data source
   - reputable media source
   - SEO/blog source
   - unknown source

5. How should `freshness_enforced=false` change readiness?

6. Why does the activity narrator return `no_items` even with 16 narratable facts?

7. Should `Thought for X` be shown when only a preamble exists?

8. What tests should be added before changing behavior?

9. How can traces become post-training / evaluation quality?
   - action facts
   - observations
   - selected sources
   - rejected sources
   - coverage decisions
   - final claims
   - claim-source joins

## Suggested Acceptance Criteria For A Future Fix

These are not implemented in this report. They are here so GPT Pro can evaluate the desired behavior.

### Web Search Acceptance

For the prompt:

```text
现在世界杯的所有已经踢完的赛程和即将开始的都列举一下
```

A good trace should show:

- query planning created at least two subgoals: completed matches and upcoming matches
- search freshness requirements were explicit
- source candidates were ranked
- weak pages were rejected or marked low confidence
- at least one authoritative or structured sports source was fetched if available
- final readiness included coverage status, not just source count
- final answer did not include placeholder teams
- completed section did not include `vs` rows without scores unless explicitly marked as no score found
- every listed match had a source id or source group behind it

### Thinking / Activity Acceptance

A good UI should show:

- active preamble appears quickly
- if provider reasoning exists, Model thinking shows it
- Klara activity contains public runtime steps derived from facts
- narrator rejection appears in Developer debug, not as empty public thinking
- if no provider/narrator activity exists, completed `Thought for X` is not over-presented
- Developer debug remains available and raw, but does not substitute for public thinking

## Minimal Files To Review First

If time is limited, inspect these first:

```text
src/klara/services/web/research.py
src/klara/tools/builtin/web_search/tool.py
src/klara/tools/builtin/web_fetch/tool.py
src/klara/context/runtime.py
src/klara/core/loop.py
apps/api/services/run_service.py
apps/api/services/run_event_projector.py
src/klara/prompts/thinking_activity_narrator.md
apps/web/src/components/klara/activityItems.ts
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraActivityDrawer.tsx
```

## Short Prompt To Paste Into GPT Pro

Use this prompt with the GitHub link:

```text
Please analyze etherea1ity/AgentLadder branch chapter-3-hooks-and-trace at commit 183ba0f413f2f1c04d9b8b88cfbc13e53c290f45.

Focus on two failures:
1. Web search/research gives poor current-event answers for World Cup schedule/results. It searches and fetches, but final answers contain placeholders, unsupported scores, or rows that are labeled completed while still showing only vs.
2. Thinking UI shows Thought for X, but the Activity drawer often only contains one generic preamble. Provider reasoning is absent and narrator activity is rejected even when runtime facts exist.

Use the trace summary in docs/reports/ch03-thinking-web-search-diagnosis-for-gpt.md as the local JSONL trace artifact. Do not propose a hardcoded World Cup fix. Propose a general agent architecture fix: research state machine, source ranking, freshness handling, evidence readiness, claim coverage, and public activity narration.

Please give:
- root cause ranking with file references
- minimal architecture changes
- test plan
- risks
- what should stay out of Chapter 3
- what should move to Chapter 4
```
