# Chapter 2: Tool Calling

语言：中文 | [English](./ch02-tool-calling.en.md)

上一章：[Chapter 1: Minimal LLM Loop](./ch01-minimal-agent-loop.md)
下一章：Chapter 3: Hooks And Trace
总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Chapter 1 的 loop 不变；本章只把“模型想用工具”升级成可注册、可执行、可回退、可观察的工具调用边界。

![Klara Chapter 2 Tool Calling](../assets/ch02-tool-calling.png)

| Klara 看到什么 | Runtime 做什么 |
| --- | --- |
| assistant 返回 `tool_calls` | 不直接结束，进入工具执行 |
| `tool_call.name` 在 registry 中 | 调用对应工具，并把结果包装成 `ToolResult` |
| `tool_call.name` 不存在 | 返回 failed observation，loop 不崩溃 |
| 工具参数错误或执行异常 | 返回 failed observation，让下一轮模型看到错误 |
| 工具成功 | 追加 `role="tool"` observation，继续下一轮模型调用 |
| assistant 没有 `tool_calls` | 返回最终答案，停止 |

## 快速体验

准备好 `.env` 后启动前后端：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

先用最稳定的本地工具：

```text
请使用 current_time 查询 Asia/Shanghai 当前时间，然后用一句话回答。
```

你应该看到：Klara 先请求 `current_time`，runtime 返回时间 observation，然后模型基于 observation 写最终回答。

再看工具错误如何回到模型：

```text
请使用 current_time 查询 Mars/Olympus 当前时间。
```

你应该看到：工具返回 failed observation，而不是让后端崩溃；下一轮模型会解释这个 timezone 无法识别。

最后看只读网络工具：

```text
请使用 web_search 搜索 python docs，然后用 web_fetch 打开第一条结果并总结。
```

`web_search` 只负责找到结果；`web_fetch` 才读取某个 URL 的正文。网页内容被标为不可信 observation。

也可以直接试媒体工具：

```text
请生成一张暖色调的 Klara 书桌插画，并把图片展示在回答里。
```

你应该看到：Klara 调用 `image_generate`，工具把 Qwen 返回的短期图片 URL 下载成本地资产，然后最终回答用 Markdown 把图片穿插在文字中。

---

## 1. 本章改变了什么

上一章已经有 loop：

```text
messages + tools -> LLM -> assistant message
assistant 有 tool_calls -> runtime 执行工具 -> tool observation -> 下一轮 LLM
assistant 没有 tool_calls -> final answer -> stop
```

本章不改这个循环。本章改变的是工具执行边界：

```text
hardcoded placeholder branch
-> registry lookup
-> selected tool handler
-> ToolResult observation
```

Klara 学到：模型可以提出动作请求，但动作选择、权限信号、错误回退和结果大小控制都属于 runtime。

对应代码：

```text
src/klara/core/loop.py
src/klara/core/tool_executor.py
src/klara/core/tools.py
```

<details>
<summary>展开：loop 为什么不用知道具体工具</summary>

这段代码出现在 `KlaraLoop.run()` 的每一轮 turn 里。它的输入不是“某个具体工具”，而是当前 transcript、系统 prompt、模型 id，以及 executor 暴露出来的 `ToolSpec` 列表。

输入和输出：

- 输入：`messages` 是到目前为止的对话记录，`self.tool_executor.specs` 是本轮可见工具的模型契约。
- 输出：如果 assistant 没有 `tool_calls`，返回最终 `KlaraRunResult`；如果有 `tool_calls`，追加 tool observations，然后进入下一轮。

真实执行顺序：

```python
response = self.llm.complete(
    system_prompt=self.system_prompt,
    messages=tuple(messages),
    tools=self.tool_executor.specs,
    model=self.model,
)

messages.append(
    KlaraMessage(
        role="assistant",
        content=response.content,
        tool_calls=response.tool_calls,
    )
)

if not response.tool_calls:
    return KlaraRunResult(...)

tool_results = self.tool_executor.execute_many(response.tool_calls)
for result in tool_results:
    messages.append(
        KlaraMessage(
            role="tool",
            name=result.name,
            content=result.content if result.ok else result.error or "",
            tool_call_id=result.tool_call_id,
        )
    )
```

怎么读这段代码：

1. `self.llm.complete(...)` 是一轮模型调用。loop 给模型的是 `messages`、`system_prompt`、`model` 和 `tools`，没有给模型任何 Python 对象。
2. `tools=self.tool_executor.specs` 是关键边界：模型只知道工具名、描述和参数 schema，不知道 `CurrentTimeTool`、`WebFetchTool` 这些类。
3. `messages.append(KlaraMessage(role="assistant", ...))` 先记录 assistant 的原始输出。即使 assistant 请求工具，这条消息也要进 transcript，因为它是后续 tool message 的前因。
4. `if not response.tool_calls` 是停止信号。没有工具请求，`response.content` 就是最终答案。
5. `execute_many(response.tool_calls)` 把所有工具请求交给 executor。loop 不检查工具名，也不判断哪个工具安全。
6. 每个 `ToolResult` 被转换成 `role="tool"` 消息。`tool_call_id` 把 observation 接回 assistant 的那条 tool call，`name` 让 trace/UI 知道是哪一个工具产生的结果。
7. `content=result.content if result.ok else result.error or ""` 把成功和失败都变成模型可见文本。失败不会让 loop 崩溃，而是成为下一轮模型能读到的 observation。

具体例子：

```text
assistant: tool_calls=[{"id": "call-1", "name": "current_time", "arguments": {"timezone": "Asia/Shanghai"}}]
executor: ToolResult(tool_call_id="call-1", name="current_time", ok=True, content="{...}")
loop：追加 role="tool", tool_call_id="call-1", name="current_time"
下一轮：模型看到时间 observation，然后写出最终答案
```

运行状态变化：

- LLM 只收到 `ToolSpec`，不知道 Python 类。
- assistant message 先被追加进 transcript，保留“模型请求了什么”。
- 如果没有 `tool_calls`，run 结束。
- 如果有 `tool_calls`，loop 把请求交给 `ToolExecutor`。
- 每个工具结果都变成 `role="tool"` 消息，下一轮模型能看到它。

架构边界：`core.loop` 只认识 `ToolExecutor` 和 `ToolResult`，不认识 `current_time`、`web_search` 或任何未来工具。

读者 takeaway：loop 只负责“模型回合”和“消息状态”，具体工具能力必须停在 executor 和 capability 层。

</details>

## 2. 工具有两份契约：给模型看的 Spec，给 runtime 看的 Metadata

一个工具不是一个函数名。Klara 把工具拆成两份契约：

```text
ToolSpec       -> 给模型看：什么时候用、参数怎么填
ToolMetadata   -> 给 runtime 看：风险、并行、审批、输出上限、可信度
```

主例子是 `current_time`。它是最适合教学的工具：无网络、无 key、输出稳定、错误可控。

对应代码：

```text
src/klara/core/tools.py
src/klara/capabilities/tools/current_time/schema.py
```

<details>
<summary>展开：current_time 的 ToolSpec</summary>

`ToolSpec` 是模型可见内容。它回答的是“模型如何请求这个工具”，不回答“runtime 如何执行这个工具”。

输入和输出：

- 输入：工具作者在 `schema.py` 里声明 `name`、`description` 和 `input_schema`。
- 输出：LLM client 把这些字段转换成 provider 能理解的 tool/function schema。

```python
CURRENT_TIME_SPEC = ToolSpec(
    name="current_time",
    description=(
        "Return the current date, time, weekday, and UTC offset for a requested "
        "timezone. Use for current-time questions, not historical or web facts."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": (
                    "Optional IANA timezone, such as Asia/Shanghai or UTC. "
                    "Use local time when omitted."
                ),
            },
        },
        "required": [],
        "additionalProperties": False,
    },
)
```

怎么读这段代码：

- `name="current_time"` 是模型生成 `tool_call.name` 时必须精确匹配的字符串，也是 executor 后面查找工具的 key。
- `description` 是给模型的使用说明。这里明确说它只回答“当前时间”，不回答历史事实或网页事实，避免模型把它误用成搜索工具。
- `input_schema.type="object"` 说明参数必须是 JSON object。Klara 的工具调用统一用 JSON-compatible arguments，方便 trace、测试和 provider 适配。
- `timezone` 是唯一参数，且不是 required；所以用户没指定时区时，模型可以传 `{}`。
- `additionalProperties=False` 是对模型的约束：不要发 `city`、`locale`、`format` 这类当前工具不理解的字段。

字段在本章的流向：

| 字段 | 谁读取 | 当前作用 |
| --- | --- | --- |
| `name` | LLM 和 `ToolExecutor` | 模型按这个名字请求工具，executor 按这个名字查找实例 |
| `description` | LLM | 帮模型判断什么时候应该调用工具 |
| `input_schema` | LLM provider / adapter | 约束模型生成 JSON arguments 的形状 |

具体例子：

```text
用户问：上海现在几点？
模型看到 ToolSpec 后可以生成：
ToolCall(name="current_time", arguments={"timezone": "Asia/Shanghai"})
```

运行状态变化：

- LLM 看到工具名 `current_time`。
- LLM 知道可填参数 `timezone`。
- `additionalProperties=False` 告诉模型不要发无关字段。
- 具体执行函数、Python 模块路径、metadata 都不会暴露给模型。

读者 takeaway：`ToolSpec` 是“模型如何请求工具”的说明书，不是执行策略。

</details>

<details>
<summary>展开：current_time 的 ToolMetadata</summary>

`ToolMetadata` 是 runtime 可见内容。它不进入模型上下文，专门给 executor、trace、UI、后续 guard 和 policy 使用。

输入和输出：

- 输入：工具作者声明 runtime 需要知道的安全、并行、展示和输出边界。
- 输出：executor 和上层 runtime 根据这些字段决定怎么执行、怎么截断、怎么展示。

```python
CURRENT_TIME_METADATA = ToolMetadata(
    label="Current Time",
    category="time",
    side_effect=ToolSideEffect.NONE,
    parallel_safe=True,
    timeout_seconds=1.0,
    max_output_chars=1000,
)
```

怎么读这段代码：

- `label="Current Time"` 是人看的名字，适合展示在 trace 或 UI 里，不要求和工具调用名一样。
- `category="time"` 让 UI、trace 或未来 profile 能把工具分组。
- `side_effect=ToolSideEffect.NONE` 说明这个工具不会读外部网络、写文件或控制系统。
- `parallel_safe=True` 是当前 executor 已经消费的字段。它允许多个安全工具在同一个 wave 中并发。
- `timeout_seconds=1.0` 是当前工具的执行预算信号；网络工具会把这个值传给 service 层。
- `max_output_chars=1000` 是当前 executor 已经消费的字段。超过这个长度的 observation 会被截断。

字段在本章的流向：

| 字段 | 谁读取 | 当前作用 | 后续用途 |
| --- | --- | --- | --- |
| `label` / `category` | trace/UI | 展示和分组 | capability profile |
| `side_effect` | runtime policy | 当前作为风险信号保留 | approval、权限、profile |
| `parallel_safe` | `ToolExecutor._can_run_in_parallel()` | 决定能否进入并行 wave | 更细粒度调度 |
| `requires_approval` | `ToolExecutor._can_run_in_parallel()` | 需要审批则切开 wave | approval UI |
| `timeout_seconds` | tool/service adapter | 给执行或网络请求传预算 | 统一超时策略 |
| `max_output_chars` | `ToolExecutor._limit_result()` | 截断模型可见输出 | token budget 策略 |
| `output_trust` | trace/prompt guard | 当前作为信任信号保留 | 网页注入防护 |

运行状态变化：

- runtime 知道它是无副作用工具。
- executor 可以把它放进并行 wave。
- output limiter 知道最多暴露多少字符给模型。
- trace/UI 可以展示 human-facing label 和 category。

读者 takeaway：metadata 不是 prompt；它是 runtime 做规划、守卫、截断和展示的信号。

</details>

## 3. 每个工具是一个 package，不是散落的函数

Klara 的工具目录采用一工具一包：

```text
src/klara/capabilities/tools/
  current_time/
    __init__.py
    schema.py
    timezones.py
    tool.py
  image_generate/
    __init__.py
    schema.py
    tool.py
  web_search/
    __init__.py
    schema.py
    tool.py
  web_fetch/
    __init__.py
    schema.py
    tool.py
```

这不是为了形式感，而是为了让读者一眼分清：

- `schema.py`：模型契约和 runtime metadata。
- `tool.py`：参数校验、调用服务、返回 observation。
- 领域 helper：例如 `timezones.py`。
- 外部 provider 或复杂 I/O：放到 `src/klara/services/`。

对应代码：

```text
src/klara/capabilities/tools/current_time/
src/klara/capabilities/tools/image_generate/
src/klara/capabilities/tools/web_search/
src/klara/capabilities/tools/web_fetch/
tests/klara/architecture/test_boundaries.py
```

Klara 学到：新增工具时，不要把工具塞进 core，也不要让 frontend 或 loop 对具体工具名分支。

## 4. Registry 负责发现“当前可见工具”

模型不能看到所有未来能力。每次 run 只暴露 registry 选择出来的可见工具。

```text
klara.capabilities.tools.*
-> discover package
-> import <tool_package>.tool
-> 找到唯一 BaseTool subclass
-> 实例化
-> visible_tools()
```

对应代码：

```text
src/klara/capabilities/registry.py
tests/klara/capabilities/test_registry.py
```

<details>
<summary>展开：自动发现工具包</summary>

这段代码的目标是从 `src/klara/capabilities/tools/` 下自动发现本地工具，而不是在 registry 里维护一份手写列表。

输入和输出：

- 输入：`klara.capabilities.tools` 包下面的一组子包，例如 `current_time`、`web_fetch`、`web_search`。
- 输出：每个工具包里的唯一 concrete `BaseTool` subclass，按包名排序后返回。

真实代码：

```python
def discover_local_tool_classes() -> tuple[type[BaseTool], ...]:
    discovered: list[type[BaseTool]] = []
    for module_info in sorted(
        pkgutil.iter_modules(tools_package.__path__, tools_package.__name__ + "."),
        key=lambda item: item.name,
    ):
        if not module_info.ispkg:
            continue
        tool_module = importlib.import_module(f"{module_info.name}.tool")
        candidates = [
            value
            for _, value in inspect.getmembers(tool_module, inspect.isclass)
            if value is not BaseTool
            and issubclass(value, BaseTool)
            and value.__module__ == tool_module.__name__
        ]
        if len(candidates) != 1:
            raise RuntimeError(
                f"{module_info.name}.tool must define exactly one BaseTool subclass"
            )
        discovered.append(candidates[0])
    return tuple(discovered)
```

怎么读这段代码：

1. `pkgutil.iter_modules(...)` 扫描 `klara.capabilities.tools` 包下面的直接子模块和子包。
2. `sorted(..., key=lambda item: item.name)` 固定发现顺序，避免不同机器或文件系统导致工具顺序漂移。
3. `if not module_info.ispkg: continue` 只接受 package。也就是说，一个工具必须有自己的目录，而不是一个散落的 `.py` 文件。
4. `importlib.import_module(f"{module_info.name}.tool")` 只导入每个工具包里的 `tool.py`，因此工具实现入口是稳定的。
5. `inspect.getmembers(..., inspect.isclass)` 找出 `tool.py` 中定义的类。
6. `issubclass(value, BaseTool)` 保证它是 Klara 本地工具模板。
7. `value.__module__ == tool_module.__name__` 排除从别处 import 进来的类，避免把 `BaseTool` 或 helper class 误认为当前工具。
8. `len(candidates) != 1` 直接报错。一个工具包只能暴露一个 concrete tool，否则 registry 不知道该把哪个类给模型看。
9. `discovered.append(candidates[0])` 记录类本身，`discover_local_tools()` 再负责实例化。

具体例子：

```text
tools/current_time/tool.py  -> CurrentTimeTool
tools/image_generate/tool.py -> ImageGenerateTool
tools/web_fetch/tool.py     -> WebFetchTool
tools/web_search/tool.py    -> WebSearchTool
```

如果 `web_fetch/tool.py` 里意外定义了两个 `BaseTool` subclass，启动默认 registry 时会失败，而不是静默暴露一个不确定的工具。

运行状态变化：

- registry 不维护手写默认工具列表。
- 新工具只要符合 package shape，就会被默认 registry 发现。
- 每个 package 必须只有一个 concrete `BaseTool`，避免读者和 runtime 都不知道该暴露哪个类。
- 工具顺序是 deterministic 的，便于测试、trace 和模型可见 spec 的稳定输出。

当前默认工具由测试锁住：

```python
assert names == {"current_time", "image_generate", "web_fetch", "web_search"}
```

读者 takeaway：registry 是“工具可见性”边界，不是执行器。

</details>

## 5. Executor 负责查找、执行、回退和截断

`ToolExecutor` 是模型请求和具体工具之间的窄门。

```text
ToolCall(id, name, arguments)
-> lookup visible tools by name
-> tool.execute(arguments)
-> normalize id/name
-> limit output
-> ToolResult
```

对应代码：

```text
src/klara/core/tool_executor.py
tests/klara/core/test_tool_executor.py
```

<details>
<summary>展开：单个工具调用如何变成 observation</summary>

这段代码是模型请求和具体工具之间的保护层。模型只会产出 `ToolCall`，executor 负责把它变成稳定的 `ToolResult`。

输入和输出：

- 输入：`ToolCall(id, name, arguments)`，其中 `id` 来自模型响应，`name` 是模型想调用的工具名，`arguments` 是模型生成的 JSON 参数。
- 输出：一定返回 `ToolResult`。成功、未知工具、工具异常和输出过长都会被收敛成同一种 observation 形状。

真实代码：

```python
def execute(self, call: ToolCall) -> ToolResult:
    tool = self._tools.get(call.name)
    if tool is None:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="",
            ok=False,
            error=f"Unknown tool: {call.name}",
        )
    try:
        result = tool.execute(call.arguments)
    except Exception as exc:
        return ToolResult(
            tool_call_id=call.id,
            name=call.name,
            content="",
            ok=False,
            error=f"{type(exc).__name__}: {exc}",
        )
    normalized = self._normalize_result(call, result)
    return self._limit_result(normalized, max_chars=tool.metadata.max_output_chars)
```

怎么读这段代码：

1. `tool = self._tools.get(call.name)` 用模型给出的工具名查找当前 run 可见的工具实例。`self._tools` 是 executor 初始化时从 registry 选出的工具 map，不是全局工具表。
2. `tool is None` 是 unknown tool 分支。即使模型请求了不存在的工具，runtime 也不抛异常，而是返回 `ok=False` 的 `ToolResult`。
3. unknown tool 的 `tool_call_id=call.id` 很重要。这样下一条 tool message 仍能和 assistant 的原始 tool call 对上。
4. `tool.execute(call.arguments)` 是唯一真正进入具体工具实现的地方。executor 不知道这个工具是时钟、搜索、网页抓取还是未来的 RAG。
5. `except Exception as exc` 是最后防线。具体工具不应该随便抛异常，但如果抛了，executor 仍把它变成 failed observation。
6. `_normalize_result(call, result)` 修正工具返回的 `tool_call_id` 和 `name`。具体工具可以简单地构造结果，最终 transcript 的 join key 由 executor 兜底。
7. `_limit_result(..., max_chars=tool.metadata.max_output_chars)` 是模型可见输出边界。具体工具返回再长，进入下一轮模型前都会按 metadata 截断。

具体例子：模型请求了不存在的工具。

```text
call = ToolCall(id="call-9", name="read_file", arguments={"path": "x"})

executor 找不到 read_file，返回：
ToolResult(
  tool_call_id="call-9",
  name="read_file",
  content="",
  ok=False,
  error="Unknown tool: read_file",
)

loop 再把这个结果追加成 role="tool" 消息。
下一轮模型看到的是“工具失败了”，而不是后端崩溃。
```

运行状态变化：

- unknown tool 变成 failed observation。
- 工具抛出的 Python 异常变成 failed observation。
- 工具返回的 id/name 如果不匹配原始请求，会被 executor 规范化。
- 输出超过 `metadata.max_output_chars` 会被截断，再交给模型。

读者 takeaway：工具失败是模型可见状态，不是 runtime 崩溃。

</details>

## 6. BaseTool 把参数错误收敛成 failed observation

每个本地工具继承 `BaseTool`。它不是 core 必需的继承树，而是给本地工具作者的模板。

对应代码：

```text
src/klara/capabilities/base_tool.py
src/klara/capabilities/tools/current_time/tool.py
tests/klara/capabilities/test_current_time_tool.py
```

<details>
<summary>展开：ToolInputError 为什么不会炸掉 loop</summary>

这段代码是工具作者的本地模板。core 只要求工具符合 `KlaraTool` protocol，但本地工具继承 `BaseTool` 后，可以共用参数读取、JSON 输出和失败 observation 的写法。

输入和输出：

- 输入：模型生成的 JSON-like `arguments`。
- 输出：成功时返回 concrete tool 的 `ToolResult`；参数错误时返回 `ok=False` 的 `ToolResult`。

真实代码：

```python
def execute(self, arguments: JsonObject) -> ToolResult:
    try:
        return self.run(arguments)
    except ToolInputError as exc:
        return self.failure(arguments, str(exc))
```

`current_time` 中的失败路径：

```python
timezone_name = str(arguments.get("timezone") or "").strip()
try:
    resolved_name, resolved_timezone = resolve_timezone(timezone_name)
except ValueError as exc:
    return self.failure(arguments, str(exc))
```

怎么读这段代码：

1. `BaseTool.execute()` 是 executor 调用的入口。executor 不直接调用 `run()`，因为 `execute()` 负责统一处理输入错误。
2. `self.run(arguments)` 才是具体工具逻辑，例如 `CurrentTimeTool.run()`。
3. `ToolInputError` 表示“模型给的参数不符合这个工具的契约”，这类错误属于可恢复的 agent observation。
4. `self.failure(arguments, str(exc))` 会构造 `ToolResult(content="", ok=False, error=...)`，并使用工具自己的 `spec.name`。
5. `current_time` 里，`timezone_name = str(arguments.get("timezone") or "").strip()` 把缺失值、空字符串和带空格的字符串收敛成一个干净输入。
6. `resolve_timezone(timezone_name)` 是领域校验。它成功时返回规范化时区名和 timezone 对象，失败时抛 `ValueError`。
7. `except ValueError as exc: return self.failure(...)` 把领域错误也收敛成 failed observation。

具体例子：

```text
arguments={"timezone": "Mars/Olympus"}
-> resolve_timezone("Mars/Olympus") 抛出 ValueError
-> CurrentTimeTool 返回 ok=False
-> loop 追加带错误文本的 role="tool" 消息
-> 模型可以道歉，或者要求用户提供有效的 IANA timezone
```

运行状态变化：

- `Mars/Olympus` 这类错误 timezone 不会抛到 FastAPI 或前端。
- 工具返回 `ok=False`、`content=""`、`error="Unknown timezone: Mars/Olympus"`。
- loop 把错误作为 tool message 放回下一轮。

读者 takeaway：工具错误也属于 agent loop 的 observation。

</details>

## 7. 分区算法：按 metadata 形成 execution waves

模型一次可以返回多个 tool calls。Klara 不按具体工具名写死执行顺序，而是按 metadata 分区。

当前规则：

```text
parallel_safe=True 且 requires_approval=False
-> 可以进入同一个 parallel wave

parallel_safe=False
或 requires_approval=True
或 unknown tool
-> 切开 wave，单独执行
```

对应代码：

```text
src/klara/core/tool_executor.py
src/klara/core/tools.py
tests/klara/core/test_tool_executor.py
```

<details>
<summary>展开：execute_many 如何切 execution wave</summary>

这段代码处理的是“同一个 assistant turn 返回多个 tool calls”的情况。它不是简单地全部串行，也不是无脑全部并行，而是按 metadata 切成一段一段 execution wave。

输入和输出：

- 输入：模型一次返回的 `tuple[ToolCall, ...]`，顺序就是模型请求顺序。
- 输出：`tuple[ToolResult, ...]`，结果顺序仍然和请求顺序一致。

真实代码：

```python
def execute_many(self, calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
    results: list[ToolResult] = []
    parallel_wave: list[ToolCall] = []
    for call in calls:
        if self._can_run_in_parallel(call):
            parallel_wave.append(call)
            continue
        results.extend(self._execute_parallel_wave(tuple(parallel_wave)))
        parallel_wave = []
        results.append(self.execute(call))
    results.extend(self._execute_parallel_wave(tuple(parallel_wave)))
    return tuple(results)
```

判断函数：

```python
def _can_run_in_parallel(self, call: ToolCall) -> bool:
    tool = self._tools.get(call.name)
    if tool is None:
        return False
    return tool.metadata.parallel_safe and not tool.metadata.requires_approval
```

并行 wave 的执行：

```python
def _execute_parallel_wave(self, calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
    if not calls:
        return ()
    if len(calls) == 1:
        return (self.execute(calls[0]),)
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return tuple(pool.map(self.execute, calls))
```

怎么读这段代码：

1. `results` 是已经完成的输出列表，最终会转成 tuple 返回。
2. `parallel_wave` 是当前正在收集的一段“连续可并行工具调用”。
3. 如果 `_can_run_in_parallel(call)` 为 true，当前 call 先进入 `parallel_wave`，暂时不执行。
4. 如果遇到不可并行 call，executor 先 flush 当前 `parallel_wave`，再单独执行这个不可并行 call。
5. loop 结束后还要再 flush 一次尾部 `parallel_wave`，否则最后一段 safe calls 不会执行。
6. `_can_run_in_parallel()` 只看当前 run 的可见工具和两个 metadata 字段：`parallel_safe`、`requires_approval`。
7. unknown tool 返回 false，因为 runtime 不能证明未知工具安全；它会单独走 `execute()`，再变成 failed observation。
8. `_execute_parallel_wave()` 对 0 个、1 个、多个 calls 分别处理。多个 calls 才创建 `ThreadPoolExecutor`，并且 `pool.map` 保持输入顺序，所以并发执行不破坏 observation 顺序。

具体 trace：

```text
calls = [可并行 A, 可并行 B, 串行 C, 可并行 D, 未知 E]

可并行 A -> parallel_wave=[A]
可并行 B -> parallel_wave=[A, B]
串行 C -> 先并发执行 [A, B]，再单独执行 C
可并行 D -> parallel_wave=[D]
未知 E -> 先执行 [D]，再单独执行 E，E 返回 failed observation

最终结果顺序仍是 [A_result, B_result, C_result, D_result, E_failed]
```

运行状态变化：

- 连续的 parallel-safe 工具可以用 thread pool 同时执行。
- serial 或 approval-gated 工具会切断当前 wave。
- unknown tool 也会切断 wave，因为 runtime 不能证明它安全。
- 返回结果仍保持模型请求顺序。

这里要精确区分：

- `parallel_safe` 和 `requires_approval` 当前已经参与 wave partition。
- `side_effect` 当前主要是风险分类信号，给后续权限、UI、profile、policy 使用。
- `output_trust` 当前主要是 observation 信任信号，给后续网页注入防护、prompt wrapper、trace/UI 使用。

读者 takeaway：分区算法不应该认识具体工具名，而应该读 metadata。

</details>

## 8. 网络工具展示 metadata 为什么重要

`current_time` 讲清最小工具模板；`web_search` 和 `web_fetch` 讲清风险边界。

```text
web_search -> 找 URL、title、snippet
web_fetch  -> 读取一个 public HTTP(S) 页面正文
```

它们都不是主线里的“研究 agent”。本章只用它们说明：

- 网络工具有 `side_effect=NETWORK`。
- 外部网页内容是 `output_trust=UNTRUSTED`。
- provider/page 解析属于 service 层，不属于 core。
- 工具返回的是 observation，不是事实真理。

对应代码：

```text
src/klara/capabilities/tools/web_search/schema.py
src/klara/capabilities/tools/web_fetch/schema.py
src/klara/services/web/search.py
src/klara/services/web/fetcher.py
src/klara/services/web/safety.py
tests/klara/capabilities/test_web_tools.py
tests/klara/services/test_web_search.py
tests/klara/services/test_web_fetch.py
```

<details>
<summary>展开：web_fetch 为什么不直接把 urllib 写进 tool.py</summary>

`web_fetch` 是本章的风险边界示例。它能访问外部网络，所以不能把所有逻辑堆在 `tool.py` 里；工具 wrapper 只负责参数、metadata 和 observation，网络细节进入 service 层。

输入和输出：

- 输入：模型生成的 `{"url": "...", "max_chars": ...}`。
- 输出：成功时返回包含页面文本的 JSON observation；失败时返回 `ok=False` 的 observation。

工具 wrapper 只负责模型契约和 observation：

```python
@dataclass(frozen=True)
class WebFetchTool(BaseTool):
    spec: ToolSpec = WEB_FETCH_SPEC
    metadata: ToolMetadata = WEB_FETCH_METADATA
    page_fetcher: PageFetcher = fetch_page

    def run(self, arguments: JsonObject) -> ToolResult:
        url = self.optional_string(arguments, "url")
        if not url:
            raise ToolInputError("url must not be empty")
        max_chars = _optional_int(arguments, "max_chars", default=4000)
        ...
        page = self.page_fetcher(
            url,
            max_chars=max_chars,
            timeout_seconds=self.metadata.timeout_seconds,
        )
        return self.json_success(arguments, {...})
```

复杂网络逻辑在 service 层：

```python
def validate_public_http_url(raw_url: str) -> str:
    ...
    if parsed.scheme not in {"http", "https"}:
        raise WebSafetyError("URL must use http or https")
    if parsed.username or parsed.password:
        raise WebSafetyError("URL must not include credentials")
    ...
    _reject_local_hostname(host)
    _reject_private_addresses(host)
```

怎么读 tool wrapper：

1. `spec` 和 `metadata` 来自 `schema.py`，所以模型契约和 runtime 信号仍然集中声明。
2. `page_fetcher: PageFetcher = fetch_page` 是依赖注入点。测试可以传假的 fetcher，不需要真的访问网络。
3. `url = self.optional_string(arguments, "url")` 复用 `BaseTool` 参数 helper，非字符串会变成 `ToolInputError`。
4. `if not url` 是必填参数校验。空 URL 是模型参数错误，不是网络错误。
5. `_optional_int(..., default=4000)` 读取可选长度限制；`200 <= max_chars <= 6000` 防止模型请求过小或过大的页面正文。
6. `self.page_fetcher(... timeout_seconds=self.metadata.timeout_seconds)` 把 runtime metadata 传到 service 层，工具自己不实现 socket/HTTP 细节。
7. `except WebFetchError as exc` 把 service 层的抓取失败转换成 failed observation。
8. `trust="untrusted_external_content"` 明确告诉后续层：网页正文不是可信系统指令，只是外部 observation。

怎么读 safety service：

1. `raw_url.strip()` 先消除首尾空白，空字符串直接拒绝。
2. `parsed.scheme not in {"http", "https"}` 拒绝 `file://`、`ftp://` 等非网页协议。
3. `not parsed.hostname` 拒绝没有 host 的 URL。
4. `parsed.username or parsed.password` 拒绝带凭据的 URL，避免把认证信息放进请求和 trace。
5. `_reject_local_hostname(host)` 拒绝 `localhost` 和 `.localhost`。
6. `_reject_private_addresses(host)` 会检查 literal IP，也会 DNS resolve 后检查每个地址。
7. `not address.is_global` 会拒绝 private、loopback、link-local、reserved 等非公网地址。
8. `parsed._replace(fragment="")` 去掉 URL fragment，因为 fragment 不会发送给服务器，也不应该影响抓取缓存和 trace。

具体例子：

```text
url="https://docs.python.org/3/"
-> scheme 是 https
-> host 可解析为公网地址
-> service 抓取 HTML 并提取正文
-> tool 返回 JSON observation，trust="untrusted_external_content"

url="http://localhost:8011"
-> _reject_local_hostname("localhost")
-> WebFetchError / WebSafetyError
-> tool 返回 failed observation
```

运行状态变化：

- tool 层保持短小，方便教学和注册。
- service 层负责 URL 校验、redirect 校验、HTML 提取、长度限制。
- `localhost` / private IP 被拒绝，避免把 `web_fetch` 变成内网探测工具。
- 任何网页正文都以 `trust="untrusted_external_content"` 返回。

读者 takeaway：外部 I/O 能力可以暴露成工具，但 provider 和安全边界要放在 service 层。

</details>

## 9. 本章不做什么

这些边界故意留到后面：

- 不做完整 approval UI。
- 不做 shell/filesystem mutation 工具。
- 不接 Bing、Google、Baidu、Brave 这类 account-backed provider routing。
- 不做 MCP。
- 不把 web search 讲成 RAG 或研究 agent。

Klara 现在只是学会：工具是 runtime 可注册、可执行、可失败、可观察的动作边界。

## 运行与验证

启动开发环境：

```powershell
.\scripts\dev.ps1 -Restart
```

默认地址：

```text
Web: http://127.0.0.1:5123
API: http://127.0.0.1:8011
```

本章相关测试：

```powershell
python -m pytest --basetemp .tmp\pytest
cd apps\web
npm.cmd test
npm.cmd run build
```

可选真实网络 smoke test：

```powershell
$env:PYTHONPATH='src'
@'
from klara.services.web.search import search_web
from klara.services.web.fetcher import fetch_page

response = search_web("python docs", count=1)
print(response.provider, response.results[0].title, response.results[0].url)
page = fetch_page(response.results[0].url, max_chars=300)
print(page.status, page.content_type, page.title)
'@ | python -
```

## 小实验

1. 改 `current_time` 的 `max_output_chars`，观察 executor 截断行为。
2. 把一个测试工具的 `parallel_safe` 改成 `False`，观察 `execute_many()` 如何切 wave。
3. 请求一个不存在的工具名，确认 loop 返回 failed observation。
4. 请求 `web_fetch` 读取 `http://localhost:8011`，确认安全层拒绝。
5. 给 `web_search` 加 `allowed_domains=["python.org"]`，观察结果过滤。

## 下一章预告

Chapter 3 会讲 Hooks And Trace：工具调用已经能发生，下一步是把 runtime 生命周期事件稳定地投影到 trace、UI 和后续 guard 里，而不是把观察逻辑写进 loop 主体。
