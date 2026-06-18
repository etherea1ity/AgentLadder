# Chapter 3: Hooks and Trace

语言：中文 | [English](./README.en.md)

上一章：[Chapter 2: Tool Calling](./docs/chapters/ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](./docs/skills/roadmap.md)

完整章节：[docs/chapters/ch03-hooks-and-trace.md](./docs/chapters/ch03-hooks-and-trace.md)

---

## 一句话看懂本章

Klara 不直接把 loop 写成黑盒函数，而是在关键生命周期点发出 public events；hooks 可以观察或轻量影响这些事件，trace、API、前端 run surface 都从同一条事件流投影出来。

![Klara Chapter 3 Hooks and Trace](./docs/assets/ch03-hooks-and-trace.svg)

| 看到什么 | Klara 做什么 |
| --- | --- |
| `user_prompt_submit.*` | 用户请求进入 runtime，hook 可以观察提交边界 |
| `llm.started/completed` | 模型调用开始/结束，trace 和 UI 同步更新 |
| `pre_tool_use.*` | 工具执行前的 hook placement，可以 allow/block，但不是完整权限系统 |
| `tool.started/completed/failed` | 每个工具调用有可配对的 started 和 terminal event |
| `post_tool_use.*` | 工具 observation 生成后，hook 可以观察结果 |
| `stop.*` | loop 准备停止，hook 可以做收尾观察 |
| JSONL trace | 开发者可以重放 run 的 public lifecycle |
| frontend run surface | 用户可以看到工具卡片和 runtime 状态 |

## 快速体验

启动前后端：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

先问：

```text
请使用 current_time 查询 Asia/Shanghai 当前时间，然后用一句话回答。
```

你应该看到：assistant 消息下方出现 run surface，里面有 model call、`current_time` tool card、hook placement 小标签，以及完成后的 trace 状态。

再打开：

```text
http://127.0.0.1:8011/api/runs/{run_id}
```

你应该看到同一条 run 的 API events。删除 session 后，相关 messages、runs、events 和 JSONL trace 行也会被清理。

## 1. Chapter 3 改变了什么

Chapter 2 的工具 loop 已经能运行：

```text
模型提出 tool_calls
-> runtime 执行工具
-> observation 回到下一轮模型上下文
```

第三章不重写这个 loop。它新增的是 lifecycle event stream：

```text
KlaraLoop
-> public KlaraEvent
-> HookManager
-> JsonlTraceHook / RunEventProjector / frontend run surface
```

Klara 学到：如果想观察或轻量影响 runtime 行为，不应该把所有逻辑塞进 loop 主体；应该在稳定 placement 上挂 hook，在稳定 public event 上做 trace 和 UI projection。

对应代码：

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
```

## 2. Public event 是共同事实源

`KlaraEvent` 是 trace、API、UI 的共同事实源。它包含：

```text
schema_version
event_id
seq
type
run_id
timestamp
payload
private_payload_ref
```

`seq` 在单个 run 内从 1 开始单调递增。`payload` 保持旧调用兼容，但新的公共边界由 `public_payload` 表达。工具结果只公开 compact preview 和长度概念，避免 UI 直接展示超长工具正文。

对应代码：

```text
src/klara/core/events.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

读者 takeaway：public event 不是“随便打日志”，而是可重放、可投影、可测试的 runtime contract。

## 3. Hooks 是 lifecycle extension point，不是工具

本章有两类 hook 行为：

```text
observer hook
-> on_event(event)
-> 只观察，不改变 loop

placement hook
-> on_user_prompt_submit / on_pre_tool_use / on_post_tool_use / on_stop
-> 在固定生命周期位置观察或轻量决策
```

PreToolUse 可以 block 当前工具调用，但这仍然不是完整 permission engine。block 的结果是：

```text
pre_tool_use.completed allowed=false
tool.failed blocked=true
failed observation 进入下一轮模型上下文
```

它不会打开审批 UI、等待人工确认、写长期策略或改变工具注册表。

对应代码：

```text
src/klara/core/hooks.py
src/klara/core/loop.py
tests/klara/core/test_hooks.py
```

## 4. Tool lifecycle 可以精确配对

每个 tool call 都有可教学的事件语义：

```text
成功工具       -> one tool.started + one tool.completed
未知工具       -> one tool.started + one tool.failed
工具异常       -> one tool.started + one tool.failed
PreToolUse block -> zero tool.started + one tool.failed
policy stop     -> pending call 不产生 tool.started
```

这让 run surface 能可靠地画 tool cards，也让 trace replay 不需要猜测某个工具到底有没有执行。

对应代码：

```text
src/klara/core/loop.py
src/klara/tools/executor.py
tests/klara/core/test_loop.py
```

## 5. Trace 和 frontend 是两种 projection

JSONL trace 是开发者视角：

```json
{
  "schema_version": 1,
  "event_id": "evt_...",
  "seq": 7,
  "type": "tool.completed",
  "run_id": "run_...",
  "payload": {
    "tool_result": {
      "name": "current_time",
      "ok": true,
      "content_preview": "...",
      "content_length": 128
    }
  }
}
```

API/SSE 是产品视角：

```text
llm.started         -> llm_call_started
tool.started        -> tool_call_started
tool.failed         -> tool_call_failed
pre_tool_use.*      -> hook_placement_*
tool_policy.stopped -> policy_stop
```

前端 run surface 是用户视角：

```text
compact lifecycle timeline
tool cards
hook badges
trace saved state
optional workstream note
```

对应代码：

```text
apps/api/services/run_event_projector.py
apps/api/services/app_store.py
apps/api/services/run_service.py
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
```

## 6. Optional narrator 只是 capstone

Narrator model 默认关闭，只位于 API/app projection 层。它不能写入 assistant content，不能进入主模型后续 messages，也不能展示 raw chain-of-thought。

它只能基于真实 run events 生成短 note：

```text
workstream_note
-> text
-> source=narrator_model
-> phase
-> evidence_event_ids
```

如果它声称搜索、读取、运行、验证或修改，recent events 必须有证据。无证据、JSON 无效、重复、过长或出现 hidden reasoning 语言时，note 会被忽略。

对应代码：

```text
apps/api/services/workstream_narrator.py
src/klara/prompts/workstream_narrator.md
tests/apps/api/test_workstream_narrator.py
```

## 本章不做什么

第三章不包括：

- complete permission engine
- Todo Planning
- agent task ledger
- context compression
- memory write policy
- full harness/config refactor
- full provider streaming adapter
- OpenAI/Claude/DeepSeek reasoning stream integration
- raw chain-of-thought display

Todo 属于 Chapter 5。RAG/module pipeline 属于后续章节。Thinking-like narrator 只是一层 evidence-bound runtime note，不是第三章主线。

## 代码索引

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
apps/api/services/run_event_projector.py
apps/api/services/app_store.py
apps/api/services/run_service.py
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
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

建议手动观察：

1. 启动 `.\scripts\dev.ps1`。
2. 问 `current_time` 问题。
3. 在 run surface 看 tool card 和 hook badges。
4. 打开 `/api/runs/{run_id}` 看 events。
5. 删除 session，确认相关 trace 被清理。

## 小实验

1. 写一个只实现 `on_event` 的 hook，确认它收到 lifecycle events。
2. 写一个 `on_pre_tool_use` 返回 `allowed=False` 的 hook，确认工具没有执行但模型看到 failed observation。
3. 人为让 hook 抛异常，确认 run 仍然完成。
4. 打开 JSONL trace，按 `seq` 重放一条 run。

## 下一章预告

Chapter 4 会讲 Harness And Config：现在 loop、tools、hooks 和 trace 都有了边界，下一步是把 provider、model、prompt、tools、hooks 和 trace sink 的组装放到一个清楚的 harness 入口里。
