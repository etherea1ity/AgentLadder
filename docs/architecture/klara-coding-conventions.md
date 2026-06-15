# Klara Coding Conventions

Klara 的代码首先是教学代码，其次才是普通工程代码。

这意味着代码要同时满足三件事：

1. 读者能顺着文件理解一个 agent runtime 是怎么长出来的。
2. 后续章节能扩展能力，但不会把边界写乱。
3. 代码本身足够真实，可以被测试、运行、重构和长期维护。

## 1. Naming Rules

命名要让读者一眼看出边界和职责。

### Public Klara Concepts

公开运行时概念使用 `Klara` 前缀：

```text
KlaraLoop
KlaraMessage
KlaraEvent
KlaraTool
KlaraHarness
KlaraRunResult
```

规则：

- 只给真正属于 Klara public runtime contract 的类加 `Klara` 前缀。
- 不要给所有类都加 `Klara`，否则前缀会失去意义。
- 如果一个概念会出现在 chapter README、测试、外部调用或架构图里，它通常应该用 `Klara` 前缀。

### Internal Helpers

内部 helper 使用直接的领域名：

```text
ToolExecutor
HookManager
LoopPolicy
UserContext
CapabilityRegistry
```

规则：

- helper 名字要说明“管什么”，不要只叫 `Manager`、`Runner`、`Helper`。
- 如果边界更具体，名字也要更具体。
- `ToolExecutor` 比 `ToolManager` 好，因为它只执行工具，不负责工具生态。

### Files And Modules

文件名使用 lowercase snake case：

```text
loop.py
tool_executor.py
user_context.py
fake_tool.py
```

规则：

- 一个文件只承载一个清晰主题。
- 文件名必须能对应 chapter README 里的阅读路径。
- 不使用 `utils.py`、`helpers.py`、`common.py`，除非先写清楚里面的稳定边界。

### Classes, Functions, Variables

```text
ClassName        PascalCase
function_name    snake_case
method_name      snake_case
variable_name    snake_case
CONSTANT_NAME    UPPER_SNAKE_CASE
```

变量命名规则：

- 状态变量要体现生命周期：`active_run_id`、`turn_index`、`messages`。
- 布尔变量要像判断句：`is_visible`、`should_continue`、`has_tool_calls`。
- 集合变量使用复数：`messages`、`tool_calls`、`events`。
- 不使用缩写，除非是行业常识：`llm`、`jsonl`、`id` 可以接受。
- 不使用 `data`、`item`、`obj` 作为长期变量名。

### Tests

测试名写行为，不写实现细节：

```text
test_one_tool_run_feeds_observation_back_to_model
test_core_does_not_import_future_layers
```

规则：

- `test_<condition>_<expected_behavior>` 是默认格式。
- 测试名应该像一句验收标准。
- 重要架构边界必须有 architecture test。

## 2. Folder Rules

`src/klara/core` 只放 runtime mechanics：

- messages
- tool contracts
- events
- hooks
- loop policy
- tool execution boundary
- loop execution

`src/klara/app` 负责组装一次 run：

- persona prompt
- user context
- model choice
- visible tools
- trace hook
- loop policy

`src/klara/capabilities` 负责能力注册和暴露：

- fake Chapter 1 tools
- later chapter tools
- capability profiles
- visibility selection

后续层不能被 `core` import：

- `context`
- `services`
- `memory`
- `skills`
- `backend`
- `eval`
- `training`

如果一个后续能力需要接入 loop，它应该通过 app、hooks、capabilities、context
或 trace 接入。不要把 core 扩成 product pipeline。

## 3. Core Size Rule

Core 可以有多个小文件。问题不是文件数量，而是责任滑坡。

Chapter 1 core file whitelist:

```text
__init__.py
messages.py
tools.py
events.py
hooks.py
policies.py
tool_executor.py
loop.py
```

新增 core 文件前必须问三个问题：

1. 在 no-RAG、no-memory、no-backend 的 loop 里，它是否仍然成立？
2. 它是否能不依赖 app、services、storage 独立测试？
3. 它是否定义了后续 layer 需要依赖的 runtime contract？

只有三个答案都是 yes，才能进入 `core`。

## 4. Comment And Docstring Rules

Klara 采用“教学密度更高”的注释规范。

默认要求：

- 每个模块必须有 module docstring。
- 每个 class 必须有 class docstring。
- 每个 public function / method 必须有 docstring。
- 每个重要变量必须有注释或通过类型/命名/上下文自解释。
- 每个 `for` / `while` 循环必须有一行注释说明循环意图。
- 每个关键阶段必须有注释说明“为什么现在做这一步”。

### Module Docstring

模块顶部说明这个文件在架构中的位置。

Good:

```python
"""Core loop execution for Klara's minimal runtime."""
```

Bad:

```python
"""Loop code."""
```

### Class Docstring

每个 class 都要有大注释，说明它的职责、边界和不负责什么。

Good:

```python
class KlaraLoop:
    """Execute model turns, tool observations, stop policy, and trace events.

    The loop owns runtime execution only. It does not choose persona, load
    memory, select capability profiles, or talk to backend transports.
    """
```

Class docstring 应该回答：

- 这个类负责什么？
- 它不负责什么？
- 它属于哪个 layer？
- 后续章节会通过什么边界接入它？

### Function And Method Docstring

每个 public `def` 都要有 docstring。

推荐格式：

```python
def run(self, user_input: str, *, run_id: str | None = None) -> KlaraRunResult:
    """Run one Klara loop until a final answer, max turns, or failure.

    Args:
        user_input: The new user message that starts this run.
        run_id: Optional stable id for deterministic traces and tests.

    Returns:
        A run result containing final answer, messages, stop reason, and hook
        failures.
    """
```

规则：

- public function/method 使用 `Args` 和 `Returns`。
- 如果可能抛出业务异常，增加 `Raises`。
- private helper 可以用一句短 docstring，除非逻辑非常明显。
- 不要把实现步骤全塞进 docstring；步骤说明放在函数体内的关键注释。

### Variable Comments

变量注释的目标是解释“这个变量在算法里的角色”，不是重复变量名。

必须注释的变量：

- 状态变量：当前 run、当前 turn、当前 message window。
- 策略变量：max turns、budget、threshold、stop reason。
- 边界变量：public payload、private prompt、tool observation。
- 容易被误改的变量：trace path、storage key、visible tools。

可以不注释的变量：

- 生命周期很短的临时变量。
- 名字和类型已经完全自解释的变量。
- 测试里明显的 fixture 局部变量。

Good:

```python
# Active run id is the trace join key across all lifecycle events.
active_run_id = run_id or str(uuid4())
```

Bad:

```python
# Set active_run_id.
active_run_id = run_id or str(uuid4())
```

### Loop Comments

每个 `for` / `while` 前都要有注释。

Good:

```python
# Iterate through bounded turns so a model cannot request tools forever.
for turn_index in range(1, self.policy.max_turns + 1):
    ...
```

Good:

```python
# Execute every tool call before preparing the next model-visible turn.
for call in response.tool_calls:
    ...
```

Bad:

```python
# Loop over tool calls.
for call in response.tool_calls:
    ...
```

### Step Comments

关键步骤必须有注释，尤其是 loop、context、memory、RAG、eval 这些章节。

Step comment 应该解释阶段目的：

```python
# Store the assistant request before tool execution so trace replay matches the
# model-visible transcript.
messages.append(assistant_message)
```

不要写机械注释：

```python
# Append assistant message.
messages.append(assistant_message)
```

### Comment Language

源码注释默认使用英文。

原因：

- Python 生态和错误信息主要是英文。
- 类名、函数名、类型名都是英文。
- 英文注释更容易和未来外部工具、lint、文档生成结合。

教程 README 和架构解释可以使用中文。

## 5. Code Shape

Chapter code should be explicit before clever.

Prefer:

- dataclasses for data contracts
- Protocols for injected dependencies
- explicit return objects
- typed public payloads
- small files with clear boundaries
- deterministic fake providers in tests

Avoid:

- hidden globals
- implicit singleton state
- broad `dict[str, Any]` at public boundaries when a dataclass is clearer
- untyped helper chains
- stringly-typed control flow without tests
- dependencies that are not required by the chapter

## 6. Import Rules

Imports should show architecture direction.

Allowed direction:

```text
app -> core
app -> capabilities
capabilities -> core
tests -> any layer under test
```

Forbidden direction:

```text
core -> app
core -> capabilities
core -> services
core -> memory
core -> skills
core -> backend
core -> eval
core -> training
```

Import rules must be protected by architecture tests when the boundary matters.

## 7. Tests

Every chapter should include:

- behavior tests for the new capability
- boundary tests for new architecture rules
- fake providers instead of real network calls
- deterministic trace or event assertions when observability changes
- failure-mode tests for loops, tools, hooks, and policies

Tests should protect teaching boundaries, not only output strings.

## 8. Minimal File Template

New Klara source files should follow this shape:

```python
"""One-sentence layer and responsibility summary."""

from __future__ import annotations


class ExampleBoundary:
    """Explain responsibility, layer boundary, and non-responsibilities."""

    def run(self, value: str) -> str:
        """Explain what this method receives and returns.

        Args:
            value: Input value visible to this boundary.

        Returns:
            The transformed value.
        """

        # Preserve the original input so trace/debug output can explain changes.
        original_value = value

        # Apply the chapter's only transformation step.
        result = original_value.strip()

        return result
```

This template is intentionally more verbose than production code. Klara teaches
architecture, so the code should carry the teaching trail without becoming
noisy or misleading.
