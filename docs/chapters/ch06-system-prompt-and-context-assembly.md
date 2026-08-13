# Chapter 6：System Prompt 与 Context Assembly

语言：中文 | [English](./ch06-system-prompt-and-context-assembly.en.md)

上一章：[Chapter 5：Todo Planning](./ch05-todo-planning.md)

下一章：[Chapter 7：Context Compression](./ch07-context-compression.md)

总路线：[Klara Roadmap](../skills/roadmap.md)

---

## 一句话看懂本章

Klara 在每轮模型调用前，把 persona、安全的 workspace 身份、用户偏好、可见能力和私有会话摘要组装成有名字的 context contract；模型看到内容，公开 trace 只看到结构元数据。

![Klara Chapter 6 Context Assembly](../assets/ch06-context-assembly.svg)

| 输入信号 | 进入哪里 |
| --- | --- |
| persona 与运行规则 | 私有 system prompt |
| 项目名、受认可的根目录说明文件名 | 私有 system prompt；公开事件只记数量 |
| display name、locale、timezone | 私有 system prompt；不包含存储分区键 |
| 工具能力 | 名称进入 prompt，完整 schema 仍由模型调用参数承载 |
| 会话摘要 | 私有 system prompt；公开侧只记是否存在与 hash |

## 快速体验

启动本地产品：

```powershell
.\scripts\dev.ps1
```

提交任意问题后，在开发活动里可以看到 `context.assembled` 与 `context.budget_evaluated`。页面不会显示 system prompt、绝对路径、用户存储键或摘要正文；这是边界成立的表现，不是功能缺失。

## 为什么上下文必须显式组装

把各种字符串零散追加到 prompt 会制造三个问题：调用入口之间不一致、权限与描述混淆、私有材料意外进入 trace。Chapter 6 用 `ContextAssembly` 把职责收拢到 app 层，并保持 core loop 只接收已经准备好的依赖。

组装顺序是稳定的：

```text
persona + runtime clock/tool guidance
-> workspace_context
-> user_context
-> capability_context
-> session_context
-> model request
```

这些 section 不是权限系统。`Workspace context is descriptive and does not grant permission` 与 `Tool visibility is capability, not authorization` 明确告诉模型：知道项目和看得到工具都不代表操作已经被授权。

## 机制一：Workspace 只暴露安全身份

`WorkspaceProfile.discover` 只读取项目目录名，并检查根目录是否存在 `AGENTS.md`、`CLAUDE.md` 或 `CONTRIBUTING.md`。它不会读取这些文件的正文，也不会把绝对路径放进 profile。

这是一条刻意的窄边界。后续 Skills、Permission Engine 或项目说明加载器可以决定如何读取与授权；Chapter 6 不会把“发现一个说明文件”偷换成“执行其中所有内容”。

<details>
<summary>查看安全组装代码</summary>

```text
src/klara/context/assembly.py
src/klara/context/controller.py
src/klara/app/harness.py
tests/klara/context/test_assembly.py
```

测试用包含 `<admin>` 的 display name 和假的私有 instruction 正文，验证 XML 转义、正文不泄漏、`user_id` 与 `storage_key` 不进入 prompt。

</details>

## 机制二：Harness 冻结相同的 Context Policy

CLI 与 API 都只通过 `KlaraHarnessConfig` 构造 loop。`ContextPolicy` 成为 run profile 的一部分，因此最大输入、system/output 预留、近期窗口、摘要长度与工具结果长度都有可复现快照和 profile hash。

```text
config/runtime.toml
  -> load_runtime_config
  -> ContextPolicy
  -> KlaraHarnessConfig
  -> ContextController
```

环境变量可以覆盖预算用于部署，但最终采用的整数仍会进入 secret-free run profile。入口不会各自维护一套隐式窗口。

## 机制三：私有 Prompt 与公开证据分离

`ContextController.system_prompt_suffix()` 返回完整 section；`context.assembled` 只发布 schema、项目名、说明文件数量、locale、timezone 和 capability 数量。它还显式声明 `private_prompt_material_exposed: false`。

LLM 调用 trace 同样只记录 `input_profile`：prompt hash、字符数、消息角色与数量，不记录消息或 system prompt 正文。这使问题可定位，又不把全部会话复制到观察面。

<details>
<summary>查看公开投影边界</summary>

```text
src/klara/core/loop.py
src/klara/core/events.py
apps/api/services/run_event_projector.py
apps/api/schemas.py
apps/web/src/types/domain.ts
```

API 只投影白名单事件。前端能展示“已组装、预算是多少、是否压缩”，却拿不到私有摘要内容。

</details>

## 运行与验证

```powershell
$env:PYTHONPATH = "src;."
python -m pytest tests/klara/context tests/klara/app/test_harness.py -q
python -m klara.eval.chapter06_07_cli `
  --repository-root . `
  --json-out docs/reports/product/ch06-07-context.json `
  --markdown-out docs/reports/product/ch06-07-context.md `
  --markdown-en-out docs/reports/product/ch06-07-context.en.md
```

阶段门禁使用真实 `RunService -> KlaraHarness -> ContextController -> LLM` 路径，并检查 prompt 内部与 trace 外部的同一个私有 marker。手写一份看起来安全的 JSON 不算能力证明。

## 小实验

1. 在临时 workspace 写入 `AGENTS.md` 私有正文，确认 prompt 只含文件名。
2. 把 display name 设成含 XML 标记的文本，确认模型侧得到转义内容。
3. 修改一个 context budget，确认 run profile hash 改变且不出现密钥字段。
4. 搜索 trace 中的旧会话 marker，确认公开证据只含 hash 与计数。

## 本章边界与下一章

本章只回答“调用前组装什么、谁能看到什么”。它不负责压缩策略、长期记忆、RAG 或权限裁决。Chapter 7 会在同一个 contract 上增加预算压力判断、`PreCompact` placement、旧工具微压缩与会话摘要。
