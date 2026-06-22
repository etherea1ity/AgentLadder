# Chapter 3: Hooks and Trace

语言：中文 | [English](./ch03-hooks-and-trace.en.md)

上一章：[Chapter 2: Tool Calling](./ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Klara 不把 loop 藏成一个黑盒函数；她在关键生命周期点发出 public events，让 hooks 在固定 placement 上观察或轻量影响行为，再把同一条事件流投影成 JSONL trace、API/SSE、前端 thinking block 和 developer trace。

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

| 看到什么 | Klara 做什么 |
| --- | --- |
| `user_prompt_submit.*` | 标记用户请求进入 runtime 的边界 |
| `llm.started/completed` | 记录模型调用，并带上时延和 token usage |
| `pre_tool_use.*` | 工具执行前的 hook placement，可以 allow 或 block 单次调用 |
| `tool.started/completed/failed` | 每个工具调用都有一个真实 start 和一个 terminal event |
| `post_tool_use.*` | 工具 observation 生成后，hook 可以观察结果 |
| `stop.*` | loop 准备结束，在 `run.completed` 前给 hook 收尾位置 |
| JSONL trace | 保存可重放的 public events 和 metrics |
| API/SSE projection | 把 core events 整形成产品可见 run events |
| Thinking block | 运行中显示 `Thinking...`，完成后显示 `Thought for Xs`，可展开 trace-grounded summary |
| Web evidence guard | 把 search 当候选，把 fetch 当证据，把赛程和比分分开 |

## 快速体验

启动应用：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

先问一个稳定工具问题：

```text
Please use current_time to check the current time in Asia/Shanghai, then answer in one sentence.
```

你应该看到 assistant 标签下方出现紧凑的 thinking block。运行中它显示 `Thinking...` 和计时器，展开后是一条由真实 run events 派生的小溪流；完成后它显示 `Thought for Xs`，只有右侧 chevron 负责展开。

再打开开发者视角：

```text
http://127.0.0.1:8011/api/runs/{run_id}
```

API events 和 JSONL trace 来自同一条 public lifecycle stream。删除 session 后，相关 run events 和 trace lines 也会被清理。

## 3.1 为什么 Chapter 2 的 Tool Loop 还不够

Chapter 2 已经让工具调用跑起来：

```text
model requests tool_calls
-> runtime executes tools
-> observations return to the next model turn
-> model writes a final answer
```

这对 tool calling 足够，但对可观察性不够。用户会问：为什么没有继续搜？哪个工具失败了？是不是 hook block 了？答案到底用了 fetched evidence，还是只看了 search snippet？如果只往 loop 里塞更多日志，loop 会变脆，也很难教学。

Chapter 3 增加的是 lifecycle layer：

```text
KlaraLoop
-> public KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> SSE / frontend thinking block / developer trace
```

读者 takeaway：loop 仍然是 runtime 中心，但生命周期事实现在有稳定的 public shape。

## 3.2 KlaraEvent：公共生命周期事件

`KlaraEvent` 是本章核心契约。每个 public event 都有 schema version、`event_id`、run 内 `seq`、type、run id、timestamp、public payload，以及可选 private payload reference。

代码：

```text
src/klara/core/events.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

关键边界：

```text
public_payload      -> trace, API, UI 可以投影
private_payload_ref -> 未来指向私有内容的引用，不包含私有内容本身
```

`EventSequencer` 每个 run 从 `1` 开始单调递增。这样 trace replay 很直接：按 `run_id` 取 JSONL lines，再按 `seq` 看，就是这次运行的 public lifecycle。

工具 payload 只公开 compact shape。工具结果可以暴露 `name`、`ok`、`error`、`content_preview`、`content_length`，但前端不应该把超长 raw tool content 当成 answer text 展示。

## 3.3 Trace 不只有事件，也有 Metrics

第三章的 trace 不只是“发生了什么”，也记录“花了多久”和“provider 报告了多少 token”。

Event-level metrics 示例：

```json
{
  "type": "llm.completed",
  "payload": {
    "turn_index": 0,
    "tool_call_count": 1,
    "usage": {
      "prompt_tokens": 128,
      "completion_tokens": 64,
      "total_tokens": 192
    },
    "metrics": {
      "duration_ms": 924,
      "prompt_tokens": 128,
      "completion_tokens": 64,
      "total_tokens": 192,
      "token_source": "reported"
    }
  }
}
```

工具 terminal events 也有 `metrics.duration_ms`。被 hook block 的工具没有真正执行，所以 duration 是 `0`。`run.completed` 会带 run-level latency 和 usage totals。

`token_source` 的含义：

```text
reported  -> provider 返回了 usage
estimated -> 预留给之后的估算器
unknown   -> 没有可靠 usage
```

读者 takeaway：event trace 说明 happened-what；metrics trace 说明 slow-or-costly-how-much。

## 3.4 Observer Hook 不拥有 Loop Correctness

Observer hook 只接收事件，不决定 loop 是否成功。`JsonlTraceHook` 是最小例子：

```text
KlaraLoop._emit(event)
-> HookManager.emit(event)
-> JsonlTraceHook.on_event(event)
-> event.to_public_dict() is appended to JSONL
```

代码：

```text
src/klara/core/hooks.py
apps/api/services/app_store.py
tests/apps/api/test_app_store_delete.py
```

JSONL shape 使用 top-level `run_id`，所以 app store 查询和 purge 也按 `record.get("run_id") == run_id` 做。删除 session 时，不会留下孤儿 trace lines。

Hook failure 也要隔离：observer hook 抛异常时，`HookManager.failures` 记录失败，loop 继续跑。

## 3.5 Lifecycle Placements：Submit、PreToolUse、PostToolUse、Stop

Hooks 可以选择接入固定生命周期位置：

```text
UserPromptSubmit -> 用户请求进入 runtime
PreToolUse       -> 单个工具执行前
PostToolUse      -> 工具 observation 生成后
Stop             -> run 完成前
```

代码：

```text
src/klara/core/hooks.py
src/klara/core/loop.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

Decision 对象故意很小：

```python
@dataclass(frozen=True)
class HookDecision:
    allowed: bool = True
    reason: str = ""
    public_metadata: dict[str, object] = field(default_factory=dict)
```

`HookManager` 用 `getattr` 发现可选方法，所以一个 hook 可以只实现 `on_event`，也可以额外实现 `on_pre_tool_use`、`on_post_tool_use` 等 placement 方法。

如果 PreToolUse hook 返回 `allowed=False`，当前工具会被 block。工具不会执行，不会发 `tool.started`，模型会收到一个 failed tool observation：

```text
pre_tool_use.started
pre_tool_use.completed allowed=false
tool.failed blocked=true
role="tool" observation: "Tool blocked by hook: ..."
```

这不是 permission engine。它不弹 approval UI，不等人确认，不写长期 policy，也不改工具注册表。

## 3.6 Tool Lifecycle Exactly Once

工具事件要能精确配对：

```text
successful tool  -> one tool.started + one tool.completed
unknown tool     -> one tool.started + one tool.failed
tool exception   -> one tool.started + one tool.failed
pre-tool blocked -> zero tool.started + one tool.failed
policy stop      -> zero tool.started for pending calls
```

代码：

```text
src/klara/core/loop.py
src/klara/tools/executor.py
tests/klara/core/test_loop.py
```

`tool.started` 表示工具真的开始执行。被 hook block 的调用仍然有 terminal failure，但不会伪装成已经 started。

## 3.7 API/SSE Projection

API 不直接把 core events 原样推给前端。`RunEventProjector` 把 public lifecycle events 变成产品可见 run events：

```text
llm.started          -> llm_call_started
llm.completed        -> llm_call_completed
tool.started         -> tool_call_started
tool.completed       -> tool_call_completed
tool.failed          -> tool_call_failed
pre/post hook events -> hook_placement_started/completed
tool_policy.stopped  -> policy_stop
```

代码：

```text
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/api/services/sse_bus.py
apps/api/schemas.py
tests/apps/api/test_run_event_projector.py
```

Projector 也负责产品层 usage accumulation。`answer_delta` 仍然只是 answer streaming，不是 trace。`thinking_summary_delta` 只是可见 thinking summary，不是 assistant message content，也不会进入后续 model-visible history。

## 3.8 GPT 风格 Thinking Block

当前用户可见主表面是 GPT 风格 thinking block：

```text
active run:
  Thinking... 4.2s
  expanded details show a small event-grounded stream

completed run:
  Thought for 23.9s
  right-side chevron expands details
```

代码：

```text
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/types/domain.ts
apps/web/src/api/client.ts
```

这不是 raw chain-of-thought。运行中那条“小溪流”来自 public events，比如 model started、tool started、tool completed、hook completed、run completed。完成后，可选 narrator 会基于完整 public trace 生成一段短 summary。

如果 narrator 不可用，Klara 仍然会发：

```text
thinking_summary_started
thinking_summary_completed has_summary=false
```

UI 会显示 `Thought for Xs`，但不会编一个假的 summary。

Developer trace panel 保持独立且弱化：

```text
Developer trace · 38 events · 3 tools
```

Tool cards 和 hook badges 留在 developer trace 里，不抢主 thinking block 的位置。

## 3.9 Thinking Summary Narrator

Thinking summary narrator 是 capstone，不是 core 机制。它在主 loop 完成后、answer streaming 前运行。输入是完整 public run events，不是私有 scratchpad。

Prompt：

```text
src/klara/prompts/thinking_summary_narrator.md
```

Service：

```text
apps/api/services/workstream_narrator.py
tests/apps/api/test_thinking_summary.py
```

规则：

- 只总结 runtime 实际做过什么
- 使用 evidence event ids
- 匹配用户语言
- 不回答用户问题
- 不暴露 raw tool arguments、secrets、full URLs、file contents、hidden reasoning、chain-of-thought
- 拒绝无证据 action claims
- 忽略 invalid JSON、空文本和 forbidden reasoning language

`workstream_note` 作为兼容事件仍然保留，但 Chapter 3 默认用户表面是 completed-run thinking summary。

## 3.10 Web Evidence 边界

Web tools 在第三章也承担一个重要教学点：search results 是 candidates，不是 facts。

代码：

```text
src/klara/tools/builtin/web_search/tool.py
src/klara/tools/builtin/web_fetch/tool.py
src/klara/services/web/source_quality.py
src/klara/services/web/search.py
src/klara/context/web_evidence.py
tests/klara/services/test_web_search.py
tests/klara/tools/test_web_tools.py
tests/klara/context/test_web_evidence.py
```

Current sports queries 会给搜索结果加 source quality：

```text
official      -> fifa.com
wire          -> reuters.com, apnews.com
sports_media  -> ESPN, Guardian football, BBC Sport, Fox Sports
aggregator    -> SEO or score-aggregation style sites
unknown       -> everything else
```

这不是 allowlist，也不会禁用其他来源。它只是 evidence selection 和 trace teaching 的质量信号。

Guard 会提醒模型：

- search snippets 不足以支撑具体事实
- current sports 至少 fetch 相关 sources，除非一个 official page 已直接包含所需事实
- aggregator-only evidence 不能支撑具体比分
- fixtures are not results
- scheduled match with no verified score is not `0:0`
- 回答要分开 completed results、scheduled or in-progress fixtures、source limitations

教学 prompt：

```text
帮我搜一下世界杯最新进展
```

在 June 18 教学场景中，期望行为是：

- 调用 `web_search`
- 需要最新结果时 fetch FIFA schedule 和至少一个 news、wire 或 sports-media source
- 区分 June 17 completed results 与 June 18 scheduled or in-progress fixtures
- 回答里给出 source URLs
- trace 里能看到带 latency 的 `web_search` / `web_fetch`
- thinking summary 高层描述 evidence selection，但不声称没有证据的工作

## 3.11 本章不做什么

Chapter 3 不包括：

- complete permission engine
- Todo Planning
- agent task ledger
- context compression
- memory write policy
- full harness/config refactor
- full provider streaming adapter
- OpenAI/Claude/DeepSeek reasoning stream integration
- raw chain-of-thought display

Todo 属于 Chapter 5。RAG/module pipeline 属于后续章节。Thinking summary 只是 public trace projection，不是 hidden reasoning。

## 代码索引

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
src/klara/core/tools.py
src/klara/tools/executor.py
src/klara/context/web_evidence.py
src/klara/services/web/source_quality.py
apps/api/services/run_event_projector.py
apps/api/services/app_store.py
apps/api/services/run_service.py
apps/api/services/workstream_narrator.py
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
apps/web/src/components/ChatWorkspace.tsx
```

## 运行与验证

后端和 core：

```powershell
pytest -q
```

前端：

```powershell
cd apps\web
npm test
npm run build
npm audit --omit=dev
```

手动检查：

1. 启动 `.\scripts\dev.ps1`。
2. 问一个 `current_time` 问题，确认 thinking block timer、chevron、tool card 和 trace panel。
3. 问 `帮我搜一下世界杯最新进展`，确认回答区分 fetched evidence、completed results、fixtures 和 source limitations。
4. 打开 `/api/runs/{run_id}`，检查 events 和 metrics。
5. 删除 session，确认相关 trace data 被清理。

## 小实验

1. 写一个只实现 `on_event` 的 hook，确认它收到 lifecycle events。
2. 写一个 `on_pre_tool_use` 返回 `allowed=False` 的 hook，确认工具不会执行。
3. 人为让 hook 抛异常，确认 run 仍然完成，并记录 failure。
4. 打开 JSONL trace，按 `seq` replay 一条 run。
5. 在 current sports query 上比较 search-only evidence 和 fetched evidence。

## 下一章

Chapter 4 会讲 Harness And Config：现在 loop、tools、hooks、trace、metrics 和 projections 都有了边界，下一步是把 provider、model、prompt、tools、hooks、policies、trace sinks 的组装收束到一个清晰的 harness entry point。
