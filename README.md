# Chapter 1: Minimal LLM Loop

语言：中文 | [English](./README.en.md)

上一章：无  
下一章：Chapter 2: Tool Calling
总路线：[Klara Roadmap](./docs/skills/roadmap.md)

---

## 一句话看懂本章

Klara 从一次性 pipeline 变成最小 loop：模型要工具，runtime 执行工具并继续；模型不要工具，loop 停止并返回答案。

![Klara Chapter 1 Minimal LLM Loop](./docs/assets/ch01-minimal-loop.png)

| 看到什么 | Klara 做什么 |
| --- | --- |
| 有 `tool_calls` | 执行工具，把结果放回上下文，继续下一轮 |
| 没有 `tool_calls` | 返回最终答案，停止 |
| 达到 `max_turns` | 按 policy 停止，并展示停止原因 |

## 快速体验

准备好 `.env` 后，一次性启动后端和前端：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

先问：

```text
用一句话介绍你自己。
```

你应该看到：模型直接回答，本次 run 结束。

再问：

```text
请使用 debug_echo 工具回显 klara-loop，然后告诉我你看到了什么。
```

你应该看到：模型请求 `debug_echo`，runtime 执行工具，把 observation 放回上下文，然后进入下一轮或返回最终答案。

## 为什么从 loop 开始

旧路线里的 pipeline 更像一条固定路径：

```text
question -> retrieve -> prompt -> answer
```

Klara 要从第一章开始学会“运行一轮、观察结果、决定继续还是停止”。这也是后面 tool registry、RAG、memory、hooks、context compression、RL 都会挂上的骨架。

Klara 学到：一次 agent run 不是黑盒模型调用，而是一个可观察、可测试、可继续、可停止的运行循环。

---

## 1. Harness 先组装一次运行

Core loop 不读取环境变量，不决定 persona，不关心前端和存储路径。
这些由 app 层 harness 组装好，再注入给 loop。

```text
user input
-> KlaraHarness
-> persona + model + tools + hooks + policy
-> KlaraLoop
```

Klara 学到：core 只负责执行运行逻辑，app 层负责把运行世界组装好。

对应代码：

```text
src/klara/app/harness.py
```

<details>
<summary>展开：harness 如何把 trace hook 和工具注入 loop</summary>

真实代码：

```python
# Hooks are built per run so trace sinks do not leak across executions.
hooks = HookManager()
if self.config.trace_path is not None:
    hooks.register(JsonlTraceHook(self.config.trace_path))

# The harness converts visible capabilities into the core executor boundary.
loop = KlaraLoop(
    llm=self.llm,
    tool_executor=ToolExecutor(list(self.registry.visible_tools())),
    hooks=hooks,
    policy=LoopPolicy(max_turns=self.config.max_turns),
    model=self.config.model,
    system_prompt=self._system_prompt(),
)
return loop.run(user_input, run_id=run_id)
```

这段代码做了三件事：

- 创建本次运行的 `HookManager`
- 如果配置了 trace path，就注册 `JsonlTraceHook`
- 把 LLM、工具、hooks、policy、model 和 system prompt 注入 `KlaraLoop`

重点是：`KlaraLoop` 没有自己读取 `.env`，没有自己创建 trace 文件，也没有自己选择工具。它只接收已经准备好的依赖。

</details>

## 2. Loop 接收依赖，不自己创建世界

`KlaraLoop` 是运行核心，但不是产品入口。它只保存依赖，然后在 `run()` 里执行 loop。

```text
llm + tool_executor + hooks + policy + model + system_prompt
-> KlaraLoop
```

Klara 学到：loop 要小，依赖要显式注入。

对应代码：

```text
src/klara/core/loop.py
```

<details>
<summary>展开：KlaraLoop.__init__ 逐行精读</summary>

真实代码：

```python
def __init__(
    self,
    *,
    llm: LlmClient,
    tool_executor: ToolExecutor,
    hooks: HookManager | None = None,
    policy: LoopPolicy | None = None,
    model: str = "fake-model",
    system_prompt: str = "",
) -> None:
```

每个参数的含义：

- `llm`：真正调用模型的客户端。
- `tool_executor`：执行模型请求的工具。
- `hooks`：runtime 生命周期事件出口，trace 和前端事件都从这里挂。
- `policy`：loop 边界，例如最大轮数。
- `model`：本次 run 使用的模型。
- `system_prompt`：Klara 的身份和行为约束。

真实代码：

```python
# Dependencies are injected so core stays independent of providers/services.
self.llm = llm
self.tool_executor = tool_executor
self.hooks = hooks or HookManager()
self.policy = policy or LoopPolicy()
self.model = model
self.system_prompt = system_prompt
```

这里的重点不是赋值本身，而是边界：

- provider 不在 core 里创建
- trace sink 不在 core 里创建
- frontend bridge 不在 core 里创建
- tool list 不在 core 里发现

</details>

## 3. Run 从一个用户消息开始

一次 run 的第一步不是调用模型，而是创建稳定的运行身份和第一条消息。

```text
user_input
-> run_id
-> [KlaraMessage(role="user")]
-> run.started event
```

Klara 学到：trace、前端事件、测试断言都需要同一个 `run_id` 作为连接点。

对应代码：

```text
src/klara/core/loop.py
src/klara/core/messages.py
src/klara/core/events.py
```

<details>
<summary>展开：run() 的开头</summary>

真实代码：

```python
# Active run id is the trace join key across all lifecycle events.
active_run_id = run_id or str(uuid4())
# Messages begin with exactly one user message; later turns append to it.
messages: list[KlaraMessage] = [KlaraMessage(role="user", content=user_input)]
self._emit(active_run_id, "run.started", {"model": self.model})
```

逐行看：

- `active_run_id` 是本次运行的唯一标识。
- 如果测试或 API 已经传入 `run_id`，就复用它。
- 如果没有传入，就生成新的 UUID。
- `messages` 从一条 user message 开始。
- `run.started` 不是直接写 log，而是发给 hook manager。

所以 trace 不是 loop 里的硬编码日志。loop 只发事件，真正写 JSONL 的是 `JsonlTraceHook`。

</details>

## 4. 每一轮都先调用 LLM

每一轮 loop 都会把当前消息、system prompt、工具 schema 和 model id 交给 LLM client。

```text
system_prompt + messages + tool specs + model
-> llm.complete(...)
-> ModelResponse(content, tool_calls)
```

Klara 学到：LLM 调用是 loop 的一个步骤，不是整个 agent。

对应代码：

```text
src/klara/core/loop.py
src/klara/core/messages.py
src/klara/infra/llm/openai_compatible.py
```

<details>
<summary>展开：LLM 调用代码</summary>

真实代码：

```python
self._emit(active_run_id, "turn.started", {"turn_index": turn_index})
self._emit(active_run_id, "llm.started", {"turn_index": turn_index})
# Ask the injected model using only the prompt, transcript, and specs.
response = self.llm.complete(
    system_prompt=self.system_prompt,
    messages=tuple(messages),
    tools=self.tool_executor.specs,
    model=self.model,
)
```

传进去的内容是：

- `system_prompt`：Klara 应该如何说话、如何保持人设和边界。
- `messages`：目前为止的可见 transcript。
- `tools`：模型可以看到的工具声明。
- `model`：本次选择的模型。

LLM client 返回 `ModelResponse`。它可能包含最终文本，也可能包含 tool calls。

</details>

## 5. `tool_calls` 决定继续还是停止

这是 Chapter 1 最核心的判断：

```text
response.tool_calls?
-> yes: execute tools, append observations, continue
-> no: final answer, stop
```

Klara 学到：模型只能请求工具，真正执行工具的是 runtime。

对应代码：

```text
src/klara/core/loop.py
src/klara/core/tool_executor.py
src/klara/capabilities/tools/fake_tool.py
```

<details>
<summary>展开：tool call 如何变成 observation</summary>

真实代码：

```python
if not response.tool_calls:
    # No tool calls means the assistant content is the final answer.
    self._emit(active_run_id, "turn.completed", {"turn_index": turn_index})
    return self._complete(
        active_run_id,
        messages,
        response.content,
        StopReason.FINAL,
    )
```

如果没有 `tool_calls`，loop 直接结束。

如果有 `tool_calls`，runtime 执行每一个工具：

```python
# Execute every requested tool before preparing the next model turn.
for call in response.tool_calls:
    self._emit(
        active_run_id,
        "tool.started",
        {"turn_index": turn_index, "tool_call": call.to_public_dict()},
    )
    # Tool results become model-visible observations.
    result = self.tool_executor.execute(call)
    self._emit(
        active_run_id,
        "tool.completed",
        {
            "turn_index": turn_index,
            "tool_result": result.to_public_dict(),
        },
    )
    messages.append(
        KlaraMessage(
            role="tool",
            name=result.name,
            tool_call_id=result.tool_call_id,
            content=result.content if result.ok else result.error or "",
        )
    )
```

关键状态变化：工具结果被追加成一条 `role="tool"` 的消息。它不是隐藏变量，而是下一轮 LLM 能看到的 observation。

</details>

## 6. prepare_next_turn 先保持最小

第一章的 `prepare_next_turn` 只做 identity：不压缩、不改写、不注入 memory。
但这个边界必须现在就出现，因为后面 context compression、memory、RAG 和 tool effects 都会挂在这里。

```text
messages
-> prepare_next_turn(messages)
-> messages for next LLM turn
```

Klara 学到：下一轮上下文需要一个明确的准备阶段。

对应代码：

```text
src/klara/core/loop.py
```

<details>
<summary>展开：prepare_next_turn 的最小版本</summary>

真实代码：

```python
# The minimal loop keeps preparation as identity until context policy exists.
self._emit(
    active_run_id,
    "prepare_next_turn.started",
    {"turn_index": turn_index},
)
messages = self.prepare_next_turn(messages)
self._emit(
    active_run_id,
    "prepare_next_turn.completed",
    {"turn_index": turn_index, "message_count": len(messages)},
)
self._emit(active_run_id, "turn.completed", {"turn_index": turn_index})
```

这一章暂时不做压缩，但事件已经存在。后面加 context compression 时，不需要重写 loop 的基本结构。

</details>

## 7. Loop 必须说明为什么停止

Klara 不能只是“跑完了”。她要知道为什么停。

```text
no tool calls -> StopReason.FINAL
max turns -> StopReason.MAX_TURNS
unexpected error -> run.failed
```

Klara 学到：停止是 runtime policy 的一部分。

对应代码：

```text
src/klara/core/loop.py
src/klara/core/policies.py
```

<details>
<summary>展开：final 和 max turns 怎么结束</summary>

如果模型一直请求工具，超过最大轮数时，loop 用 `max_turns` 停止：

```python
# At max turns, expose the last visible content and explicit stop reason.
final_answer = messages[-1].content if messages else ""
return self._complete(
    active_run_id,
    messages,
    final_answer,
    StopReason.MAX_TURNS,
)
```

完成时，loop 仍然只是发事件：

```python
self._emit(run_id, "run.completed", {"stop_reason": stop_reason.value})
```

所以停止原因会进入 trace，也会进入最终 `KlaraRunResult`。

</details>

## 8. Hook 是 trace 和 UI 的挂点

这一章的 hook 先只做 observer：hook 接收事件，但不改变 loop 行为。

```text
KlaraLoop._emit(...)
-> HookManager.emit(event)
-> JsonlTraceHook.on_event(event)
-> frontend bridge on_event(event)
```

Klara 学到：trace 不是写死的 log，而是 hook 的第一个实现。

对应代码：

```text
src/klara/core/events.py
src/klara/core/hooks.py
apps/api/services/run_service.py
tests/klara/core/test_hooks.py
```

<details>
<summary>展开：HookManager 和 JsonlTraceHook</summary>

真实代码：

```python
class KlaraHook(Protocol):
    """Protocol for observers or guards attached to loop lifecycle events."""

    def on_event(self, event: KlaraEvent) -> None:
        """Handle one loop event."""

        ...
```

第一章只使用 observer hook。后面才会引入 `PreToolUse`、`PostToolUse`、`Stop` 这种更接近 Claude Code / claw-code 的生命周期 hook。

真实代码：

```python
def emit(self, event: KlaraEvent) -> None:
    """Send an event to every hook and record hook-level failures."""

    # Visit hooks sequentially so trace and policy hooks see stable order.
    for hook in self._hooks:
        try:
            hook.on_event(event)
        except Exception as exc:  # pragma: no cover - exact hook errors vary
            # Hook failures are runtime observations, not loop failures.
            self.failures.append((event.type, f"{type(exc).__name__}: {exc}"))
```

hook 失败不会让 loop 崩掉，它会被记录成 hook failure。

真实代码：

```python
class JsonlTraceHook:
    """Persist public lifecycle events as newline-delimited JSON."""

    def on_event(self, event: KlaraEvent) -> None:
        """Append one public event to the JSONL trace file."""

        # Ensure local trace directories exist before appending the event.
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(event.to_public_dict(), ensure_ascii=False) + "\n")
```

这就是本章的核心原则：

```text
loop emits events
hook consumes events
trace is one hook implementation
```

前端事件也是同一个思路。API 层把 `_RunEventBridge` 和 `JsonlTraceHook` 一起挂进 `HookManager`：

```python
usage_totals = _UsageTotals()
bridge = _RunEventBridge(self, run_id, usage_totals)
hooks = HookManager([bridge, JsonlTraceHook(Path(self.trace_path))])
```

</details>

## 9. 真实 LLM 配置放在 infra，不放在 core

Chapter 1 已经可以使用真实模型，但 provider 仍然在 infra 层。Core 只知道 `LlmClient` 协议。

```text
.env
-> config/models.toml
-> RoutedLlmClient
-> OpenAICompatibleLlmClient
-> KlaraLoop
```

Klara 学到：DeepSeek 和 Qwen 是可替换 provider，不是 loop 的一部分。

对应代码：

```text
config/models.toml
config/README.md
src/klara/infra/llm/openai_compatible.py
src/klara/infra/llm/routed_client.py
```

<details>
<summary>展开：为什么真实 LLM 不改变 loop</summary>

core loop 只需要这个能力：

```text
complete(system_prompt, messages, tools, model) -> ModelResponse
```

DeepSeek、Qwen 或未来其他 provider 都应该适配到这个协议，而不是让 `KlaraLoop` 知道：

- API key
- base URL
- provider name
- HTTP response shape
- retry strategy
- model routing

本章当前需要的 key 是：

```text
DEEPSEEK_API_KEY
DASHSCOPE_API_KEY
```

当前 chat models 在 `config/models.toml`：

```text
deepseek/deepseek-v4-flash
deepseek/deepseek-v4-pro
qwen/qwen3.6-flash
qwen/qwen3.6-plus
```

Qwen image model 已经放在 `config/images.toml`，但本章不把生图接入 loop。以后它应该作为 tool 或 capability 进入，而不是混进 chat model picker。

</details>

## 如何运行和验证

1. 安装 Python 依赖

```powershell
python -m pip install -e ".[dev]"
```

2. 在仓库根目录创建 `.env`

```powershell
Copy-Item .env.example .env
```

3. 填入自己的 key

```text
DEEPSEEK_API_KEY=...
DASHSCOPE_API_KEY=...
```

4. 一次性启动后端和前端

```powershell
.\scripts\dev.ps1
```

默认地址：

```text
API: http://127.0.0.1:8011
Web: http://127.0.0.1:5123
```

5. 运行核心测试

```powershell
python -m pytest tests\klara\core\test_hooks.py tests\klara\app\test_harness.py
```

这些测试确认：

- hook failure 不会打断 loop
- JSONL trace 是通过 hook 写出的
- harness 能组装 persona、tools、user context 和 trace hook

## 小实验

- 把 `KlaraHarnessConfig.max_turns` 调小，再观察 `StopReason.MAX_TURNS`。
- 问模型明确使用 `debug_echo`，观察右侧事件里 `tool.started` 和 `tool.completed` 的顺序。
- 打开本地 trace JSONL，确认同一个 `run_id` 串起 `run.started`、`llm.completed`、`tool.completed` 和 `run.completed`。

## 下一章预告

Chapter 2 会把本章的最小工具路径升级成完整的 tool calling：工具包目录、schema、metadata、registry、executor、串并行执行和错误 observation。

Klara 会继续学习：

- 如何把 tool schema 暴露给 LLM
- 如何让 runtime 执行 tool call
- 如何把 tool result 作为 observation 放回下一轮
- 如何从一组 registry 工具中选择本章可见工具
- 如何记录 tool selection、tool start、tool result 和 tool error

Chapter 1 的原则会保留：loop 只拥有运行结构，能力通过边界接入，trace 通过 hook 观察。
