# Chapter 1: Minimal LLM Loop

Language: [中文](./README.md) | English

Previous: none  
Next: Chapter 2: Tool Calling, Registry, And Capability Partitioning  
Roadmap: [Klara Roadmap](./docs/skills/roadmap.md)

---

## What This Chapter Builds

This chapter gives Klara the smallest real LLM loop.

Klara can receive user input, call a real LLM, check whether the model requested tools, execute those tools, put tool observations back into the next turn, and record public trace events through hooks.

This chapter focuses on:

- how the LLM is called
- how the loop organizes turns
- how tool calls return to the next model turn
- why hooks are the trace and frontend event attachment point
- why the harness assembles a run instead of letting the core loop read config

This chapter does not build the full agent, RAG, memory, complex permissions, or RL. It builds the runtime skeleton that later capabilities will attach to.

![Klara Chapter 1 Minimal LLM Loop](./docs/assets/ch01-minimal-loop.png)

## The Loop Idea

The old pipeline shape is a fixed path:

```text
question
-> retrieve
-> prompt
-> answer
```

Klara starts as a loop:

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

Input:

- user message
- Klara system prompt
- model id
- visible tools
- hook manager
- loop policy

Output:

- final answer
- stop reason
- transcript messages
- public trace events

Klara learns: an agent run is not a black-box model call. It is an observable, testable, continuable, stoppable runtime loop.

## Code Map

Core loop:

```text
src/klara/core/loop.py
```

Messages, tools, events, and hooks:

```text
src/klara/core/messages.py
src/klara/core/tools.py
src/klara/core/events.py
src/klara/core/hooks.py
src/klara/core/tool_executor.py
src/klara/core/policies.py
```

App-layer assembly:

```text
src/klara/app/harness.py
apps/api/services/run_service.py
```

Real LLM providers:

```text
config/models.toml
src/klara/infra/llm/openai_compatible.py
src/klara/infra/llm/routed_client.py
```

Config and startup:

```text
.env.example
config/README.md
scripts/dev.ps1
```

---

## 1. The Harness Assembles One Run

The core loop should not know environment variables, frontend state, storage paths, user settings, or product persona.  
The harness assembles those dependencies and injects them into the loop.

```text
user input
-> KlaraHarness
-> persona + model + tools + hooks + policy
-> KlaraLoop
```

Klara learns: core executes runtime logic; the app layer assembles the runtime world.

Code:

```text
src/klara/app/harness.py
```

<details>
<summary>Expand: how the harness injects trace hooks and tools</summary>

Real code:

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

This code:

- creates a run-local `HookManager`
- registers `JsonlTraceHook` when a trace path exists
- injects LLM, tools, hooks, policy, model, and system prompt into `KlaraLoop`

The key boundary: `KlaraLoop` does not read `.env`, create trace files, or choose tools. It receives prepared dependencies.

</details>

## 2. The Loop Receives Dependencies

Klara's core loop is the runtime core, not the product entry point. It receives dependencies and executes the loop.

```text
llm + tool_executor + hooks + policy + model + system_prompt
-> KlaraLoop
```

Klara learns: keep the loop small and inject dependencies explicitly.

Code:

```text
src/klara/core/loop.py
```

<details>
<summary>Expand: reading KlaraLoop.__init__</summary>

Real code:

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

Parameters:

- `llm`: the model client.
- `tool_executor`: the boundary that executes requested tools.
- `hooks`: the runtime lifecycle event outlet.
- `policy`: loop boundaries such as max turns.
- `model`: the selected model for this run.
- `system_prompt`: Klara's identity and behavior constraints.

Real code:

```python
# Dependencies are injected so core stays independent of providers/services.
self.llm = llm
self.tool_executor = tool_executor
self.hooks = hooks or HookManager()
self.policy = policy or LoopPolicy()
self.model = model
self.system_prompt = system_prompt
```

The point is the boundary:

- providers are not created in core
- trace sinks are not created in core
- frontend bridges are not created in core
- visible tools are not discovered in core

</details>

## 3. A Run Starts From One User Message

The first step is not the model call. The run first needs a stable identity and one user message.

```text
user_input
-> run_id
-> [KlaraMessage(role="user")]
-> run.started event
```

Klara learns: trace, frontend events, and tests need the same `run_id` join key.

Code:

```text
src/klara/core/loop.py
src/klara/core/messages.py
src/klara/core/events.py
```

<details>
<summary>Expand: the beginning of run()</summary>

Real code:

```python
# Active run id is the trace join key across all lifecycle events.
active_run_id = run_id or str(uuid4())
# Messages begin with exactly one user message; later turns append to it.
messages: list[KlaraMessage] = [KlaraMessage(role="user", content=user_input)]
self._emit(active_run_id, "run.started", {"model": self.model})
```

Line by line:

- `active_run_id` identifies the run.
- tests and APIs can pass a stable `run_id`.
- otherwise, the loop generates a UUID.
- `messages` starts with one user message.
- `run.started` is emitted to hooks, not directly written as a log.

Trace is therefore not hardcoded logging inside the loop. The loop emits events; `JsonlTraceHook` writes them.

</details>

## 4. The Loop Calls the LLM

Each turn sends the current transcript, system prompt, tool specs, and model id to the LLM client.

```text
system_prompt + messages + tool specs + model
-> llm.complete(...)
-> ModelResponse
```

Klara learns: the LLM call is one step inside the loop, not the whole agent.

Code:

```text
src/klara/core/loop.py
src/klara/core/types.py
src/klara/infra/llm/openai_compatible.py
```

<details>
<summary>Expand: LLM call code</summary>

Real code:

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

The call receives:

- `system_prompt`: Klara's behavior contract.
- `messages`: the visible transcript so far.
- `tools`: the tool schemas visible to the model.
- `model`: the selected model.

The result is a `ModelResponse`, which may contain final text or tool calls.

</details>

## 5. If the Model Requests Tools, Runtime Executes Them

The model does not execute tools by itself. It can only request tool calls.  
The runtime executes them through `ToolExecutor`.

```text
ModelResponse.tool_calls
-> ToolExecutor.execute(call)
-> ToolResult
-> tool observation message
```

Klara learns: tools are runtime capabilities, not model magic.

Code:

```text
src/klara/core/tools.py
src/klara/core/tool_executor.py
src/klara/capabilities/tools/fake_tool.py
```

<details>
<summary>Expand: how a tool call becomes an observation</summary>

Real code:

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

Tool results are not hidden state. They become `role="tool"` messages so the next LLM turn can see the observation.

</details>

## 6. prepare_next_turn Is Minimal, But the Boundary Exists

Chapter 1 keeps `prepare_next_turn` as identity: no compression, rewriting, or memory injection yet.  
The boundary exists now because later context compression, memory, RAG, and tool effects need it.

```text
messages
-> prepare_next_turn(messages)
-> messages for next LLM turn
```

Klara learns: the next-turn context needs a deliberate preparation phase.

Code:

```text
src/klara/core/loop.py
```

<details>
<summary>Expand: the minimal prepare_next_turn step</summary>

Real code:

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

Later chapters can make `prepare_next_turn` do real work without changing the loop shape.

</details>

## 7. The Loop Must Explain Why It Stopped

Klara should not merely be "done." She should know why the loop ended.

```text
no tool calls -> final answer
max turns -> max_turns stop reason
unexpected error -> run.failed
```

Klara learns: stopping is part of runtime policy.

Code:

```text
src/klara/core/loop.py
src/klara/core/policies.py
```

<details>
<summary>Expand: final and max-turn stopping</summary>

If the model does not request tools, the response becomes the final answer:

```python
if not response.tool_calls:
    return self._complete(
        active_run_id,
        messages,
        response.content,
        StopReason.FINAL,
    )
```

If the model keeps requesting tools until the turn budget is exhausted:

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

Completion is still emitted as an event:

```python
self._emit(run_id, "run.completed", {"stop_reason": stop_reason.value})
```

</details>

## 8. Hooks Are the Attachment Point for Trace and UI

Chapter 1 uses hooks as observers.  
They receive events but do not change loop behavior.

```text
KlaraLoop._emit(...)
-> HookManager.emit(event)
-> JsonlTraceHook.on_event(event)
-> frontend bridge on_event(event)
```

Klara learns: trace is not hardcoded logging. It is the first hook implementation.

Code:

```text
src/klara/core/events.py
src/klara/core/hooks.py
apps/api/services/run_service.py
tests/klara/core/test_hooks.py
```

<details>
<summary>Expand: HookManager and JsonlTraceHook</summary>

Real code:

```python
class KlaraHook(Protocol):
    """Protocol for observers or guards attached to loop lifecycle events."""

    def on_event(self, event: KlaraEvent) -> None:
        """Handle one loop event."""

        ...
```

Chapter 1 only uses observer hooks. Later chapters can introduce `PreToolUse`, `PostToolUse`, and `Stop` lifecycle hooks.

Real code:

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

Real code:

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

Core principle:

```text
loop emits events
hook consumes events
trace is one hook implementation
```

The frontend event stream follows the same model:

```python
usage_totals = _UsageTotals()
bridge = _RunEventBridge(self, run_id, usage_totals)
hooks = HookManager([bridge, JsonlTraceHook(Path(self.trace_path))])
```

</details>

## 9. Real LLM Config Lives in Infra, Not Core

Chapter 1 can use real models, but providers stay in infra.  
The core loop only knows the `LlmClient` protocol.

```text
.env
-> config/models.toml
-> RoutedLlmClient
-> OpenAICompatibleLlmClient
-> KlaraLoop
```

Klara learns: DeepSeek and Qwen are replaceable providers, not part of the loop.

Code:

```text
config/models.toml
config/README.md
src/klara/infra/llm/openai_compatible.py
src/klara/infra/llm/routed_client.py
```

<details>
<summary>Expand: why real LLM support does not change the loop</summary>

The core loop only needs:

```text
complete(system_prompt, messages, tools, model) -> ModelResponse
```

Provider details stay outside core:

- API key
- base URL
- provider name
- HTTP response shape
- retry strategy
- model routing

Required keys:

```text
DEEPSEEK_API_KEY
DASHSCOPE_API_KEY
```

Current chat models:

```text
deepseek/deepseek-v4-flash
deepseek/deepseek-v4-pro
qwen/qwen3.6-flash
qwen/qwen3.6-plus
```

The Qwen image model is configured in `config/images.toml`, but image generation is not part of the Chapter 1 loop. Later it should enter as a tool or capability.

</details>

---

## What This Chapter Does Not Build Yet

This chapter does not build:

- RAG
- memory
- context compression
- skill registry
- scheduled jobs
- permission guards
- complex Stop hooks
- RL / post-training
- multi-user auth

Chapter 1 only establishes Klara's minimal runtime skeleton.

## Run and Verify

1. Create `.env` at the repo root:

```powershell
Copy-Item .env.example .env
```

2. Fill in your keys:

```text
DEEPSEEK_API_KEY=...
DASHSCOPE_API_KEY=...
```

3. Start backend and frontend together:

```powershell
.\scripts\dev.ps1
```

Default URLs:

```text
API: http://127.0.0.1:8011
Web: http://127.0.0.1:5123
```

4. Open the frontend, choose a model, and send a message.

The frontend calls the backend API. The backend runs `KlaraLoop`, projects lifecycle events to the UI, and `JsonlTraceHook` writes public trace events to local JSONL.

5. Run core tests:

```powershell
python -m pytest tests\klara\core\test_hooks.py tests\klara\app\test_harness.py
```

These tests confirm:

- hook failures do not crash the loop
- JSONL trace is written through hooks
- the harness assembles persona, tools, user context, and trace hook

## Next Chapter

Chapter 2 upgrades the minimal tool path into real tool calling and capability partitioning.

Klara will learn:

- how to expose tool schemas to the LLM
- how runtime executes tool calls
- how tool results return as observations for the next turn
- how to select chapter-visible tools from a larger registry
- how to trace tool selection, tool start, tool result, and tool error

Chapter 1's rule remains: the loop owns runtime shape, capabilities attach through boundaries, and trace observes through hooks.
