# Chapter 3: Hooks and Trace

语言：中文 | [English](./ch03-hooks-and-trace.en.md)

上一章：[Chapter 2: Tool Calling](./ch02-tool-calling.md)

下一章：Chapter 4: Harness And Config

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Klara 不把一次回答藏成黑盒：loop 仍然只负责模型和工具，但每个生命周期点都会发出事件，hooks、JSONL trace、前端 Thinking、右侧活动栏和 Developer Debug 都从同一条 public event stream 投影出来。

![Klara Chapter 3 Hooks and Trace](../assets/ch03-hooks-and-trace.svg)

| 看到什么 | Klara 做什么 |
| --- | --- |
| `llm.started` | 记录本轮模型输入边界：消息数量、role 分布、prompt hash、工具 schema |
| `llm.completed` | 记录模型输出边界：是否有正文、是否有工具、是否有公开 thinking、是否有 provider reasoning |
| `tool.started/completed/failed` | 记录真实工具动作、耗时、错误和安全 observation 摘要 |
| `assistant_activity_delta` | 展示主模型自己写出的公开过程说明，不进入最终答案 |
| Developer Debug | 展示工程 trace、tokens、duration、payload，用来教学和排查 |

## 快速体验

启动：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

先问一个简单问题：

```text
你好
```

你应该看到：模型直接回答，下面的 Developer Debug 里只有一次 LLM round，没有工具。

再问一个需要工具的问题：

```text
现在上海时间几点？
```

你应该看到：模型可以发出工具调用，trace 里出现 `tool_call_started` 和 `tool_call_completed`，最终答案只包含给用户看的回答。

最后问一个需要搜索的问题：

```text
今天有什么最新新闻？
```

这类问题最适合观察 Chapter 3：如果搜索提供商返回 challenge page、工具失败、模型多轮尝试或最终答案不完整，Developer Debug 应该能让你看到失败发生在哪一层。

## 真实问题：为什么只看最终答案不够

我们在调试里遇到过几类非常典型的问题：

- 模型跑了很久，但最终答案为空或失败。
- Thinking 里出现很多重复内容，看起来像“思考”，其实是多轮公开 commentary 重复。
- 搜索工具返回 challenge page，模型却把缺证据的问题说成“无法获取”或误用候选摘要。
- 一个 run 有多次 LLM 和工具调用，但前端只让人看到最终文字，无法判断是哪一轮出错。

这些问题不能靠“再写一个固定提示词”解决。Chapter 3 的答案是：先把 runtime 轨迹看清楚。

本章不改变 Chapter 2 的核心 loop：

```text
model tool_calls -> runtime executes tools -> observations return to model
```

本章增加的是可观察性：

```text
KlaraLoop
-> KlaraEvent
-> HookManager
-> JsonlTraceHook
-> RunEventProjector
-> Thinking / Activity / Developer Debug
```

## 机制一：Hook 不改写 loop，只挂在生命周期上

Hook 有两种用途。

第一种是 observer hook，只观察事件：

```text
on_event(event)
```

第二种是 placement hook，挂在固定位置：

```text
on_user_prompt_submit
on_pre_tool_use
on_post_tool_use
on_stop
```

`PreToolUse` 可以阻止一次工具调用，但它不是完整 permission engine。当前章节只教“placement 可以影响一次生命周期动作”：如果 hook 阻止工具，runtime 会产生一个 failed tool observation，把失败反馈给下一轮模型。

对应代码：

```text
src/klara/core/hooks.py
src/klara/core/loop.py
tests/klara/core/test_hooks.py
```

<details>
<summary>展开：HookManager 如何隔离 hook failure</summary>

Hook 不能让整个 run 崩掉。`HookManager.emit()` 会顺序调用每个 hook，如果某个 hook 抛错，只记录到 `failures`：

```python
for hook in self._hooks:
    try:
        hook.on_event(event)
    except Exception as exc:
        self.failures.append((event.type, f"{type(exc).__name__}: {exc}"))
```

这个设计保护了 loop 的边界：

- loop 只发事件。
- hook 可以观察或在 placement 上给出 decision。
- hook 自己坏了，不应该吞掉用户这次回答。

读者要记住：Hook 是生命周期扩展点，不是业务规则大杂烩。

</details>

## 机制二：Trace 先记录边界，不直接 dump prompt

Chapter 3 最重要的改造是 LLM 输入/输出边界。

我们不把完整 system prompt、完整 history、用户原文或 provider raw payload 塞进 public trace。那会让 Debug 变成隐私泄露和 replay 混杂在一起。

我们记录的是 trace-safe profile。

`llm.started` 增加：

```text
input_profile:
  message_count
  role_counts
  total_content_chars
  last_message_role
  last_message_chars
  tool_result_count
  assistant_tool_call_message_count
  system_prompt_chars
  system_prompt_hash
  tool_spec_count
  tool_names
  tool_spec_hash
  public_activity_update_count
  controller_count
  finalization
```

`llm.completed` 增加：

```text
response_profile:
  content_chars
  has_content
  external_tool_call_count
  internal_activity_call_count
  tool_call_names
  tool_call_ids
  has_activity_commentary
  activity_commentary_chars
  has_provider_reasoning
  provider_reasoning_chars
```

这样我们能回答：

- 这一轮模型看到了多少历史？
- 是正常模型轮，还是 finalization 轮？
- 工具 schema 有没有暴露给模型？
- 模型返回的是 final answer、tool calls、公开 thinking，还是 provider reasoning？
- 空答案到底是模型没写 content，还是 runtime 没把 content 投影出来？

对应代码：

```text
src/klara/core/loop.py
apps/api/services/run_event_projector.py
tests/klara/core/test_loop.py
tests/apps/api/test_run_event_projector.py
```

<details>
<summary>展开：一次 LLM 输入边界如何生成</summary>

模型调用前，loop 先固定本轮真实输入：

```python
model_messages = tuple(messages)
system_prompt = self._system_prompt_for_turn(public_activity_updates)
model_tools = _model_visible_tool_specs(self.tool_executor.specs)
```

然后 `llm.started` 记录 profile：

```python
"input_profile": _llm_input_profile(
    system_prompt=system_prompt,
    messages=model_messages,
    tools=model_tools,
    public_activity_updates=public_activity_updates,
    controller_count=len(self.controllers),
)
```

注意这里没有记录 `system_prompt` 原文，也没有记录 `messages` 原文。它只记录长度、数量、role 分布、工具名和 hash。

随后模型调用复用同一份 `system_prompt / model_messages / model_tools`：

```python
response = self.llm.complete(
    system_prompt=system_prompt,
    messages=model_messages,
    tools=model_tools,
    model=self.model,
    thinking_enabled=self.thinking_enabled,
)
```

这保证 trace 里的 profile 和真实请求边界一致。

运行时状态变化：

```text
messages 不变
tools 不变
trace 新增 llm.started
LLM 收到与 trace profile 对应的输入边界
```

</details>

<details>
<summary>展开：一次 LLM 输出边界如何生成</summary>

模型返回后，loop 先把工具调用分成两类：

```python
prepared_calls = _prepare_tool_calls(response.tool_calls)
```

其中 `update_activity` 是内部公开 thinking 工具，不会被当成外部工具执行；其他工具才进入 runtime executor。

然后 `llm.completed` 写入输出 profile：

```python
"response_profile": _llm_response_profile(
    response=response,
    prepared_calls=prepared_calls,
    activity_payload=activity_payload,
)
```

这个 profile 不记录正文原文，只记录：

- content 有多长
- 是否有 content
- 外部工具数量
- 内部 activity 工具数量
- 工具名和 tool_call id
- 是否有公开 commentary
- 是否有 provider reasoning

它解决了一个很实际的问题：如果 UI 没显示答案，我们可以先看 `has_content` 和 `content_chars`。如果模型本身没返回正文，那是模型/工具轮问题；如果模型返回了正文但 UI 没展示，那是投影或前端问题。

</details>

## 机制三：Thinking、Activity、Debug 分开

Klara 的用户可见链路分三条。

### A. Provider reasoning

来源是 provider/model 原生字段，例如：

```text
reasoning_content
reasoning
thinking
```

有就展示，没有不伪造。它不进入 final answer，也不进入下一轮模型 history。

### B. Main model public commentary

这是主模型自己写出的公开过程说明。来源可以是：

- `content + tool_calls` 里的 `content`
- `activity_commentary / public_activity / commentary`
- 内部 `update_activity` 工具

它是 Thinking 的主要来源之一，但不是 hidden chain-of-thought。它可以说“我会先查公开来源”，但不能冒充已经查过。

### C. Runtime action transcript

这是 runtime 真实发生的动作：

```text
web_search
web_fetch
image_generate
current_time
tool failed
```

它不是模型 thinking，而是 agent workstream。公开 Activity 里只显示安全摘要；完整参数、完整 URL、raw payload 留给 Developer Debug。

## 机制四：Developer Debug 是工程面，不是用户思考

Developer Debug 默认折叠，放在回答下方。它可以显示：

- LLM round
- token metrics
- duration / latency
- tool arguments preview
- observation preview
- raw payload
- trace saved state

这层是给开发者和教学看的。用户主路径不应该被 raw trace、tool cards、payload 淹没。

对应代码：

```text
apps/api/services/run_event_projector.py
apps/api/services/run_service.py
apps/web/src/components/klara/KlaraRunSurface.tsx
apps/web/src/components/klara/KlaraThinkingBlock.tsx
apps/web/src/components/klara/KlaraActivityDrawer.tsx
```

## 如何读一次 run

读 trace 时先按这个顺序看：

```text
run_created
thinking_started
llm_call_started
llm_call_completed
assistant_activity_delta?
tool_call_started?
tool_call_completed / tool_call_failed?
llm_call_started ...
answer_streaming_started
answer_delta...
answer_completed
run_completed
```

如果回答异常，先问四个问题：

1. `llm_call_started.input_profile.tool_names` 里有没有需要的工具？
2. `llm_call_completed.response_profile.external_tool_call_count` 是多少？
3. 工具 terminal event 是 completed 还是 failed？
4. `answer_delta` 有没有真的开始流出？

这就是 Chapter 3 的核心能力：把“感觉模型坏了”变成“哪一层出了问题”。

## 本章测试

核心测试：

```powershell
python -m pytest tests\klara\core\test_loop.py tests\apps\api\test_run_event_projector.py -q
```

全量测试：

```powershell
python -m pytest
```

本章 trace profile 改造已经验证：

```text
168 passed
```

## 本章不做什么

Chapter 3 不做：

- raw chain-of-thought 展示
- intent router
- domain guard
- 搜索关键词规则
- source ranking
- grounding verifier
- memory
- context compression
- LangGraph 迁移

这些属于后续章节。Chapter 3 只把 hook、trace、Thinking、Activity、Developer Debug 的边界立住。

## 下一章预告

Chapter 4 会讲 Harness And Config：一次 Klara run 在进入 loop 前是怎么组装出来的，包括模型选择、provider、persona、工具列表、hook 列表、trace sink 和前后端 run 创建边界。
