# Chapter 2: Tool Calling

Language: [中文](./ch02-tool-calling.md) | English

Previous: [Chapter 1: Minimal LLM Loop](./ch01-minimal-agent-loop.en.md)
Next: Chapter 3: Hooks And Trace
Roadmap: [Klara Roadmap](../skills/roadmap.md)

---

## The Chapter In One Sentence

The Chapter 1 loop stays the same; this chapter turns "the model wants a tool" into a registered, executable, recoverable, observable runtime boundary.

![Klara Chapter 2 Tool Calling](../assets/ch02-tool-calling.png)

| What Klara sees | What runtime does |
| --- | --- |
| assistant returns `tool_calls` | Do not finish yet; enter tool execution |
| `tool_call.name` exists in the registry | Call that tool and wrap the result as `ToolResult` |
| `tool_call.name` is missing | Return a failed observation instead of crashing |
| tool arguments or execution fail | Return a failed observation visible to the next model turn |
| tool succeeds | Append a `role="tool"` observation and continue |
| assistant has no `tool_calls` | Return the final answer and stop |

## Quick Experience

After `.env` is ready, start backend and frontend:

```powershell
.\scripts\dev.ps1
```

Open:

```text
http://127.0.0.1:5123
```

Start with the stable local tool:

```text
Please use current_time to check the current time in Asia/Shanghai, then answer in one sentence.
```

You should see: Klara requests `current_time`, runtime returns a time observation, and the model writes the final answer from that observation.

Then inspect tool error recovery:

```text
Please use current_time to check the current time in Mars/Olympus.
```

You should see: the tool returns a failed observation instead of crashing the backend; the next model turn can explain that the timezone is unknown.

Finally inspect read-only web tools:

```text
Please use web_search to search for python docs, then use web_fetch to open the first result and summarize it.
```

`web_search` finds candidates; `web_fetch` reads one URL. External page content is marked as an untrusted observation.

You can also try the media tool:

```text
Generate a warm Klara desk illustration and show the image in the answer.
```

You should see: Klara calls `image_generate`, the tool downloads Qwen's short-lived image URL into a local asset, and the final answer embeds the image with Markdown beside normal text.

---

## 1. What Changes In This Chapter

Chapter 1 already has the loop:

```text
messages + tools -> LLM -> assistant message
assistant has tool_calls -> runtime executes tools -> tool observation -> next LLM turn
assistant has no tool_calls -> final answer -> stop
```

This chapter does not change that loop. It changes the tool execution boundary:

```text
hardcoded placeholder branch
-> registry lookup
-> selected tool handler
-> ToolResult observation
```

Klara learns: the model may request an action, but runtime owns action lookup, risk signals, error recovery, and output limits.

Code:

```text
src/klara/core/loop.py
src/klara/core/tool_executor.py
src/klara/core/tools.py
```

<details>
<summary>Expand: why the loop does not know concrete tools</summary>

This code runs inside each turn of `KlaraLoop.run()`. Its input is not a concrete tool. Its input is the current transcript, system prompt, model id, and the `ToolSpec` list exposed by the executor.

Input and output:

- Input: `messages` is the transcript so far, and `self.tool_executor.specs` is the model-visible contract for the tools available in this run.
- Output: if the assistant has no `tool_calls`, return the final `KlaraRunResult`; if it has `tool_calls`, append tool observations and continue to the next turn.

Real execution order:

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

How to read this code:

1. `self.llm.complete(...)` is one model turn. The loop gives the model `messages`, `system_prompt`, `model`, and `tools`; it does not pass Python tool objects.
2. `tools=self.tool_executor.specs` is the key boundary. The model sees tool names, descriptions, and parameter schemas, not classes such as `CurrentTimeTool` or `WebFetchTool`.
3. `messages.append(KlaraMessage(role="assistant", ...))` records the assistant output before tools run. Even when the assistant requests tools, this message belongs in the transcript because later tool messages answer it.
4. `if not response.tool_calls` is the stop signal. With no tool request, `response.content` is the final answer.
5. `execute_many(response.tool_calls)` delegates all tool requests to the executor. The loop does not inspect tool names or decide which tools are safe.
6. Each `ToolResult` becomes a `role="tool"` message. `tool_call_id` joins the observation back to the assistant tool call, and `name` lets trace/UI show which tool produced it.
7. `content=result.content if result.ok else result.error or ""` turns both success and failure into model-visible text. A tool failure does not crash the loop; it becomes an observation for the next model turn.

Concrete example:

```text
assistant: tool_calls=[{"id": "call-1", "name": "current_time", "arguments": {"timezone": "Asia/Shanghai"}}]
executor: ToolResult(tool_call_id="call-1", name="current_time", ok=True, content="{...}")
loop: append role="tool", tool_call_id="call-1", name="current_time"
next turn: the model sees the time observation and can write the final answer
```

Runtime state changes:

- The LLM sees only `ToolSpec`, not Python classes.
- The assistant message is appended before tools run, preserving what the model requested.
- If there are no `tool_calls`, the run stops.
- If there are `tool_calls`, the loop delegates to `ToolExecutor`.
- Each tool result becomes a `role="tool"` message visible to the next model turn.

Architecture boundary: `core.loop` knows `ToolExecutor` and `ToolResult`; it does not know `current_time`, `web_search`, or any future concrete tool.

Takeaway: the loop owns model turns and message state; concrete capabilities must stay behind the executor and capability layers.

</details>

## 2. Tools Have Two Contracts: Spec For Model, Metadata For Runtime

A tool is not just a function name. Klara splits every tool into two contracts:

```text
ToolSpec       -> model-visible: when to use it and how to fill arguments
ToolMetadata   -> runtime-visible: risk, parallelism, approval, output limit, trust
```

The main example is `current_time`. It is the best teaching tool here: no network, no key, stable output, controlled errors.

Code:

```text
src/klara/core/tools.py
src/klara/capabilities/tools/current_time/schema.py
```

<details>
<summary>Expand: current_time ToolSpec</summary>

`ToolSpec` is model-visible. It answers "how may the model request this tool?", not "how does runtime execute it?"

Input and output:

- Input: the tool author declares `name`, `description`, and `input_schema` in `schema.py`.
- Output: the LLM client converts these fields into the provider's tool/function schema.

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

How to read this code:

- `name="current_time"` is the exact string the model must produce in `tool_call.name`; it is also the lookup key used later by the executor.
- `description` is usage guidance for the model. It says this tool answers current-time questions, not historical facts or web facts, so the model does not misuse it as search.
- `input_schema.type="object"` means arguments must be a JSON object. Klara keeps tool arguments JSON-compatible for traces, tests, and provider adapters.
- `timezone` is the only parameter and is not required, so the model may pass `{}` when the user did not specify a timezone.
- `additionalProperties=False` tells the model not to send fields such as `city`, `locale`, or `format` that this tool does not understand.

Field flow in this chapter:

| Field | Who reads it | Current behavior |
| --- | --- | --- |
| `name` | LLM and `ToolExecutor` | The model requests the tool by this name; the executor looks up the instance by this name |
| `description` | LLM | Helps the model decide when to call the tool |
| `input_schema` | LLM provider / adapter | Constrains the JSON argument shape the model should generate |

Concrete example:

```text
User asks: what time is it in Shanghai?
After seeing ToolSpec, the model may generate:
ToolCall(name="current_time", arguments={"timezone": "Asia/Shanghai"})
```

Runtime state changes:

- The LLM sees the tool name `current_time`.
- The LLM knows it may pass `timezone`.
- `additionalProperties=False` discourages unrelated arguments.
- The execution function, Python module path, and metadata are not exposed to the model.

Takeaway: `ToolSpec` describes how the model may request a tool. It is not the execution policy.

</details>

<details>
<summary>Expand: current_time ToolMetadata</summary>

`ToolMetadata` is runtime-visible. It does not enter model context; it exists for the executor, trace, UI, later guards, and policy.

Input and output:

- Input: the tool author declares the runtime safety, parallelism, display, and output boundaries.
- Output: the executor and upper runtime layers use these fields to decide how to execute, truncate, and present the tool.

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

How to read this code:

- `label="Current Time"` is the human-facing name, suitable for trace or UI. It does not have to match the call name.
- `category="time"` lets UI, trace, or future profiles group tools.
- `side_effect=ToolSideEffect.NONE` says this tool does not read the network, write files, or control the system.
- `parallel_safe=True` is already consumed by the current executor. It allows multiple safe tools to run in the same wave.
- `timeout_seconds=1.0` is this tool's execution budget signal; network tools pass this value into the service layer.
- `max_output_chars=1000` is already consumed by the current executor. Observations longer than this are truncated.

Field flow in this chapter:

| Field | Who reads it | Current behavior | Future behavior |
| --- | --- | --- | --- |
| `label` / `category` | trace/UI | Display and grouping | capability profiles |
| `side_effect` | runtime policy | Kept as a risk signal | approval, permissions, profiles |
| `parallel_safe` | `ToolExecutor._can_run_in_parallel()` | Controls whether a call may enter a parallel wave | finer scheduling |
| `requires_approval` | `ToolExecutor._can_run_in_parallel()` | Approval-gated calls split waves | approval UI |
| `timeout_seconds` | tool/service adapter | Passes an execution or network budget | unified timeout policy |
| `max_output_chars` | `ToolExecutor._limit_result()` | Truncates model-visible output | token budget policy |
| `output_trust` | trace/prompt guard | Kept as a trust signal | web-injection defense |

Runtime state changes:

- Runtime knows this tool has no side effects.
- The executor may place it in a parallel wave.
- The output limiter knows how much text may be exposed to the model.
- Trace/UI can show a human-facing label and category.

Takeaway: metadata is not prompt text; it is a runtime signal for planning, guarding, truncation, and presentation.

</details>

## 3. Each Tool Is A Package, Not A Loose Function

Klara uses one package per model-visible tool:

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

This shape keeps responsibilities visible:

- `schema.py`: model contract and runtime metadata.
- `tool.py`: argument validation, service call, observation formatting.
- domain helpers: for example `timezones.py`.
- external providers or complex I/O: live under `src/klara/services/`.

Code:

```text
src/klara/capabilities/tools/current_time/
src/klara/capabilities/tools/image_generate/
src/klara/capabilities/tools/web_search/
src/klara/capabilities/tools/web_fetch/
tests/klara/architecture/test_boundaries.py
```

Klara learns: adding a tool should not put concrete tool names into core, frontend, or loop branches.

## 4. Registry Decides Which Tools Are Visible

The model should not see every future capability. Each run exposes only the visible tools selected by the registry.

```text
klara.capabilities.tools.*
-> discover package
-> import <tool_package>.tool
-> find exactly one BaseTool subclass
-> instantiate it
-> visible_tools()
```

Code:

```text
src/klara/capabilities/registry.py
tests/klara/capabilities/test_registry.py
```

<details>
<summary>Expand: automatic local tool discovery</summary>

This code discovers local tools under `src/klara/capabilities/tools/` instead of keeping a handwritten default list in the registry.

Input and output:

- Input: child packages under `klara.capabilities.tools`, such as `current_time`, `web_fetch`, and `web_search`.
- Output: the single concrete `BaseTool` subclass from each tool package, returned in package-name order.

Real code:

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

How to read this code:

1. `pkgutil.iter_modules(...)` scans the direct children of the `klara.capabilities.tools` package.
2. `sorted(..., key=lambda item: item.name)` fixes discovery order, so tool order does not drift across machines or filesystems.
3. `if not module_info.ispkg: continue` accepts only packages. A tool must live in its own directory, not as a loose `.py` file.
4. `importlib.import_module(f"{module_info.name}.tool")` imports only the `tool.py` file inside each package, making the implementation entrypoint stable.
5. `inspect.getmembers(..., inspect.isclass)` finds classes defined in that module.
6. `issubclass(value, BaseTool)` ensures the class follows Klara's local tool template.
7. `value.__module__ == tool_module.__name__` excludes imported classes, so `BaseTool` or helper classes are not mistaken for the current tool.
8. `len(candidates) != 1` fails fast. One tool package may expose exactly one concrete tool, otherwise the registry cannot know which class should be model-visible.
9. `discovered.append(candidates[0])` records the class itself; `discover_local_tools()` later instantiates it.

Concrete example:

```text
tools/current_time/tool.py  -> CurrentTimeTool
tools/image_generate/tool.py -> ImageGenerateTool
tools/web_fetch/tool.py     -> WebFetchTool
tools/web_search/tool.py    -> WebSearchTool
```

If `web_fetch/tool.py` accidentally defines two `BaseTool` subclasses, default registry startup fails instead of silently exposing an ambiguous tool.

Runtime state changes:

- The registry does not maintain a handwritten default tool list.
- A new tool becomes visible when it follows the package shape.
- Each package must expose exactly one concrete `BaseTool`, so both runtime and readers know what is visible.
- Tool order is deterministic, which keeps tests, traces, and model-visible specs stable.

The current default set is locked by test:

```python
assert names == {"current_time", "image_generate", "web_fetch", "web_search"}
```

Takeaway: the registry owns visibility. It is not the executor.

</details>

## 5. Executor Handles Lookup, Execution, Recovery, And Truncation

`ToolExecutor` is the narrow gate between a model request and a concrete tool.

```text
ToolCall(id, name, arguments)
-> lookup visible tools by name
-> tool.execute(arguments)
-> normalize id/name
-> limit output
-> ToolResult
```

Code:

```text
src/klara/core/tool_executor.py
tests/klara/core/test_tool_executor.py
```

<details>
<summary>Expand: how one tool call becomes an observation</summary>

This code is the protection layer between a model request and a concrete tool. The model produces a `ToolCall`; the executor turns it into a stable `ToolResult`.

Input and output:

- Input: `ToolCall(id, name, arguments)`, where `id` comes from the model response, `name` is the requested tool name, and `arguments` is the model-generated JSON argument object.
- Output: always return a `ToolResult`. Success, unknown tools, tool exceptions, and long outputs all collapse into the same observation shape.

Real code:

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

How to read this code:

1. `tool = self._tools.get(call.name)` looks up the model-provided name in the visible tool map for this run. `self._tools` is built from the registry-selected tools, not from a global tool table.
2. `tool is None` is the unknown-tool branch. Even if the model requests a missing tool, runtime returns an `ok=False` `ToolResult` instead of throwing.
3. `tool_call_id=call.id` in the unknown-tool result matters. The next tool message can still join back to the assistant's original tool call.
4. `tool.execute(call.arguments)` is the only point where concrete tool code runs. The executor does not know whether the tool is time, search, fetch, or future RAG.
5. `except Exception as exc` is the last line of defense. Concrete tools should not throw casually, but if they do, the executor still converts the exception into a failed observation.
6. `_normalize_result(call, result)` repairs mismatched `tool_call_id` and `name`. Concrete tools can build simple results; the executor guarantees transcript join keys.
7. `_limit_result(..., max_chars=tool.metadata.max_output_chars)` enforces the model-visible output boundary. No matter how long a tool output is, it is truncated before the next model turn.

Concrete example: the model requests a missing tool.

```text
call = ToolCall(id="call-9", name="read_file", arguments={"path": "x"})

executor cannot find read_file and returns:
ToolResult(
  tool_call_id="call-9",
  name="read_file",
  content="",
  ok=False,
  error="Unknown tool: read_file",
)

The loop then appends this result as a role="tool" message.
The next model turn sees "the tool failed" instead of a backend crash.
```

Runtime state changes:

- An unknown tool becomes a failed observation.
- A Python exception inside a tool becomes a failed observation.
- If the returned id/name does not match the original request, the executor normalizes it.
- Output longer than `metadata.max_output_chars` is truncated before the model sees it.

Takeaway: tool failure is model-visible runtime state, not a backend crash.

</details>

## 6. BaseTool Turns Argument Errors Into Failed Observations

Each local tool inherits `BaseTool`. This is not a core requirement; it is an authoring template for local tools.

Code:

```text
src/klara/capabilities/base_tool.py
src/klara/capabilities/tools/current_time/tool.py
tests/klara/capabilities/test_current_time_tool.py
```

<details>
<summary>Expand: why ToolInputError does not crash the loop</summary>

This code is the local authoring template for tools. Core only requires the `KlaraTool` protocol, but local tools inherit `BaseTool` so they can share argument helpers, JSON output, and failed-observation construction.

Input and output:

- Input: JSON-like `arguments` generated by the model.
- Output: on success, return the concrete tool's `ToolResult`; on argument error, return an `ok=False` `ToolResult`.

Real code:

```python
def execute(self, arguments: JsonObject) -> ToolResult:
    try:
        return self.run(arguments)
    except ToolInputError as exc:
        return self.failure(arguments, str(exc))
```

Failure path in `current_time`:

```python
timezone_name = str(arguments.get("timezone") or "").strip()
try:
    resolved_name, resolved_timezone = resolve_timezone(timezone_name)
except ValueError as exc:
    return self.failure(arguments, str(exc))
```

How to read this code:

1. `BaseTool.execute()` is the entrypoint called by the executor. The executor does not call `run()` directly because `execute()` owns consistent input-error handling.
2. `self.run(arguments)` is the concrete tool implementation, such as `CurrentTimeTool.run()`.
3. `ToolInputError` means "the model-provided arguments do not match this tool contract." That error is recoverable agent state.
4. `self.failure(arguments, str(exc))` builds `ToolResult(content="", ok=False, error=...)` and uses the tool's own `spec.name`.
5. In `current_time`, `timezone_name = str(arguments.get("timezone") or "").strip()` collapses missing values, empty strings, and padded strings into one clean input.
6. `resolve_timezone(timezone_name)` is the domain validation step. On success it returns a normalized timezone name and timezone object; on failure it raises `ValueError`.
7. `except ValueError as exc: return self.failure(...)` converts a domain error into a failed observation.

Concrete example:

```text
arguments={"timezone": "Mars/Olympus"}
-> resolve_timezone("Mars/Olympus") raises ValueError
-> CurrentTimeTool returns ok=False
-> loop appends role="tool" with error text
-> the model can apologize or ask for a valid IANA timezone
```

Runtime state changes:

- A bad timezone such as `Mars/Olympus` does not escape to FastAPI or the frontend.
- The tool returns `ok=False`, `content=""`, and `error="Unknown timezone: Mars/Olympus"`.
- The loop appends that error as a tool message for the next model turn.

Takeaway: tool errors are observations inside the agent loop.

</details>

## 7. Partitioning: Metadata Creates Execution Waves

The model may request several tool calls in one assistant turn. Klara does not hard-code ordering by concrete tool name; it partitions calls by metadata.

Current rule:

```text
parallel_safe=True and requires_approval=False
-> may enter the same parallel wave

parallel_safe=False
or requires_approval=True
or unknown tool
-> split the wave and execute separately
```

Code:

```text
src/klara/core/tool_executor.py
src/klara/core/tools.py
tests/klara/core/test_tool_executor.py
```

<details>
<summary>Expand: how execute_many splits execution waves</summary>

This code handles the case where one assistant turn returns several tool calls. It does not run everything serially, and it does not blindly run everything in parallel. It partitions calls into execution waves based on metadata.

Input and output:

- Input: `tuple[ToolCall, ...]` returned by the model in one assistant turn; order is the model request order.
- Output: `tuple[ToolResult, ...]`; result order still matches request order.

Real code:

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

Decision function:

```python
def _can_run_in_parallel(self, call: ToolCall) -> bool:
    tool = self._tools.get(call.name)
    if tool is None:
        return False
    return tool.metadata.parallel_safe and not tool.metadata.requires_approval
```

Parallel wave execution:

```python
def _execute_parallel_wave(self, calls: tuple[ToolCall, ...]) -> tuple[ToolResult, ...]:
    if not calls:
        return ()
    if len(calls) == 1:
        return (self.execute(calls[0]),)
    with ThreadPoolExecutor(max_workers=len(calls)) as pool:
        return tuple(pool.map(self.execute, calls))
```

How to read this code:

1. `results` stores completed outputs and eventually becomes the returned tuple.
2. `parallel_wave` collects the current contiguous run of calls that are safe to run together.
3. If `_can_run_in_parallel(call)` is true, the call is added to `parallel_wave` and execution is deferred.
4. If a non-parallel call appears, the executor first flushes the current `parallel_wave`, then runs the non-parallel call alone.
5. After the loop, the executor flushes one final time so a trailing safe wave is not lost.
6. `_can_run_in_parallel()` reads only the visible tool map and two metadata fields: `parallel_safe` and `requires_approval`.
7. Unknown tools return false because runtime cannot prove they are safe; they run alone through `execute()` and become failed observations.
8. `_execute_parallel_wave()` has separate branches for 0, 1, and many calls. Only many calls create a `ThreadPoolExecutor`, and `pool.map` preserves input order, so concurrent execution does not reorder observations.

Concrete trace:

```text
calls = [safe A, safe B, serial C, safe D, unknown E]

safe A -> parallel_wave=[A]
safe B -> parallel_wave=[A, B]
serial C -> run [A, B] concurrently, then run C alone
safe D -> parallel_wave=[D]
unknown E -> run [D], then run E alone; E returns a failed observation

final result order is [A_result, B_result, C_result, D_result, E_failed]
```

Runtime state changes:

- Consecutive parallel-safe calls may run through a thread pool.
- Serial or approval-gated calls split the current wave.
- Unknown tools split the wave because runtime cannot prove they are safe.
- Results keep the original model request order.

Be precise:

- `parallel_safe` and `requires_approval` currently participate in wave partitioning.
- `side_effect` is currently a risk classification signal for later permissions, UI, profiles, and policies.
- `output_trust` is currently an observation trust signal for later prompt wrappers, web-injection defense, trace, and UI.

Takeaway: partitioning should read metadata, not concrete tool names.

</details>

## 8. Web Tools Show Why Metadata Matters

`current_time` teaches the minimal tool template; `web_search` and `web_fetch` teach risk boundaries.

```text
web_search -> find URLs, titles, snippets
web_fetch  -> read the body of one public HTTP(S) page
```

They are not a research agent in this chapter. They exist here to show:

- network tools carry `side_effect=NETWORK`
- external page content carries `output_trust=UNTRUSTED`
- provider/page parsing belongs in the service layer, not core
- a tool observation is input to the model, not guaranteed truth

Code:

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
<summary>Expand: why web_fetch does not put urllib directly in tool.py</summary>

`web_fetch` is the risk-boundary example in this chapter. It can access the external network, so the implementation should not pile every concern into `tool.py`. The tool wrapper owns arguments, metadata, and observation formatting; network behavior belongs in the service layer.

Input and output:

- Input: model-generated `{"url": "...", "max_chars": ...}`.
- Output: on success, return a JSON observation with page text; on failure, return an `ok=False` observation.

The tool wrapper owns model contract and observation formatting:

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

Network behavior lives in the service layer:

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

How to read the tool wrapper:

1. `spec` and `metadata` come from `schema.py`, so model contract and runtime signals stay centralized.
2. `page_fetcher: PageFetcher = fetch_page` is the dependency injection point. Tests can pass a fake fetcher without touching the network.
3. `url = self.optional_string(arguments, "url")` reuses a `BaseTool` argument helper; non-string input becomes `ToolInputError`.
4. `if not url` is required-argument validation. An empty URL is a model argument error, not a network error.
5. `_optional_int(..., default=4000)` reads the optional length limit; `200 <= max_chars <= 6000` prevents the model from requesting page text that is too small or too large.
6. `self.page_fetcher(... timeout_seconds=self.metadata.timeout_seconds)` passes runtime metadata into the service layer. The tool does not implement socket or HTTP details itself.
7. `except WebFetchError as exc` converts service-layer fetch failures into failed observations.
8. `trust="untrusted_external_content"` tells later layers that page text is not trusted system instruction; it is external observation data.

How to read the safety service:

1. `raw_url.strip()` removes surrounding whitespace; an empty string is rejected.
2. `parsed.scheme not in {"http", "https"}` rejects protocols such as `file://` and `ftp://`.
3. `not parsed.hostname` rejects URLs without a host.
4. `parsed.username or parsed.password` rejects credential-bearing URLs so secrets do not enter requests or traces.
5. `_reject_local_hostname(host)` rejects `localhost` and `.localhost`.
6. `_reject_private_addresses(host)` checks literal IPs and DNS-resolved addresses.
7. `not address.is_global` rejects private, loopback, link-local, reserved, and other non-public addresses.
8. `parsed._replace(fragment="")` removes URL fragments because fragments are not sent to the server and should not affect fetch cache or trace identity.

Concrete examples:

```text
url="https://docs.python.org/3/"
-> scheme is https
-> host resolves to public addresses
-> service fetches HTML and extracts text
-> tool returns a JSON observation with trust="untrusted_external_content"

url="http://localhost:8011"
-> _reject_local_hostname("localhost")
-> WebFetchError / WebSafetyError
-> tool returns a failed observation
```

Runtime state changes:

- The tool layer stays short enough to teach and register.
- The service layer owns URL validation, redirect validation, HTML extraction, and length limits.
- `localhost` and private IP addresses are rejected so `web_fetch` cannot become a local-network probe.
- Page text returns with `trust="untrusted_external_content"`.

Takeaway: external I/O can be exposed as a tool, but provider and safety boundaries belong in services.

</details>

## 9. What This Chapter Does Not Do

These boundaries are intentionally later:

- full approval UI
- shell/filesystem mutation tools
- Bing, Google, Baidu, or Brave account-backed provider routing
- MCP
- RAG or research-agent behavior

Klara only learns this here: a tool is a registered, executable, recoverable, observable runtime action boundary.

## Run And Verification

Start the dev environment:

```powershell
.\scripts\dev.ps1 -Restart
```

Default URLs:

```text
Web: http://127.0.0.1:5123
API: http://127.0.0.1:8011
```

Chapter-related checks:

```powershell
python -m pytest --basetemp .tmp\pytest
cd apps\web
npm.cmd test
npm.cmd run build
```

Optional real-network smoke test:

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

## Small Experiments

1. Change `current_time` `max_output_chars` and observe executor truncation.
2. Set a fixture tool's `parallel_safe` to `False` and watch `execute_many()` split waves.
3. Request a missing tool name and confirm the loop returns a failed observation.
4. Ask `web_fetch` to read `http://localhost:8011` and confirm the safety layer rejects it.
5. Add `allowed_domains=["python.org"]` to `web_search` and observe filtering.

## Next Chapter Preview

Chapter 3 covers Hooks And Trace: now that tool calls can happen, the next step is to project runtime lifecycle events into trace, UI, and later guards without putting observation logic into the loop body.
