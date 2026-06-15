# Chapter 1 - Minimal Agent Loop

Klara 的第一章只做一件事：把她从 pipeline 重新变成 loop。

这一章不是在做完整 agent，也不是在做 RAG、memory、skills 或前后端。
它只建立以后所有能力都会挂上的最小运行心跳：

```text
UserMessage
-> KlaraLoop
-> LLM turn
-> optional ToolCall
-> ToolResult / Observation
-> prepare_next_turn
-> FinalAnswer or StopReason
-> JSONL Trace
```

Klara learns: 一次运行必须是可继续、可观察、可测试、可停止的循环。

Corresponding code:

```text
src/klara/core/loop.py
src/klara/core/messages.py
src/klara/core/tools.py
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/tool_executor.py
src/klara/core/policies.py
```

<details>
<summary>Expand: why Chapter 1 starts with a loop</summary>

旧路线容易把 agent 写成一条 pipeline：

```text
question -> retrieve -> prompt -> answer
```

这条线在 RAG 教程里可以工作，但它不是 Klara 的核心。Klara 后面要学习
tools、memory、skills、hooks、context compression、research、routines、eval
和 policy learning。它们不是 pipeline 上的固定步骤，而是运行时会被选择、
观察、回填、压缩、评估的能力层。

所以第一章先教 loop：

- model 可以直接回答
- model 也可以请求工具
- 工具结果必须作为 observation 回到消息列表
- loop 可以继续，也可以停止
- 每一步都产生 trace

这就是后面所有章节的地基。

</details>

## 1. Message: Klara 能看见什么

本章只有三种 message：`user`、`assistant`、`tool`。

```text
user input
-> KlaraMessage
-> loop-visible transcript
```

Input: 用户输入、模型回复、工具观察。
Output: 统一的 `KlaraMessage` 列表。
Klara learns: loop 不直接处理散乱字符串，所有可见上下文都进入消息序列。

Corresponding code:

```text
src/klara/core/messages.py
tests/klara/core/test_loop.py
```

<details>
<summary>Expand: why tool result is also a message</summary>

工具结果不是隐藏变量。它必须进入 loop-visible transcript，否则模型无法在下一轮
基于 observation 做最终回答。

本章采用：

```text
assistant message with tool_calls
tool message with tool result
assistant final answer
```

这让后续 context compression、trace replay、eval、memory review 都可以读同一条
消息轨迹，而不是从多个内部状态里拼事实。

</details>

## 2. Tool Contract: Klara 怎么请求能力

工具在第一章只是一个确定性 fake tool：`debug_echo`。

```text
ToolCall
-> ToolExecutor
-> ToolResult
-> tool observation message
```

Input: tool name 和 JSON-like arguments。
Output: `ToolResult`，成功或失败都以 observation 形式回到 loop。
Klara learns: 工具失败也是可见观察，不应该让 loop 随便崩掉。

Corresponding code:

```text
src/klara/core/tools.py
src/klara/core/tool_executor.py
src/klara/capabilities/tools/fake_tool.py
tests/klara/core/test_loop.py
```

<details>
<summary>Expand: why Chapter 1 uses only one fake tool</summary>

第一章的目标不是建立工具生态，而是证明 loop 的形状：

- assistant 可以发出 tool call
- runtime 可以执行 tool
- tool result 可以回填
- model 能看到 observation 后再回答

如果这里直接加入文件工具、搜索、RAG、MCP 或 shell，就会把读者注意力带到具体能力
上，而不是 loop 本身。`debug_echo` 足够证明机制。

</details>

## 3. Loop: Klara 的最小心跳

Loop 负责执行，不负责组装世界。

```text
messages + tools + model
-> KlaraLoop.run()
-> final answer + stop reason + trace events
```

Input: 用户消息、LLM client、tool executor、hooks、policy。
Output: `KlaraRunResult`。
Klara learns: 每次运行必须有明确 stop reason。

Corresponding code:

```text
src/klara/core/loop.py
src/klara/core/policies.py
tests/klara/core/test_loop.py
```

<details>
<summary>Expand: what the loop owns and does not own</summary>

Loop owns:

- 调用模型
- 追加 assistant message
- 执行 tool calls
- 追加 tool observation
- 调用 `prepare_next_turn`
- 在 max turns 时停止
- 发出 lifecycle events

Loop does not own:

- persona prompt 怎么写
- 当前用户是谁
- 哪些工具可见
- RAG 怎么检索
- memory 怎么召回
- skills 怎么加载
- UI 怎么流式显示
- eval 怎么打分

这些属于 harness、capabilities、context、services、memory、skills、backend、
eval 或 training。保持这个边界，后面章节才不会倒灌进 core。

</details>

## 4. Hooks And Trace: 为什么第一章就要可观察

第一章只有最小 hook infrastructure，主要用途是 JSONL trace。

```text
loop lifecycle event
-> HookManager
-> JsonlTraceHook
-> trace.jsonl
```

Input: `KlaraEvent`。
Output: 一行一条 JSONL event。
Klara learns: 运行过程不是黑盒；未来 debug、UI、eval、RL 都从 trace 开始。

Corresponding code:

```text
src/klara/core/events.py
src/klara/core/hooks.py
tests/klara/core/test_hooks.py
```

<details>
<summary>Expand: why trace is not a later feature</summary>

如果 trace 到后面才加，前面的章节会反复重写：

- memory 需要知道哪些 turn 值得保存
- context compression 需要知道什么时候压缩
- RAG eval 需要知道查了什么、用了什么证据
- routines 需要知道后台任务做了什么
- policy learning 需要 trajectory

所以 trace 必须从 Chapter 1 开始。它现在很小，但事件边界已经存在。

本章 trace 不记录 hidden reasoning，不记录 secrets，不把 private prompt body 默认暴露
出去。它记录的是运行结构：run、turn、llm、tool、prepare、completion。

</details>

## 5. Harness: 谁来组装一次运行

Harness 是 app 层。它把 persona、用户上下文、工具、trace hook、policy 和模型选择组装
好，再交给 loop。

```text
KlaraHarness
-> persona + UserContext + visible tools + trace hook
-> KlaraLoop
```

Input: `user_input` 和一个 LLM client。
Output: `KlaraRunResult`。
Klara learns: core 不知道产品世界，harness 才负责运行装配。

Corresponding code:

```text
src/klara/app/harness.py
src/klara/app/user_context.py
src/klara/capabilities/registry.py
src/klara/prompts/persona.md
tests/klara/app/test_harness.py
```

<details>
<summary>Expand: why UserContext appears but auth does not</summary>

第一章需要一个最小 `UserContext`，因为后面的 memory、skills、sessions、traces、eval
都会需要稳定的分区概念。

但第一章不做账号系统：

- 不做 login
- 不做 auth
- 不做 multi-tenant database
- 不做 production session management

这就是本章的折中：提前给未来留接口，但不把 production concerns 带进第一章。

</details>

## 5.5. Real LLM Adapter: DeepSeek / Qwen 放在哪里

真实 provider 不属于 core。Klara 可以用 DeepSeek 或 Qwen，但它们必须通过 infra adapter
接到 harness，再由 harness 注入 loop。

```text
config/models.toml
-> RoutedLlmClient
-> OpenAICompatibleLlmClient
-> KlaraLoop LlmClient protocol
```

Input: `deepseek/deepseek-v4-flash` 或 `qwen/qwen3.6-flash` 这种 model ref。
Output: core 能理解的 `ModelResponse`。
Klara learns: provider 是可替换基础设施，不是 loop 的一部分。

Corresponding code:

```text
config/models.toml
src/klara/infra/config/loader.py
src/klara/infra/llm/routed_client.py
src/klara/infra/llm/openai_compatible.py
tests/klara/infra/llm/test_openai_compatible.py
tests/klara/infra/llm/test_routed_client.py
```

<details>
<summary>Expand: why real LLM support does not change core</summary>

Chapter 1 的 core 只要求一个 `LlmClient` protocol：

```text
complete(system_prompt, messages, tools, model) -> ModelResponse
```

DeepSeek、Qwen、OpenAI、Bedrock 或本地模型都应该适配到这个 protocol，而不是让
`KlaraLoop` 去知道 HTTP、API key、base URL、retry、fallback 或 provider response
格式。

这一层参考 ReAct 的本地配置：

- DeepSeek 使用 `DEEPSEEK_API_KEY`
- Qwen 使用 `DASHSCOPE_API_KEY`
- 两者都是 OpenAI-compatible chat completions
- model profile 可以指定 primary 和 fallback

本章只做 non-streaming adapter。streaming、model selection policy、更复杂 fallback、
provider-specific reasoning replay 都属于后续章节。

</details>

## 6. Architecture Boundary: core 到底能放什么

`src/klara/core` 是 runtime mechanics，不是产品层。

```text
runtime invariant
-> core
product/capability/service concern
-> outside core
```

Input: 新代码或新文件。
Output: 明确归属到 core、app、capabilities 或后续 layer。
Klara learns: 架构不是靠口头约定，而是靠文档和测试一起保护。

Corresponding code:

```text
tests/klara/architecture/test_boundaries.py
docs/architecture/klara-coding-conventions.md
```

<details>
<summary>Expand: why core has several files</summary>

`core` 现在看起来有几个文件，但它们都是 runtime invariant：

- `messages.py`: loop 看见的上下文单位
- `tools.py`: tool call/result/spec contract
- `events.py`: lifecycle event contract
- `hooks.py`: event fanout and trace hook
- `policies.py`: max turns and stop reason
- `tool_executor.py`: concrete tool execution boundary
- `loop.py`: loop execution

问题不在于文件数量，而在于责任是否滑坡。

所以本章加了白名单测试：如果以后想往 `core` 加新文件，测试会失败，迫使我们先问：

1. 它是不是 no-RAG、no-memory、no-backend 时仍然成立？
2. 它能不能不依赖 app/services/storage 独立测试？
3. 它是不是后续 layer 需要依赖的 runtime contract？

如果答案不是三个 yes，它就不属于 core。

</details>

## 7. Reading Path

按这个顺序读代码：

1. `src/klara/core/messages.py`
2. `src/klara/core/tools.py`
3. `src/klara/core/events.py`
4. `src/klara/core/hooks.py`
5. `src/klara/core/tool_executor.py`
6. `src/klara/core/policies.py`
7. `src/klara/core/loop.py`
8. `src/klara/app/harness.py`
9. `tests/klara/core/test_loop.py`
10. `tests/klara/architecture/test_boundaries.py`

Klara learns: 先读 contract，再读 execution，再读 assembly，最后读 tests。

## 8. Acceptance Criteria

Chapter 1 完成时必须满足：

- no-tool run 能返回 final answer
- one-tool run 能执行工具、回填 observation、再返回 final answer
- 模型持续请求工具时能在 max turns 停止
- unknown tool 变成 observation，不直接炸掉 loop
- hook failure 不会中断 run
- JSONL trace 能记录 run、LLM、tool、prepare、completion
- harness 能组装 persona、local `UserContext`、visible tool 和 trace hook
- `core` 不 import RAG、memory、skills、backend、eval、training
- `core` 文件集合保持显式白名单

Verification:

```text
python -m pytest
python -m compileall -q src
```

## 9. Next Chapter Bridge

下一章应该讲 Harness And Runtime Context。

Chapter 1 已经有 loop，但 runtime assembly 还很薄。下一章自然要回答：

- persona 和 runtime context 如何分层？
- chapter/profile 怎么决定可见工具？
- session message 如何加载？
- trace sink 如何选择？
- workspace/profile bootstrap 什么时候进入 prompt？

这会把 Klara 从“能跑一个 loop”推进到“能组装一次有身份、有边界、有配置的 run”。
