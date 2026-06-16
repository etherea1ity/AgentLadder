# Chapter 1: Minimal LLM Loop

语言：中文 | [English](./README.en.md)

上一章：无  
下一章：Chapter 2: Tool Calling, Registry, And Capability Partitioning  
总路线：[Klara Roadmap](./docs/skills/roadmap.md)

---

## 本章主要内容

这一章让 Klara 拥有最小可运行的 LLM loop。

她可以接收用户输入，调用真实 LLM，判断模型是否请求工具，执行工具，把工具结果放回下一轮上下文，并通过 hook 记录公共 trace。

本章重点：

- LLM 如何被调用
- loop 如何组织多轮运行
- tool call 如何进入下一轮上下文
- hook 为什么是 trace 和前端事件的挂点
- harness 为什么负责组装运行，而不是让 core loop 读取配置

这一章不做完整 agent，不做 RAG，不做 memory，不做复杂 permission，也不做 RL。它只建立以后所有能力都会挂上的运行骨架。

![Klara Chapter 1 Minimal LLM Loop](./docs/assets/ch01-minimal-loop.png)

## Loop 思想

旧的 pipeline 更像一次固定流程：

```text
question
-> retrieve
-> prompt
-> answer
```

Klara 要从第一章开始变成 loop：

```text
user input
-> harness assembles dependencies
-> loop emits run.started
-> LLM call
-> if tool calls exist, execute tools
-> append tool observations
-> prepare next turn
-> stop with final answer or max turns
-> hooks receive public lifecycle events
```

输入：

- 用户消息
- Klara system prompt
- model id
- visible tools
- hook manager
- loop policy

输出：

- final answer
- stop reason
- transcript messages
- public trace events

Klara learns: 一次 agent run 不是黑盒模型调用，而是一个可观察、可测试、可继续、可停止的运行循环。

## 代码地图

核心 loop：

```text
src/klara/core/loop.py
```

消息、工具、事件、hook：

```text
src/klara/core/messages.py
src/klara/core/tools.py
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/tool_executor.py
src/klara/core/policies.py
```

app 层组装：

```text
src/klara/app/harness.py
apps/api/services/run_service.py
```

真实 LLM provider：

```text
config/models.toml
src/klara/infra/llm/openai_compatible.py
src/klara/infra/llm/routed_client.py
```

配置与运行：

```text
.env.example
config/README.md
scripts/dev.ps1
```

---

## 1. Harness 先组装一次运行

core loop 不应该知道环境变量、前端、存储路径、用户配置或产品 persona。  
这些由 harness 组装好，再注入给 loop。

```text
user input
-> KlaraHarness
-> persona + model + tools + hooks + policy
-> KlaraLoop
```

Klara learns: core 只负责执行运行逻辑，app 层负责把运行世界组装好。

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

重点是：`KlaraLoop` 没有自己读取 `.env`，没有自己创建 trace 文件，也没有自己选择工具。  
它只接收已经准备好的依赖。

</details>

## 2. Loop 接收依赖，不自己创建世界

Klara 的 core loop 是运行核心，但它不是产品入口。它只接收依赖，然后执行 loop。

```text
llm + tool_executor + hooks + policy + model + system_prompt
-> KlaraLoop
```

Klara learns: loop 要小，依赖要显式注入。

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

core loop 只保存这些依赖，等待 `run()` 开始执行。

</details>

## 3. Run 从一个用户消息开始

一次 run 的第一步不是调用模型，而是创建稳定的运行身份和第一条消息。

```text
user_input
-> run_id
-> [KlaraMessage(role="user")]
-> run.started event
```

Klara learns: trace、前端事件、测试断言都需要同一个 `run_id` 作为连接点。

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

所以 trace 不是 loop 里的硬编码日志。  
loop 只发事件，真正写 JSONL 的是后面的 `JsonlTraceHook`。

</details>

## 4. Loop 调用 LLM

每一轮 loop 都会把当前消息、system prompt、工具 schema 和 model id 交给 LLM client。

```text
system_prompt + messages + tool specs + model
-> llm.complete(...)
-> ModelResponse
```

Klara learns: LLM 调用是 loop 的一个步骤，不是整个 agent。

对应代码：

```text
src/klara/core/loop.py
src/klara/core/types.py
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

这里有两个重要事件：

- `turn.started`：一轮开始。
- `llm.started`：准备调用模型。

然后调用 `self.llm.complete(...)`。

传进去的内容是：

- `system_prompt`：Klara 应该如何说话、如何保持人设和边界。
- `messages`：目前为止的可见 transcript。
- `tools`：模型可以看到的工具声明。
- `model`：本次选择的模型。

LLM client 返回 `ModelResponse`。它可能包含最终文本，也可能包含 tool calls。

</details>

## 5. 如果模型请求工具，runtime 执行工具

模型不能自己执行工具。它只能发出 tool call。  
真正执行工具的是 runtime 的 `ToolExecutor`。

```text
ModelResponse.tool_calls
-> ToolExecutor.execute(call)
-> ToolResult
-> tool observation message
```

Klara learns: tool 是 runtime 能力，不是模型魔法。

对应代码：

```text
src/klara/core/tools.py
src/klara/core/tool_executor.py
src/klara/capabilities/tools/fake_tool.py
```

<details>
<summary>展开：tool call 如何变成 observation</summary>

真实代码：

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

逐步看：

- `tool.started` 先发出，trace 和前端可以知道工具开始执行。
- `ToolExecutor.execute(call)` 执行工具。
- `tool.completed` 发出工具结果。
- 工具结果被追加成一条 `role="tool"` 的消息。

这一步很关键：工具结果不是隐藏变量。  
它会作为 observation 回到消息列表，让下一轮 LLM 能看到。

</details>

## 6. prepare_next_turn 先保持最小，但边界已经存在

第一章的 `prepare_next_turn` 只做 identity，也就是不压缩、不改写、不注入 memory。  
但这个边界必须现在就出现，因为后面 context compression、memory、RAG 和 tool effects 都会挂在这里。

```text
messages
-> prepare_next_turn(messages)
-> messages for next LLM turn
```

Klara learns: 下一轮上下文需要一个明确的准备阶段。

对应代码：

```text
src/klara/core/loop.py
```

<details>
<summary>展开：prepare_next_turn 的最小版本</summary>

真实代码：

```python
# Chapter 1 keeps preparation as identity; compression arrives later.
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

这一章暂时不做压缩，但事件已经存在：

- `prepare_next_turn.started`
- `prepare_next_turn.completed`
- `turn.completed`

后面章节加 context compression 时，不需要重写 loop 的基本结构，只需要让 `prepare_next_turn` 真正开始处理消息。

</details>

## 7. Loop 必须明确停止原因

Klara 不能只是“跑完了”。她要知道为什么停。

```text
no tool calls -> final answer
max turns -> max_turns stop reason
unexpected error -> run.failed
```

Klara learns: 停止是 runtime policy 的一部分。

对应代码：

```text
src/klara/core/loop.py
src/klara/core/policies.py
```

<details>
<summary>展开：final 和 max turns 怎么结束</summary>

当模型没有请求工具时，loop 把当前内容当作最终回答：

```python
if not response.tool_calls:
    return self._complete(
        active_run_id,
        messages,
        response.content,
        StopReason.FINAL,
    )
```

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

这一章的 hook 先只做 observer。  
也就是说，hook 接收事件，但不改变 loop 行为。

```text
KlaraLoop._emit(...)
-> HookManager.emit(event)
-> JsonlTraceHook.on_event(event)
-> frontend bridge on_event(event)
```

Klara learns: trace 不是写死的 log，而是 hook 的第一个实现。

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

第一章只使用 observer hook。  
后面才会引入 `PreToolUse`、`PostToolUse`、`Stop` 这种更像 claw-code / learn-claude-code 的生命周期 hook。

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

hook 失败不会让 loop 崩掉。  
它会被记录成 hook failure。

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

所以 JSONL trace 和前端 SSE 不是两套 runtime。  
它们都是同一批 lifecycle events 的不同消费者。

</details>

## 9. 真实 LLM 配置放在 infra，不放在 core

Chapter 1 已经可以使用真实模型，但 provider 仍然在 infra 层。  
core 只知道 `LlmClient` 协议。

```text
.env
-> config/models.toml
-> RoutedLlmClient
-> OpenAICompatibleLlmClient
-> KlaraLoop
```

Klara learns: DeepSeek 和 Qwen 是可替换 provider，不是 loop 的一部分。

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

Qwen image model 已经放在 `config/images.toml`，但本章不把生图接入 loop。  
以后它应该作为 tool 或 capability 进入，而不是混进 chat model picker。

</details>

---

## 本章暂时不做什么

这一章不做：

- RAG
- memory
- context compression
- skill registry
- scheduled jobs
- permission guard
- complex Stop hook
- RL / post-training
- multi-user auth

这些都重要，但不能塞进 Chapter 1。  
Chapter 1 只负责建立 Klara 的最小运行骨架。

## 如何运行和验证

1. 在仓库根目录创建 `.env`

```powershell
Copy-Item .env.example .env
```

2. 填入自己的 key

```text
DEEPSEEK_API_KEY=...
DASHSCOPE_API_KEY=...
```

`DEEPSEEK_API_KEY` 用于 DeepSeek chat models。  
`DASHSCOPE_API_KEY` 用于 Qwen chat models，也会供未来 Qwen image capability 使用。

3. 一次性启动后端和前端

```powershell
.\scripts\dev.ps1
```

默认地址：

```text
API: http://127.0.0.1:8011
Web: http://127.0.0.1:5123
```

4. 打开前端，选择模型，发送一条消息

前端会调用后端 API，后端会运行 `KlaraLoop`，并把生命周期事件投射到前端。  
同时，`JsonlTraceHook` 会把公共 trace 写到本地 JSONL。

5. 运行核心测试

```powershell
python -m pytest tests\klara\core\test_hooks.py tests\klara\app\test_harness.py
```

这些测试确认：

- hook failure 不会打断 loop
- JSONL trace 是通过 hook 写出的
- harness 能组装 persona、tools、user context 和 trace hook

## 下一章预告

Chapter 2 会把本章的最小工具路径，升级成真正的 tool calling 和 capability partitioning。

Klara 会学会：

- 如何把 tool schema 暴露给 LLM
- 如何让 runtime 执行 tool call
- 如何把 tool result 作为 observation 放回下一轮
- 如何从一组 registry 工具中选择本章可见工具
- 如何记录 tool selection、tool start、tool result 和 tool error

Chapter 1 的原则会继续保留：  
loop 只拥有运行结构，能力通过边界接入，trace 通过 hook 观察。
