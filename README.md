# Chapter 2: Tool Calling

语言：中文 | [English](./README.en.md)

上一章：[Chapter 1: Minimal LLM Loop](./docs/chapters/ch01-minimal-agent-loop.md)
下一章：Chapter 3: Hooks And Trace
总路线：[Klara Roadmap](./docs/skills/roadmap.md)

---

## 一句话看懂本章

工具调用的本质是：模型提出 `tool_calls`，runtime 执行工具，把 observation 放回上下文；如果模型没有提出 `tool_calls`，loop 就停止并返回最终答案。

![Klara Chapter 2 Tool Calling](./docs/assets/ch02-tool-calling.png)

| 看到什么 | Klara 做什么 |
| --- | --- |
| assistant 返回 `tool_calls` | 执行工具，把结果追加成 `role="tool"` observation，继续下一轮 |
| assistant 没有 `tool_calls` | 返回最终答案，停止 |
| 工具不存在、参数错误、执行失败 | 返回 failed observation，让下一轮模型看到错误 |
| 工具返回太长 | 按 metadata 截断后再进入上下文 |
| 达到 `max_turns` | 按 `LoopPolicy` 停止，避免无限工具循环 |

## 快速体验

准备好 `.env` 后启动前后端：

```powershell
.\scripts\dev.ps1
```

打开：

```text
http://127.0.0.1:5123
```

先问一个稳定的本地工具问题：

```text
请使用 current_time 查询 Asia/Shanghai 当前时间，然后用一句话回答。
```

你应该看到：Klara 调用 `current_time`，runtime 返回时间 observation，然后模型基于 observation 写最终回答。

再问一个网络证据链问题：

```text
请使用 web_search 搜索世界杯最新战报，再用 web_fetch 打开一个结果总结。
```

你应该看到：`web_search` 只找候选网页，`web_fetch` 才读取其中一个 URL。网页内容会以不可信 observation 进入下一轮。

最后试一个媒体工具：

```text
请生成一张暖色调的 Klara 书桌插画，并把图片展示在回答里。
```

你应该看到：Klara 调用 `image_generate`，工具把图片保存成本地资产，最终回答用 Markdown 图片链接把图片穿插在文字中。

## 1. 从真实问题开始：为什么“有工具”还会答错

本章不是为了把函数包装成工具而包装。我们先看一个真实问题。

同样是“世界杯最新战报”：

```text
好的 run：
llm_call_completed: tool_call_count=1
tool_call_started: web_search
tool_call_completed: web_search
llm_call_completed: tool_call_count=1
tool_call_started: web_fetch
tool_call_completed: web_fetch
llm_call_completed: tool_call_count=0

坏的 follow-up：
用户追问：阿根廷呢？
llm_call_completed: tool_call_count=0
assistant 直接回答，没有重新建立搜索证据链
```

这说明问题不只是“有没有 web_search”。问题是：

```text
当前问题
-> 当前可见工具声明是否清楚
-> 历史上下文是否干净
-> 工具 observation 是否可信、可控、可回退
```

Klara 不应该靠关键词规则修补，例如“看到世界杯就强制搜索”。那样很快会变成一堆脆弱的 if/else。Klara 要做的是把工具边界建清楚：

```text
ToolSpec       -> 模型看见：我能调用什么，参数怎么写
ToolMetadata   -> runtime 看见：风险、并行、审批、输出上限、可信度
ToolExecutor   -> 执行工具，把成功/失败都变成 observation
History policy -> 每个会话只注入最近历史，并清理本地图片链接
```

对应代码：

```text
src/klara/core/loop.py
src/klara/core/tools.py
src/klara/tools/registry.py
src/klara/tools/executor.py
src/klara/context/history.py
apps/api/services/run_service.py
```

读者 takeaway：工具章节真正要讲的是 runtime 边界，不是某一个搜索 API。

<details>
<summary>展开：这次事故应该怎么读</summary>

第一条世界杯问题能正确走 `web_search -> web_fetch`，说明工具链本身能跑。后面追问出现不稳定，说明更深的问题在“模型可见状态”：

1. 工具声明要足够清楚。模型只看 `ToolSpec`，如果工具描述含糊，它可能不调用工具，或者调用错工具。
2. 工具结果不能直接等于事实。`web_search` 返回的是候选结果，`web_fetch` 返回的是外部网页正文，这些 observation 都可能过时、低质量或被网页内容污染。
3. 历史上下文不能无限回放。图片生成后，旧回答里会有 `/api/assets/local?...` 本地图片链接；这些链接对后续搜索问题没有帮助，还会占上下文。
4. 每个聊天窗口应有自己的历史。`RunService._conversation_history(session_id, ...)` 只读取当前 session 的消息，不会把其他窗口混进来。

本章只解决最基础的边界：

```text
工具如何声明
工具如何注册
工具如何执行
工具结果如何回到 loop
历史如何做最小清理和最近 12 条边界
```

完整的 context compression、source grounding、memory policy、工具选择评估会在后面章节展开。

</details>

## 2. Loop 只认识 tool_calls，不认识具体工具

上一章已经有最小 loop。本章不改变 loop 的核心判断：

```text
messages + system_prompt + tool specs
-> LLM
-> assistant message
-> 有 tool_calls：执行工具，追加 observation，继续
-> 无 tool_calls：返回 final answer，停止
```

Klara 学到：工具调用不是另一个聊天接口，而是 loop 的继续信号。

对应代码：

```text
src/klara/core/loop.py
src/klara/core/messages.py
src/klara/core/policies.py
```

<details>
<summary>展开：KlaraLoop.run 的工具分支</summary>

这段代码在每一轮 turn 里运行。输入是当前 transcript、系统 prompt、当前模型、以及本轮可见工具 specs。输出要么是最终答案，要么是追加了工具 observation 的下一轮 transcript。

真实代码：

```python
response = self.llm.complete(
    system_prompt=self.system_prompt,
    messages=tuple(messages),
    tools=self.tool_executor.specs,
    model=self.model,
)

assistant_message = KlaraMessage(
    role="assistant",
    content=response.content,
    tool_calls=response.tool_calls,
)
messages.append(assistant_message)

if not response.tool_calls:
    return self._complete(
        active_run_id,
        messages,
        response.content,
        StopReason.FINAL,
    )

tool_results = self.tool_executor.execute_many(response.tool_calls)
for result in tool_results:
    messages.append(
        KlaraMessage(
            role="tool",
            name=result.name,
            tool_call_id=result.tool_call_id,
            content=result.content if result.ok else result.error or "",
        )
    )
```

怎么读：

1. `self.llm.complete(...)` 是一轮模型调用。模型只收到 `ToolSpec`，不会拿到 Python 工具对象。
2. assistant message 先进入 `messages`。即使 assistant 只是请求工具，这条消息也必须保存，因为后面的 tool message 要用 `tool_call_id` 接回它。
3. `if not response.tool_calls` 是停止信号。没有工具请求，`response.content` 就是最终答案。
4. `execute_many(response.tool_calls)` 把工具请求交给 executor。loop 不关心工具名是 `current_time`、`web_search` 还是未来的 RAG。
5. 每个 `ToolResult` 变成 `role="tool"` 消息。成功用 `content`，失败用 `error`，但两者都会进入下一轮模型可见上下文。

具体例子：

```text
assistant:
  tool_calls=[{"id": "call-1", "name": "current_time", "arguments": {"timezone": "Asia/Shanghai"}}]

executor:
  ToolResult(tool_call_id="call-1", name="current_time", ok=True, content="{...}")

loop:
  append role="tool", tool_call_id="call-1", name="current_time"

next model turn:
  模型看到时间 observation，然后写最终答案
```

状态变化：

- `messages` 先追加 assistant 请求。
- 如果没有工具请求，run 用 `StopReason.FINAL` 完成。
- 如果有工具请求，`messages` 继续追加 tool observations。
- `LoopPolicy.max_turns = 12` 防止模型无限请求工具。

架构边界：`core.loop` 只依赖 `ToolRunner` 协议，不导入 `klara.tools` 里的具体实现。

读者 takeaway：loop 只决定继续或停止；具体工具能力留在工具层。

</details>

## 3. ToolSpec 给模型看，ToolMetadata 给 runtime 看

一个工具有两份契约：

```text
ToolSpec       -> 模型可见：名称、描述、JSON 参数 schema
ToolMetadata   -> 模型不可见：风险、并行、审批、超时、输出上限、可信度
```

主例子是 `current_time`。它没有网络、没有密钥、输出稳定，非常适合看清工具模板。

对应代码：

```text
src/klara/core/tools.py
src/klara/tools/builtin/current_time/schema.py
```

<details>
<summary>展开：current_time 的 Spec 和 Metadata</summary>

`ToolSpec` 是模型可见内容。它回答“模型怎样请求这个工具”。

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

怎么读：

- `name="current_time"` 是模型生成 `tool_call.name` 时必须精确匹配的字符串。
- `description` 明确说它只回答当前时间，不回答历史事实或网页事实。
- `input_schema` 约束模型生成 JSON arguments。
- `additionalProperties=False` 告诉模型不要发 `city`、`locale`、`format` 这类工具不理解的字段。

`ToolMetadata` 是 runtime 可见内容。它回答“runtime 怎样管理这个工具”。

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

字段流向：

| 字段 | 谁读取 | 当前作用 |
| --- | --- | --- |
| `ToolSpec.name` | LLM / executor | 模型按这个名字请求，executor 按这个名字查找 |
| `ToolSpec.description` | LLM | 帮模型判断什么时候该用工具 |
| `ToolSpec.input_schema` | LLM adapter | 转成 provider tool schema |
| `metadata.parallel_safe` | `ToolExecutor` | 决定能否进入并行 wave |
| `metadata.requires_approval` | `ToolExecutor` | 需要审批则切断并行 wave |
| `metadata.timeout_seconds` | tool/service | 传给具体工具或网络服务 |
| `metadata.max_output_chars` | `ToolExecutor` | 截断模型可见 observation |
| `metadata.output_trust` | trace / future guard | 标记网页等外部 observation 不可信 |

状态变化：

- 模型只看到 `ToolSpec`。
- runtime 保留 `ToolMetadata`。
- executor 用 metadata 做并行与截断。

读者 takeaway：Spec 是给模型的说明书；Metadata 是给 runtime 的调度和安全信号。

</details>

## 4. 每个工具是一个 package

Klara 采用一工具一包：

```text
src/klara/tools/builtin/
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

Klara 学到：工具不是散落函数，而是一个可声明、可注册、可测试的能力包。

对应代码：

```text
src/klara/tools/base.py
src/klara/tools/builtin/current_time/
src/klara/tools/builtin/image_generate/
src/klara/tools/builtin/web_search/
src/klara/tools/builtin/web_fetch/
tests/klara/architecture/test_boundaries.py
```

<details>
<summary>展开：BaseTool 为什么只是作者模板，不是 core 依赖</summary>

core 只要求工具满足 `KlaraTool` protocol。本地工具继承 `BaseTool`，是为了共享参数校验和结果构造，不是为了让 loop 依赖继承树。

```python
class BaseTool:
    spec: ToolSpec
    metadata: ToolMetadata

    def execute(self, arguments: JsonObject) -> ToolResult:
        try:
            return self.run(arguments)
        except ToolInputError as exc:
            return self.failure(arguments, str(exc))

    def run(self, arguments: JsonObject) -> ToolResult:
        raise NotImplementedError
```

怎么读：

1. executor 调用的是 `tool.execute(arguments)`。
2. `BaseTool.execute()` 捕获 `ToolInputError`，把参数错误变成 failed observation。
3. 具体工具只实现 `run()`。
4. core 不导入 `BaseTool`，所以未来 MCP、远端工具、沙箱工具也可以只实现 protocol。

`current_time` 的失败路径：

```python
timezone_name = str(arguments.get("timezone") or "").strip()
try:
    resolved_name, resolved_timezone = resolve_timezone(timezone_name)
except ValueError as exc:
    return self.failure(arguments, str(exc))
```

具体例子：

```text
arguments={"timezone": "Mars/Olympus"}
-> resolve_timezone raises ValueError
-> CurrentTimeTool returns ok=False
-> loop appends role="tool" with the error
-> next model turn can explain the invalid timezone
```

读者 takeaway：参数错误是模型可见 observation，不是后端崩溃。

</details>

## 5. Registry 负责发现当前可见工具

模型不能看到“所有未来能力”。每个 run 只暴露 registry 当前选择的工具。

```text
klara.tools.builtin.*
-> 发现子包
-> 导入 <tool_package>.tool
-> 找到唯一 BaseTool subclass
-> 实例化
-> visible_tools()
```

对应代码：

```text
src/klara/tools/registry.py
tests/klara/tools/test_tool_registry.py
```

<details>
<summary>展开：自动发现为什么比手写列表更适合课程</summary>

真实代码：

```python
def discover_local_tool_classes() -> tuple[type[BaseTool], ...]:
    discovered: list[type[BaseTool]] = []
    for module_info in sorted(
        pkgutil.iter_modules(
            builtin_tools_package.__path__,
            builtin_tools_package.__name__ + ".",
        ),
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

怎么读：

1. `pkgutil.iter_modules(...)` 扫描内置工具包。
2. `sorted(..., key=lambda item: item.name)` 固定顺序，避免不同机器上工具顺序漂移。
3. `if not module_info.ispkg` 只接受目录包，逼迫每个工具有自己的文件夹。
4. `importlib.import_module(f"{module_info.name}.tool")` 只导入每个工具包的 `tool.py`。
5. `issubclass(value, BaseTool)` 确认这是本地工具模板。
6. `value.__module__ == tool_module.__name__` 排除 import 进来的类。
7. `len(candidates) != 1` 直接报错，避免一个工具包里暴露多个工具导致歧义。

当前默认工具由测试锁住：

```python
assert names == {"current_time", "image_generate", "web_fetch", "web_search"}
```

状态变化：

- 新工具按目录规范加入后，会被默认 registry 发现。
- registry 输出的是 concrete tools。
- harness 把这些 tools 交给 `ToolExecutor`。
- loop 仍然只通过 `ToolRunner` 协议拿 specs 和执行结果。

读者 takeaway：registry 是工具可见性边界，不是关键词路由器。

</details>

## 6. Executor 把工具请求变成稳定 observation

`ToolExecutor` 是模型请求和具体工具之间的窄门。

```text
ToolCall(id, name, arguments)
-> lookup visible tool by name
-> tool.execute(arguments)
-> normalize id/name
-> limit output
-> ToolResult
```

对应代码：

```text
src/klara/tools/executor.py
tests/klara/tools/test_tool_executor.py
```

<details>
<summary>展开：单个工具调用怎么执行</summary>

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

怎么读：

1. `call.name` 来自模型生成的 tool call。
2. executor 只在“当前 run 可见工具”里查找这个名字。
3. unknown tool 不抛异常，而是返回 `ok=False` 的 `ToolResult`。
4. 具体工具异常也会变成 failed observation。
5. `_normalize_result()` 保证返回结果的 `tool_call_id` 和 `name` 接回原始请求。
6. `_limit_result()` 按工具 metadata 截断输出，避免网页或图片工具把上下文撑爆。

具体例子：

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
```

状态变化：

- 不存在的工具不会让 FastAPI 崩溃。
- 工具异常不会打断整个 run。
- 失败也会进入下一轮模型上下文。

读者 takeaway：工具失败是 agent 可以观察和修正的状态。

</details>

<details>
<summary>展开：多个工具调用如何串并行分区</summary>

模型一次可能返回多个 tool calls。Klara 不按具体工具名硬编码顺序，而是按 metadata 形成 execution waves。

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

def _can_run_in_parallel(self, call: ToolCall) -> bool:
    tool = self._tools.get(call.name)
    if tool is None:
        return False
    return tool.metadata.parallel_safe and not tool.metadata.requires_approval
```

算法：

```text
parallel_safe=True 且 requires_approval=False
-> 进入当前 parallel wave

parallel_safe=False
或 requires_approval=True
或 unknown tool
-> 先 flush 当前 wave，再单独执行当前 call
```

具体 trace：

```text
[safe A, safe B, serial C, safe D, unknown E]
-> A/B 同一个 wave 并发执行
-> C 单独执行
-> D 单独一个 wave
-> E 单独执行并返回 failed observation
```

为什么图片工具是串行：

```text
image_generate:
  side_effect=NETWORK
  parallel_safe=False
  timeout_seconds=180.0
```

图片生成可能慢、贵、网络依赖强，也会产出本地资产链接，所以先按串行工具处理。

读者 takeaway：并行/串行不是写死工具名，而是读取 metadata。

</details>

## 7. Web 和 Image：工具结果不是事实，只是 observation

`web_search`、`web_fetch`、`image_generate` 都是工具，但它们的风险不同。

```text
web_search     -> 找 title / URL / snippet
web_fetch      -> 读取一个 public HTTP(S) 页面
image_generate -> 调 Qwen 图片模型，保存本地资产，返回 Markdown 图片链接
```

Klara 学到：外部 I/O 能力可以暴露成工具，但 provider、安全校验、资产保存不应该塞进 core loop。

对应代码：

```text
src/klara/tools/builtin/web_search/schema.py
src/klara/tools/builtin/web_fetch/schema.py
src/klara/tools/builtin/image_generate/schema.py
src/klara/services/web/search.py
src/klara/services/web/fetcher.py
src/klara/services/web/safety.py
src/klara/services/images/qwen.py
src/klara/services/images/storage.py
src/klara/services/images/types.py
src/klara/infra/config/images.py
```

<details>
<summary>展开：web_fetch 为什么要放安全边界</summary>

`web_fetch` 可以访问外部 URL，所以 tool wrapper 只负责参数和 observation，网络安全放在 service 层。

工具 wrapper：

```python
page = self.page_fetcher(
    url,
    max_chars=max_chars,
    timeout_seconds=self.metadata.timeout_seconds,
)
return self.json_success(arguments, {...})
```

安全校验：

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

运行状态：

- `http://localhost:8011` 会被拒绝。
- private IP、loopback、带凭据 URL 会被拒绝。
- 网页正文返回时标为 `untrusted_external_content`。

读者 takeaway：web 工具的输出不能当系统指令，只能当不可信 observation。

</details>

<details>
<summary>展开：image_generate 为什么会影响后续上下文</summary>

图片工具返回的是 Markdown 图片链接，最终答案可以把图片穿插在文字中：

```text
![Generated image](/api/assets/local?path=data/assets/images/20260617/xxx.png)
```

这对前端展示是好的，但对下一轮模型历史不一定有用。模型不需要反复看到本地资产 URL；这些 URL 还可能让后续普通问题带上图片语境。

所以本章加入最小 history sanitizer：

```python
GENERATED_IMAGE_PLACEHOLDER = "[generated image omitted from prior context]"

def prepare_conversation_history(
    messages: Iterable[KlaraMessage],
    *,
    max_messages: int,
) -> tuple[KlaraMessage, ...]:
    prepared: list[KlaraMessage] = []
    for message in messages:
        prepared.append(
            KlaraMessage(
                role=message.role,
                content=sanitize_history_content(message.content),
                name=message.name,
                tool_call_id=message.tool_call_id,
                tool_calls=message.tool_calls,
            )
        )
    return tuple(prepared[-max_messages:])
```

API 层调用它：

```python
MAX_HISTORY_MESSAGES = 12
...
return prepare_conversation_history(history, max_messages=MAX_HISTORY_MESSAGES)
```

注意这里有两个不同的 12：

- `LoopPolicy.max_turns = 12`：一个 run 最多 12 个模型 turn，防止无限工具循环。
- `MAX_HISTORY_MESSAGES = 12`：下一次 run 最多注入当前 session 最近 12 条 completed user/assistant 消息。

状态变化：

- 历史按 session 读取，不跨聊天窗口污染。
- 只注入 completed user/assistant 消息，不回放运行中的消息。
- 本地图片链接被替换成短 placeholder。
- 这还不是完整 context compression；完整压缩、source summary、memory 会在后面章节讲。

读者 takeaway：工具越多，越需要清楚地区分“用户可见内容”和“下一轮模型应该看见的上下文”。

</details>

## 8. 运行与验证

启动：

```powershell
.\scripts\dev.ps1 -Restart
```

默认地址：

```text
Web: http://127.0.0.1:5123
API: http://127.0.0.1:8011
```

建议验证：

```powershell
python -m pytest tests\klara tests\apps\api
cd apps\web
npm.cmd test
npm.cmd run build
```

前端观察点：

```text
llm_call_completed.tool_call_count
tool_call_started
tool_call_completed
run_completed.stop_reason
```

如果你想复现“世界杯问题”，可以在一个新窗口里问：

```text
请搜索世界杯最新战报，并打开一个网页总结。
```

再追问：

```text
阿根廷呢？
```

观察右侧事件里第二问是否继续产生 `web_search` / `web_fetch`。如果没有，这不是靠关键词 if 修的地方，而是后续 context policy、tool-use evaluation、source grounding 要继续推进的地方。

## 小实验

1. 把 `current_time` 的 `max_output_chars` 改小，观察 executor 截断。
2. 构造两个 parallel-safe 测试工具和一个 serial 工具，观察 `execute_many()` 如何切 wave。
3. 请求不存在的工具名，确认 loop 返回 failed observation。
4. 请求 `web_fetch` 读取 `http://localhost:8011`，确认安全层拒绝。
5. 生成图片后继续问搜索问题，观察 history sanitizer 如何把本地图片链接替换成 placeholder。

## 下一章预告

Chapter 3 会讲 Hooks And Trace：工具调用已经能发生，下一步是把 runtime 生命周期事件投影到 hook、trace、UI 和 guard 里，而不是把观察逻辑写进 loop 主体。
