# Klara README Conventions Reference

Klara READMEs are not release notes. They are teaching chapters that must let a
reader understand the runtime idea first, then inspect the real code.

This file is the canonical project rule for chapter README writing. It is based
on the current Klara direction plus local reference reading from:

- `C:\Users\brainclos_032\Desktop\ReAct\learn-claude-code\s01_agent_loop\README.md`
- `C:\Users\brainclos_032\Desktop\ReAct\learn-claude-code\s02_tool_use\README.md`
- `C:\Users\brainclos_032\Desktop\ReAct\learn-claude-code\s04_hooks\README.md`
- `C:\Users\brainclos_032\Desktop\ReAct\README.md`
- `C:\Users\brainclos_032\Desktop\ReAct\docs\ARCHITECTURE.md`
- `C:\Users\brainclos_032\Desktop\hello-agents\README.md`
- `C:\Users\brainclos_032\Desktop\hello-agents\docs\chapter4\Chapter4-Building-Classic-Agent-Paradigms.md`
- `C:\Users\brainclos_032\Desktop\hello-agents\docs\chapter7\Chapter7-Building-Your-Agent-Framework.md`
- `C:\Users\brainclos_032\Desktop\hello-agents\docs\chapter14\Chapter14-Automated-Deep-Research-Agent.md`
- `C:\Users\brainclos_032\Desktop\hello-agents\code\chapter4\ReAct.py`

## Core Teaching Rule

Every chapter must begin with the mechanism, not the module list.

The reader should be able to answer this within the first screen:

```text
What changes in Klara now?
What stays the same?
What signal decides the next step?
Which section shows the real code?
```

For Chapter 1, the first-screen teaching target is:

```text
If the model requests tools, runtime executes them and feeds results back.
If the model requests no tools, the loop stops and returns the final answer.
```

Do not open a chapter by listing harness, provider, config, frontend, trace, or
other boundaries before the reader understands the mechanism being taught.

## Opening Budget

The top of a chapter should be short enough to read in one breath.

After title and navigation, use this order:

```text
one-sentence thesis
-> generated core image
-> tiny signal table
-> quick experience
```

Avoid a separate "main contents" introduction when it only restates the later
sections. The first screen should teach the decision rule, not summarize every
module.

Do not turn the first screen into an ASCII process diagram. A short flow can
appear later inside a teaching section, but the top mechanism should be carried
by a generated visual asset.

For Chapter 1, replace a broad intro such as:

```text
This chapter covers LLM calls, loop organization, tool calls, hooks, and harness.
```

with:

```text
Klara runs one turn at a time: if the model asks for tools, runtime executes
them and continues; if it asks for no tools, the loop stops.
```

Then let the following sections explain LLM calls, hooks, harness, and provider
boundaries in execution order.

## Course Portal vs Chapter Tutorial

Keep the course entry and the active chapter in different mental lanes.

- Course portal: explains what Klara is, who it is for, what the full roadmap
  contains, and how to join the project.
- Chapter tutorial: teaches one runtime mechanism, shows the smallest useful
  behavior, then walks through the real source code.

The `hello-agents` root README is a strong portal pattern: project introduction,
quick start, content navigation, learning method, contribution, and community.
Klara's active chapter README must be tighter than that. If `README.md` displays
the current chapter on GitHub, it should behave like a chapter entry, not a
course brochure plus a long architecture essay.

Full chapter content should live in `docs/chapters/`. The root README may mirror
the active chapter while a branch is teaching that chapter, but it must still
open with the chapter's mechanism and stop/continue signal.

## Output Locations

For the active chapter, maintain both:

- Root preview: `README.md` and `README.en.md` when the branch should display
  the chapter on GitHub.
- Chapter archive: `docs/chapters/<chapter-slug>.md` and
  `docs/chapters/<chapter-slug>.en.md`.

Fix relative links when copying chapter docs into root README files:

- Root image path: `./docs/assets/...`
- Chapter image path: `../assets/...`
- Root roadmap path: `./docs/skills/roadmap.md`
- Chapter roadmap path: `../skills/roadmap.md`
- Root language toggle: `README.md` <-> `README.en.md`
- Chapter language toggle: `<chapter>.md` <-> `<chapter>.en.md`

## Required Chapter Structure

Use this order unless a chapter has a strong reason to differ:

1. Title and bilingual navigation.
2. Previous / next chapter navigation, including the next chapter title.
3. Roadmap link.
4. One-sentence thesis: the chapter's central mechanism.
5. One clear generated image that explains the mechanism.
6. Tiny signal table: the exact signal that makes runtime continue or stop.
7. Quick experience: how to run, what to ask, and what the reader should see.
8. Main teaching sections in execution order.
9. Code walkthroughs inside details blocks.
10. Run and verification instructions.
11. Small experiments or exercises.
12. Next chapter preview.

The first five visible sections must be short. A reader should not need to
scroll past a long architecture inventory before seeing the core idea.

## First-Screen Pattern

Start with a compact teaching block:

````md
## 一句话看懂本章

模型要工具，runtime 执行工具并继续；模型不要工具，loop 停止并返回答案。

![Klara Chapter 1 Minimal Loop](./docs/assets/ch01-minimal-loop.png)

| 看到什么 | Klara 做什么 |
| --- | --- |
| 有 `tool_calls` | 执行工具，把结果放回上下文，继续下一轮 |
| 没有 `tool_calls` | 返回最终答案，停止 |
| 达到 `max_turns` | 不再暴露工具，最后做一次无工具 LLM 总结，并展示停止原因 |
````

This block should appear before harness, provider, frontend, RAG, memory, or
configuration details.

## Experience First, Then Implement

When a chapter has runnable behavior, the quick experience should only tell the
reader how to run it and what to look for. It is not a feature tour.

Use this shape:

````md
## 快速体验

```powershell
.\scripts\dev.ps1
```

打开 `http://127.0.0.1:5123`。

你可以先问：

```text
用一句话介绍你自己。
```

你应该看到：模型直接回答，右侧 run 事件显示本轮结束。

再问：

```text
调用 current_time 告诉我 Asia/Shanghai 现在几点。
```

你应该看到：模型请求工具，runtime 执行工具，然后把 observation 放回下一轮。
````

The quick experience must stay near the top, but the full setup and test
commands still belong in the later run-and-verification section.

## Problem Before Mechanism

Each chapter should start from a concrete friction, not from an abstraction.

Good:

```text
The model can ask to read a file, but it cannot read the file by itself.
Without a loop, a human must run the tool and paste the result back.
```

Weak:

```text
This chapter introduces the ToolExecutor, HookManager, ModelResponse, and
LoopPolicy modules.
```

The module names can appear after the reader understands what runtime action
they serve.

## Real Incident -> Mechanism -> Source

When a chapter grows out of a real bug, confusing demo, or failed user run,
teach from that incident. Do not write it as a changelog or a confession. Use it
as the smallest visible case that makes the runtime boundary necessary.

Use this order:

```text
1. 现场：用户问了什么，Klara 做错了什么，或者 trace 显示了什么。
2. 判断：这不是哪个表面模块的问题，而是哪条 runtime 边界不清。
3. 机制：本章新增或收紧哪条机制。
4. 源码：对应的真实文件、关键分支、状态变化。
5. 验证：读者怎么在前端、trace、tests 或 prompts 里复现。
6. 预告：完整解法若属于后续章节，只讲当前章节的边界。
```

For Chapter 2, the real incident pattern is:

```text
用户先问世界杯战报，Klara 能走 web_search -> web_fetch。
之后加入 image_generate，并在同一类聊天里继续问最新战报或追问阿根廷。
有些 run 没有稳定继续调用搜索工具，或者把低质量网页 observation 当成事实。
```

The teaching point is not "add a keyword router". The teaching point is:

```text
ToolSpec tells the model what actions exist.
ToolMetadata tells runtime how risky and schedulable those actions are.
ToolExecutor turns success and failure into observations.
Conversation-history preparation removes stale local asset links and bounds the
history before the next run.
```

This incident should point to source:

```text
src/klara/core/loop.py
src/klara/core/tools.py
src/klara/tools/registry.py
src/klara/tools/executor.py
src/klara/context/history.py
apps/api/services/run_service.py
data/app/run_events.jsonl
```

Use short trace excerpts, not giant logs. A good excerpt shows the decision
signal:

```text
llm_call_completed: tool_call_count=1
tool_call_started: web_search
tool_call_completed: web_search
tool_call_started: web_fetch
...
follow-up run: tool_call_count=0
```

Anti-pattern:

```text
We fixed image pollution and added web tools.
```

Better:

```text
The model can only decide well when the current run exposes a clear tool
contract and a clean recent history. This chapter builds the tool boundary; full
context compression and memory policy are deferred.
```

## Concept -> Mechanism -> Code -> Experiment

Each main teaching section should move in this order:

1. Concept: one useful idea, stated in plain language.
2. Mechanism: input, decision signal, action, next state, stop condition.
3. Code: real paths plus the exact block that implements the mechanism.
4. Experiment: a prompt, test, or small modification the reader can try.

This comes from two useful `hello-agents` patterns:

- Chapter 4 defines ReAct as a Thought -> Action -> Observation loop before
  showing tool definitions, parsing, execution, and history integration.
- Chapter 14 explains tool calls as instruction generation -> parsing -> lookup
  -> execution -> result formatting, which is a useful shape for Klara's later
  tool-registry chapter.

Klara should be more explicit about the runtime state after each block. A code
excerpt is incomplete until the prose says what changed in `messages`, `history`,
`run_id`, hook events, tool observations, memory, or stop reason.

## Mechanism Before Architecture

For every chapter, write the mechanism in this order:

1. The input.
2. The decision signal.
3. The action.
4. The next state.
5. The stop condition.

Then introduce architecture boundaries.

Example for Chapter 2:

```text
Existing loop stays the same.
Only tool execution changes:
hardcoded placeholder branch -> registry lookup -> selected tool handler.
```

Example for hooks:

```text
Existing loop stays the same.
New behavior is attached to lifecycle events:
before tool, after tool, before stop.
```

This "what changes / what stays the same" sentence is required for every
chapter after Chapter 1.

## Klara Vocabulary Must Stay Precise

`hello-agents` uses "Everything is a Tool" as a teaching simplification. Klara
can borrow the teaching move, but not the vocabulary collapse.

Use these boundaries consistently:

- Tool / capability: a model-facing action that can be selected and executed.
- RAG: a retrieval capability; it can be exposed as a tool, but the retrieval
  algorithms and index pipeline remain their own lesson.
- Hook: lifecycle extension outside the loop body, such as before model call,
  after tool result, stop guard, trace sink, or policy gate.
- Memory: runtime/user/project state that may influence context, retrieval, or
  future runs; it is not simply another tool.
- Context compression: a context-shaping policy that decides what remains
  visible to the next model turn.

When teaching a chapter, state which of these boundaries is being added and
which ones stay untouched.

## Outer Layer

The visible README must be readable without opening any details block.

For each teaching section, include:

- the problem solved
- the compact mechanism or flow
- what Klara learns
- what changed from the previous chapter
- real code paths

Do not hide code paths inside details blocks, but do not add a standalone "code
map" section by default. Put the relevant code paths beside the mechanism that
uses them. A standalone code map is only allowed for architecture appendix pages
or very large chapters where navigation would otherwise be painful.

Use this shape:

````md
## 2. Loop calls the model once per turn

The loop does not ask the model to "be an agent" in one shot. It asks for one
assistant turn, then checks whether the response contains tool calls.

```text
messages + system_prompt + tool specs
-> LLM
-> assistant message + optional tool_calls
```

Klara learns: the LLM call is one step inside the runtime loop, not the whole
agent.

Changed in this chapter: the response can either stop the loop or request tools.

Corresponding code:

```text
src/klara/core/loop.py
src/klara/core/messages.py
```

<details>
<summary>Expand: real code walkthrough for the LLM turn</summary>

Real code and line-by-line explanation.

</details>
````

## Code Walkthroughs

Detailed source explanation is required. It should be hidden in details blocks, but
it must be concrete and ordered by execution.

For each code walkthrough:

1. Explain why this code appears at this point in the run.
2. Show a real code block from the repository.
3. Explain the input and output of the code before walking through it.
4. Explain important parameters, variables, emitted events, returned values, and
   failure branches.
5. State the runtime state change after each important branch.
6. State the architecture boundary protected by the code.
7. State the reader takeaway in one sentence.

Do not paste code as decoration. Every code block must answer:

```text
What has changed in runtime state after this block runs?
```

## Code Explanation Depth

Klara chapters are teaching chapters, so details blocks must teach the code, not
merely prove that code exists.

Every non-trivial details block should use this order:

```text
Why this code is here
-> Input / output contract
-> Real code excerpt
-> How to read this code step by step
-> Concrete example
-> Runtime state changes
-> Boundary protected
-> Takeaway
```

The step-by-step explanation should be explicit enough that a reader can follow
the execution without opening the source file in another tab. Include:

- what each important variable represents
- who constructed that value
- who reads it next
- which branch is the success path
- which branch is the failure or fallback path
- how ids, names, messages, events, or observations are joined together
- which metadata fields are consumed now and which are only future-facing signals

Prefer prose around the code over adding many tutorial comments into production
source. Short comments inside README code excerpts are allowed when they make the
excerpt easier to teach, but the repository source should stay production-grade.

For example, an executor walkthrough should not stop at:

```text
unknown tool becomes failed observation
```

It should say:

```text
`call.name` comes from the model's tool call. The executor looks it up in the
visible tool map for this run. If the name is absent, the executor still returns
`ToolResult(tool_call_id=call.id, name=call.name, ok=False, error=...)` so the
loop can append a model-visible tool message joined to the original request id.
```

For algorithms, include one small trace example. For example:

```text
[safe A, safe B, serial C, safe D]
-> run A/B in one wave
-> run C alone
-> run D in the next wave
```

For metadata-driven sections, include a field table:

```text
field -> who reads it -> current behavior -> future behavior if any
```

This is especially important when a metadata field exists for future policy but
is not yet consumed by the current algorithm.

For Chapter 1, `KlaraLoop.run()` must be explained in this order:

1. Create `run_id` and the first user message.
2. Start a bounded turn loop.
3. Call the LLM with messages, system prompt, tool specs, and model id.
4. Append the assistant message.
5. If there are no tool calls, complete with `StopReason.FINAL`.
6. If there are tool calls, execute each tool.
7. Append each tool result as a model-visible observation.
8. Prepare the next turn.
9. When policy is exhausted, stop exposing tools, make one no-tool finalization call, then stop with `StopReason.MAX_TURNS`.

## Images

Each chapter should have one clear visual near the top.

The image must explain the mechanism, not merely decorate the page.

Generate this image with `image-2` / the image generation skill when the chapter
needs a new visual asset. Save the resulting raster file under `docs/assets/`.
If the final image is generated outside Codex, keep the README path stable and
replace only the asset file when it arrives.

For a loop chapter, the image should visibly show:

```text
LLM -> tool_calls? -> yes: tools -> observations -> LLM
                 -> no: final answer / stop
```

Requirements:

- landscape layout
- clear labels
- no tiny unreadable text
- no fake UI screenshots unless the chapter is about UI
- no chain-of-thought wording
- the decision signal must be obvious
- the stop path must be visually obvious

Save project-bound images under:

```text
docs/assets/
```

Recommended Chapter 1 image prompt:

```text
Create a clean 16:9 landscape technical infographic for "Klara Chapter 1:
Minimal LLM Loop".

The diagram must show this exact mechanism:
User -> Klara Loop -> LLM -> decision diamond "tool_calls?"

YES path:
tool_calls? -> Tools -> Observation -> back to Klara Loop

NO path:
tool_calls? -> Final Answer -> Stop

Side branch:
Klara Loop -> Hooks -> Trace / UI

The YES path is the only path that returns to Klara Loop. Final Answer and Stop
must not connect back to Klara Loop.

Use large readable labels, a white background, teal for Klara Loop, purple for
LLM/Hooks, amber for Tools/Observation, green for Final Answer, red for Stop,
and gray arrows. No code, no screenshots, no chain-of-thought wording, no
watermark, no extra labels.
```

## Source-Aware Teaching

Klara chapters should teach from the local implementation, but can use reference
projects to sharpen the lesson.

When borrowing teaching structure from references:

- Extract the teaching move, not the reference project's personality.
- Do not copy large passages.
- Prefer local Klara code as the source of truth.
- Mention reference influence only in planning docs or convention docs, not in
  every chapter unless useful for the reader.

Reference patterns worth preserving:

- `learn-claude-code/s01_agent_loop`: problem -> solution diagram -> two
  signals -> 30-line loop -> run prompts -> deeper source appendix.
- `learn-claude-code/s02_tool_use`: state what stayed unchanged, then show the
  one line or boundary that changed.
- `learn-claude-code/s04_hooks`: show how behavior moves out of the loop and
  onto event hooks.
- `ReAct/docs/ARCHITECTURE.md`: define the core loop in one compact flow, then
  list hard boundaries.
- `hello-agents/README.md`: keep the course portal separate from the chapter
  tutorial; use the portal for roadmap, audience, learning method, and links.
- `hello-agents/docs/chapter4`: teach the agent loop before introducing tool
  classes; show how action results become observations in the next context.
- `hello-agents/docs/chapter7`: explain why we build our own small framework,
  then give a 30-second runnable experience before framework internals.
- `hello-agents/docs/chapter14`: express tool calling as instruction -> parse
  -> lookup -> execute -> format result.

## Bilingual Docs

Write Chinese first unless asked otherwise, then create the English mirror.

The English version must preserve structure, diagrams, code blocks, paths,
commands, and section order. Translate prose; do not invent new technical
claims.

Code explanations must stay in the document language:

- Chinese README files use Chinese prose for walkthroughs, branch explanations,
  examples, and takeaways.
- English README files use English prose for the same walkthroughs.
- Code blocks, identifiers, paths, commands, and literal error strings remain as
  they appear in the repository.

Do not leave English teaching prose inside the Chinese README, and do not leave
Chinese teaching prose inside the English README except when quoting user-facing
prompts that are intentionally Chinese.

## Run And Verification

Use realistic local execution instructions.

For Chapter 1 and similar full-stack chapters:

```powershell
Copy-Item .env.example .env
```

List required keys without secrets:

```text
DEEPSEEK_API_KEY=...
DASHSCOPE_API_KEY=...
```

Prefer the one-command dev script when available:

```powershell
.\scripts\dev.ps1
```

List default URLs and targeted tests. Do not claim tests passed unless they were
run in the current task.

## Anti-Patterns

Do not write a Klara chapter like this:

- module inventory before mechanism
- image that looks pretty but does not show the decision signal
- ASCII process flow as the main first-screen visual
- long introduction before the first runnable idea
- code paths hidden only inside details blocks
- code snippets without execution-state explanation
- provider/config/frontend details before the core runtime idea
- "this chapter introduces X" without saying what runtime problem X solves
- abstract agent vocabulary before the reader sees input -> decision -> output
- a top-level "what this chapter does not do" block before the reader understands
  the chapter's positive mechanism
- root README trying to be portal, chapter, architecture spec, and changelog at
  the same time
- exercise prompts that ask for vague reflection without touching code, tests,
  or runtime behavior

## Stop Checks

Before finishing README work, verify:

- root README displays the intended chapter if requested
- bilingual links are not broken
- image paths exist
- the first screen states the chapter's mechanism and stop/continue signal
- details block open and close counts match
- code paths referenced in visible sections exist or are intentionally future-facing
- run commands match current scripts and config
- targeted tests were run, or the validation gap is reported
