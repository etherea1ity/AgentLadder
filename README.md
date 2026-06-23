# Chapter 3: Hooks and Trace

语言：中文 | [English](./README.en.md)

上一章：[Chapter 2: Tool Calling](./docs/chapters/ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](./docs/skills/roadmap.md)

完整章节：[docs/chapters/ch03-hooks-and-trace.md](./docs/chapters/ch03-hooks-and-trace.md)

---

## 一句话看懂本章

Klara 不把 loop 藏成黑盒函数；hooks、JSONL trace、API/SSE、GPT 风格 thinking block 和 developer trace panel 都从同一条 public lifecycle event stream 投影出来。

![Klara Chapter 3 Hooks and Trace](./docs/assets/ch03-hooks-and-trace.svg)

| 看到什么 | Klara 做什么 |
| --- | --- |
| Hooks | 观察 lifecycle events，并在 `PreToolUse` 等固定 placement 上轻量影响行为 |
| Trace | 记录 public events、duration 和 token metrics |
| Thinking block | 运行中显示 `Thinking...`，完成后显示 `Thought for Xs`，用 chevron 展开 |
| Developer trace | 把 tool cards、hook badges、trace saved state 留在 answer text 外面 |
| Web evidence | 把 search 当候选，把 fetch 当证据，把赛程和比分分开 |

## 快速体验

启动应用：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

先问：

```text
Please use current_time to check the current time in Asia/Shanghai, then answer in one sentence.
```

你应该看到：

```text
Thinking...  -> active 时来自 public events 的小溪流
Thought for Xs -> 右侧 chevron 展开 trace-grounded details
Assistant answer -> 只有 answer_delta 改 message content
Developer trace -> tool cards、hook badges、trace saved state、metrics
```

再打开 run 详情：

```text
http://127.0.0.1:8011/api/runs/{run_id}
```

删除 session 时，相关 messages、runs、events 和 JSONL trace lines 也会被清理。

## Chapter 3 改变了什么

Chapter 2 已经让工具调用跑起来：

```text
model tool_calls -> runtime executes tools -> observations return to model
```

Chapter 3 在它外面加上 public lifecycle structure：

```text
KlaraLoop
-> KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> frontend thinking block + developer trace
```

重点不是装饰 UI，而是一个稳定事件契约：可观察、可 trace、可投影、可测试，以后还能用于 evaluation。

## Hooks

Hooks 有两类职责：

```text
observer hook   -> on_event(event)
placement hook  -> on_user_prompt_submit / on_pre_tool_use / on_post_tool_use / on_stop
```

`PreToolUse` 可以 block 单次工具调用，但它不是完整 permission engine。Block 会给下一轮模型生成 failed tool observation；它不弹 approval UI，不等人确认，也不写长期 policy。

Hook failure 会隔离，只记录到 `HookManager.failures`，不会 crash run。

## Trace And Metrics

Trace 分两层：

```text
event trace   -> what happened
metrics trace -> how long it took and what usage was reported
```

`llm.completed`、工具 terminal events 和 `run.completed` 会暴露 `duration_ms`、latency、usage totals 和 `token_source`。`token_source` 可以是 `reported`、`estimated` 或 `unknown`。

Public payload 是安全投影面。Private payload content 不会塞进事件里，未来只用 `private_payload_ref` 指向。

## API/SSE Projection

`RunEventProjector` 把 core events 映射成产品可见 events：

```text
llm.started   -> llm_call_started
tool.failed   -> tool_call_failed
pre_tool_use  -> hook_placement_*
run events    -> SSE + stored RunEventRecord
```

`answer_delta` 不是 trace。`thinking_summary_delta` 也不是 assistant content。它们都是 run events，但只有 answer deltas 会改 assistant message。

## Thinking Summary

可见 thinking block 是 GPT 风格：

```text
active:    Thinking... 4.2s
completed: Thought for 23.9s
toggle:   only the right-side chevron
```

运行中，展开区域展示一条由真实 public events 派生的小溪流。完成后，可选 narrator 会基于完整 public trace 生成短 summary。如果没有 narrator，Klara 不会编假的 summary。

这不是 raw chain-of-thought，也不是 hidden reasoning display。

## Web Evidence Boundary

对于 current sports 和比分类问题：

- search results 是 candidates，不是 facts
- snippets 不能支撑具体比分
- search candidates and fetched page text remain separate observations
- scheduled match with no fetched verified score is not `0:0`
- current results 优先 official、wire、sports-media evidence
- aggregator-only evidence 不能支撑具体比分

教学 demo：

```text
帮我搜索一个需要当前网页信息的问题
```

Klara 可以由模型决定是否 search / fetch；trace 应该显示真实发生的 `web_search` / `web_fetch` 调用、latency 和 tool observations。

## 代码索引

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
src/klara/tools/executor.py
apps/api/services/run_event_projector.py
apps/api/services/app_store.py
apps/api/services/run_service.py
apps/api/services/workstream_narrator.py
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
```

## 运行与验证

```powershell
pytest -q
cd apps\web
npm test
npm run build
npm audit --omit=dev
```

Chapter 4 会把这条可运行 runtime 收束进更清晰的 Harness And Config 边界。
