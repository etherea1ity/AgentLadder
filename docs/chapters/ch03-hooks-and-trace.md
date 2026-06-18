# Chapter 3: Hooks and Trace

语言：中文 | [English](./ch03-hooks-and-trace.en.md)

上一章：[Chapter 2: Tool Calling](./ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Klara 不直接把 loop 写成黑盒函数，而是在关键生命周期点发出 public events；hooks 可以观察或轻量影响这些事件，trace、API、前端 run surface 都从同一条事件流投影出来。

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

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

问一个稳定工具问题：

```text
请使用 current_time 查询 Asia/Shanghai 当前时间，然后用一句话回答。
```

你应该看到：assistant 消息下方出现 run surface，里面有 model call、`current_time` tool card、hook placement 小标签，以及完成后的 trace 状态。

然后打开 API run 详情：

```text
http://127.0.0.1:8011/api/runs/{run_id}
```

你应该看到同一条 run 的 events；删除 session 后，相关 messages、runs、events 和 JSONL trace 行也会被清理。

## 3.1 为什么 Chapter 2 的 tool loop 还不够

Chapter 2 让模型可以请求工具，runtime 可以执行工具并把 observation 放回上下文。但只做到这里，loop 仍然像一个不透明函数：

```text
user request
-> loop
-> maybe tools
-> final answer
```

当用户问“为什么它没有继续搜？”或“哪个工具被 block 了？”时，我们不能靠在 loop 里散落更多日志解决。Klara 需要一个稳定的生命周期事件层：

```text
loop emits public lifecycle events
-> hooks observe or lightly decide
-> JSONL trace stores public replay data
-> API/SSE projects user-visible events
-> frontend run surface renders tool cards and hook badges
```

对应代码：

```text
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/loop.py
apps/api/services/run_event_projector.py
apps/web/src/components/klara/KlaraRunSurface.tsx
```

读者 takeaway：第三章不是给 loop 加 UI，而是把 loop 的生命周期变成可观察、可测试、可投影的公共事件流。

## 3.2 KlaraEvent：公共生命周期事件

`KlaraEvent` 是第三章的核心契约。它把“runtime 内部发生了什么”变成稳定的 public event。

事件字段里有两个重要边界：

```text
public_payload      -> trace / API / UI 可以使用
private_payload_ref -> 未来指向私有内容的引用，不把私有内容塞进事件
```

对应代码：

```text
src/klara/core/events.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

<details>
<summary>展开：KlaraEvent 和 EventSequencer 怎么读</summary>

`EventKind` 把 public event 名称集中在一个枚举里，`EventSequencer` 给每个 run 内的事件分配单调递增的 `seq`。

```python
class EventSequencer:
    def __init__(self) -> None:
        self._next_value = 1

    def next(self) -> int:
        value = self._next_value
        self._next_value += 1
        return value

@dataclass(frozen=True)
class KlaraEvent:
    type: str | EventKind
    run_id: str
    timestamp: str = field(default_factory=lambda: datetime.now(UTC).isoformat())
    payload: dict[str, Any] = field(default_factory=dict)
    schema_version: int = 1
    event_id: str = field(default_factory=lambda: f"evt_{uuid4().hex}")
    seq: int | None = None
    public_payload: dict[str, Any] | None = None
    private_payload_ref: str | None = None

    def to_public_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "event_id": self.event_id,
            "seq": self.seq,
            "type": self.type,
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "payload": self.public_payload or {},
            **({"private_payload_ref": self.private_payload_ref} if self.private_payload_ref else {}),
        }
```

怎么读：

1. `type` 是生命周期点，例如 `tool.started` 或 `stop.completed`。
2. `run_id` 把同一次 loop 的事件串起来。
3. `event_id` 给 trace replay、API projection 和测试一个稳定 join key。
4. `seq` 是 run 内顺序；测试会确认它从 1 开始单调递增。
5. `public_payload` 是对外可见内容；如果旧代码只传 `payload`，事件会保持兼容。
6. `private_payload_ref` 只保留引用，不携带私有正文。

状态变化：loop 每次 `_emit` 都生成一个带 `event_id` 和 `seq` 的事件，hooks、trace、API projection 看到的是同一份 public event。

边界：core 可以描述工具名、tool call id、短 preview 和长度，但不应该把未来私有 payload 或超长工具正文直接推给 UI。

</details>

## 3.3 Observer hook：trace 不应该影响 loop correctness

Observer hook 是最轻的扩展点：它只接收事件，不改变 loop 决策。`JsonlTraceHook` 就是一个 observer。

```text
KlaraLoop._emit(...)
-> HookManager.emit(event)
-> JsonlTraceHook.on_event(event)
-> event.to_public_dict() 写入 JSONL
```

对应代码：

```text
src/klara/core/hooks.py
apps/api/services/app_store.py
tests/apps/api/test_app_store_delete.py
```

本章修正了 trace 格式的教学边界：JSONL 每行使用 top-level `run_id`，所以 app store 查询和 purge 也按 `record.get("run_id")` 判断。这样删除 session 时，相关 trace 行不会留下孤儿数据。

读者 takeaway：trace 是开发者视角的 public lifecycle 记录，不应该反向决定 loop 是否成功。

## 3.4 Lifecycle placement：UserPromptSubmit / PreToolUse / PostToolUse / Stop

第三章的主线不是“权限系统”，而是 placement。Klara 在关键位置给 hooks 一个稳定入口：

```text
user prompt enters runtime -> UserPromptSubmit
before a tool executes     -> PreToolUse
after tool observation     -> PostToolUse
before run completed       -> Stop
```

对应代码：

```text
src/klara/core/hooks.py
src/klara/core/loop.py
tests/klara/core/test_hooks.py
tests/klara/core/test_loop.py
```

<details>
<summary>展开：HookManager placement 的最小决策模型</summary>

本章只引入一个小的 decision 对象：

```python
@dataclass(frozen=True)
class HookDecision:
    allowed: bool = True
    reason: str = ""
    public_metadata: dict[str, object] = field(default_factory=dict)
```

`HookManager` 仍然支持 observer hook：

```python
def emit(self, event: KlaraEvent) -> None:
    for hook in self._hooks:
        try:
            hook.on_event(event)
        except Exception as exc:
            self.failures.append((event.type, f"{type(exc).__name__}: {exc}"))
```

同时它会用 `getattr` 发现可选 placement 方法：

```python
def pre_tool_use(self, context: PreToolUseContext) -> HookDecision:
    return self._decision_placement(
        "pre_tool_use",
        "on_pre_tool_use",
        context,
    )
```

怎么读：

1. 一个 hook 可以只实现 `on_event`。
2. 一个 hook 也可以额外实现 `on_pre_tool_use`。
3. 多个 PreToolUse hook 中只要有一个返回 `allowed=False`，当前 tool call 就被 block。
4. hook 自己抛异常会记录到 `HookManager.failures`，默认不 crash loop。

状态变化：placement hook 不改变 messages，除非 PreToolUse 明确 block 了一个工具；block 会产生一个 model-visible failed observation。

边界：这里不是完整 approval UI，也不是 human-in-the-loop，只是把生命周期位置打出来。

</details>

## 3.5 PreToolUse 不是 permission engine

PreToolUse 可以 `allow` 或 `block` 当前 tool call，但本章故意不实现完整权限系统。

当 hook block 一个工具时：

```text
pre_tool_use.started
pre_tool_use.completed allowed=false
tool.failed blocked=true
role="tool" failed observation 进入下一轮模型上下文
```

它不会：

```text
打开审批弹窗
等待用户确认
写入长期策略
改变工具注册表
```

这很重要。第三章只回答“在哪里可以影响生命周期行为”；完整 permission/approval 会等 MCP、外部工具、后台任务和生产风险出现后再教。

## 3.6 Tool lifecycle exactly-once

每个工具调用都要能被教学和测试清楚配对：

```text
successful tool  -> one tool.started + one tool.completed
unknown tool     -> one tool.started + one tool.failed
tool exception   -> one tool.started + one tool.failed
pre-tool blocked -> zero tool.started + one tool.failed
policy stop      -> zero tool.started for pending calls
```

对应代码：

```text
src/klara/core/loop.py
src/klara/tools/executor.py
tests/klara/core/test_loop.py
```

读者 takeaway：`tool.started` 表示工具真的开始执行；被 PreToolUse block 的工具不应该伪装成 started。

## 3.7 JSONL trace：开发者视角

JSONL trace 保存的是 public event schema，不是 UI 状态，也不是 provider hidden reasoning。

一条 trace 事件的形状是：

```json
{
  "schema_version": 1,
  "event_id": "evt_...",
  "seq": 7,
  "type": "tool.completed",
  "run_id": "run_...",
  "timestamp": "2026-06-18T...",
  "payload": {
    "turn_index": 0,
    "tool_result": {
      "name": "current_time",
      "ok": true,
      "content_preview": "...",
      "content_length": 128
    }
  }
}
```

注意 `content_preview/content_length`：trace 可以记录 compact observation，但 UI 不应该直接拿完整工具内容当展示正文。

对应代码：

```text
src/klara/core/hooks.py
apps/api/services/app_store.py
```

## 3.8 API/SSE projection：产品视角

API 不直接把所有 core event 原样推给前端。`RunEventProjector` 把 public lifecycle events 投影成产品可见的 run events：

```text
llm.started        -> llm_call_started
llm.completed      -> llm_call_completed
tool.started       -> tool_call_started
tool.completed     -> tool_call_completed
tool.failed        -> tool_call_failed
pre_tool_use.*     -> hook_placement_*
tool_policy.stopped -> policy_stop
```

对应代码：

```text
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/api/services/sse_bus.py
apps/api/schemas.py
tests/apps/api/test_run_event_projector.py
```

`RunService` 现在只保留薄 adapter：core hook 收到 `KlaraEvent`，projector 返回一个或多个 `ProjectedRunEvent`，service 再保存并通过 SSE 推送。

读者 takeaway：trace 和前端来自同一条 public event stream，但 projection 层决定什么适合给用户看。

## 3.9 Frontend run surface：用户看到工具和状态

前端第三章不是 Thinking UI，也不是 RAG module timeline。它只把 runtime public projection 展示为一个轻量 run surface：

```text
assistant label
-> KlaraRunStatus
-> KlaraRunSurface
   -> compact lifecycle timeline
   -> tool cards
   -> hook badges
   -> trace saved state
-> assistant answer markdown
```

对应代码：

```text
apps/web/src/components/ChatWorkspace.tsx
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/useKlaraRunMotion.ts
apps/web/src/types/domain.ts
apps/web/src/api/client.ts
```

`answer_delta` 仍然只更新 assistant answer。`workstream_note` 和 tool cards 不会写进 assistant message content。

## 3.10 Optional narrator：把真实 runtime events 翻译成一句自然语言说明

Narrator 是本章最后的 capstone，不是主线。它默认关闭，位于 API/app projection 层，不在 core 里。

它只能基于真实 `RunEventRecord` 生成短 note：

```json
{
  "event_type": "workstream_note",
  "payload": {
    "text": "...",
    "source": "narrator_model",
    "phase": "thinking",
    "evidence_event_ids": ["evt_..."],
    "display": {"ephemeral": false}
  }
}
```

对应代码：

```text
apps/api/services/workstream_narrator.py
src/klara/prompts/workstream_narrator.md
tests/apps/api/test_workstream_narrator.py
```

限制：

- 不进入 `MessageRecord.content`
- 不进入主模型后续 messages
- 不展示 raw chain-of-thought
- 不能声称搜索、读取、运行、验证或修改，除非 recent events 有证据
- narrator 失败不影响主 run

读者 takeaway：自然语言 runtime note 是 event projection 的体验增强，不是隐藏推理的展示。

## 3.11 本章不做什么

本章明确不做：

- complete permission engine
- Todo Planning
- agent task ledger
- context compression
- memory write policy
- full harness/config refactor
- full provider streaming adapter
- OpenAI/Claude/DeepSeek reasoning stream integration
- raw chain-of-thought display

这些能力都需要 hooks/trace 这个公共事件层作为前置基础，但不应该抢第三章的主线。

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
3. 在 run surface 里确认 tool card 和 hook badges。
4. 打开 `/api/runs/{run_id}` 看 events。
5. 删除 session，确认相关 trace 被清理。

## 小实验

1. 写一个只实现 `on_event` 的 hook，确认它收到所有 lifecycle events。
2. 写一个 `on_pre_tool_use` 返回 `allowed=False` 的 hook，确认工具没有执行但模型看到 failed observation。
3. 人为让 hook 抛异常，确认 run 仍然完成，失败只记录在 `HookManager.failures`。
4. 打开 JSONL trace，按 `seq` 重放一条 run。
5. 在前端观察 completed run 默认折叠，active run 默认展开。

## 下一章预告

Chapter 4 会讲 Harness And Config：现在 loop、tools、hooks 和 trace 都有了边界，下一步是把 provider、model、prompt、tools、hooks 和 trace sink 的组装放到一个清楚的 harness 入口里。
