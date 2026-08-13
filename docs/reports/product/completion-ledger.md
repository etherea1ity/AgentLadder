# AgentLadder 完成台账

语言：中文 | [English](./completion-ledger.en.md)

模式：`full-end-to-end`

| 目标 | 分支 | 状态 |
| --- | --- | --- |
| phase-0a-baseline | `codex/agent-product-baseline` | passed |
| phase-0b-agent-eval-contract | `codex/agent-eval-contract` | passed |
| ch04-harness-config | `codex/ch04-harness-config` | passed |
| ch05-todo-planning | `codex/ch05-todo-planning` | passed |
| ch06-07-context | `codex/ch06-07-context` | passed |
| ch08-provider-recovery | `codex/ch08-provider-recovery` | passed |
| ch09-skills-runtime | `codex/ch09-skills-runtime` | passed |
| ch10-memory | `codex/ch10-memory` | passed |
| ch11-formal-rag | `none` | deferred_by_scope |
| ch12-13-evidence-runtime | `codex/ch12-13-evidence-runtime` | passed |
| permission-engine | `codex/permission-engine` | passed |
| ch14-durable-tasks | `codex/ch14-durable-tasks` | pending |
| ch15-background-scheduler | `codex/ch15-background-scheduler` | pending |
| ch17-mcp | `codex/ch17-mcp` | pending |
| ch16-subagents-team-worktree | `codex/ch16-subagents-team-worktree` | pending |
| ch18-production-runtime | `codex/ch18-production-runtime` | pending |
| agent-product-polish | `codex/agent-product-polish` | pending |
| agent-product-benchmarks | `codex/agent-product-benchmarks` | pending |
| agent-product-freeze | `codex/agent-product-freeze` | pending |
| model-kv-cache | `codex/model-kv-cache` | pending |
| real-trajectory-collector | `codex/real-trajectory-collector` | pending |
| real-trajectory-dataset | `codex/real-trajectory-dataset` | pending |
| hku-upload-ready | `codex/local-pre-hku-freeze` | pending |

`deferred_by_scope` 不是通过，`pending` 也不是部分完成。Agent Product Freeze 通过之前不得开始新的 HKU 训练；整个项目只有在 Agent、模型/数据与学习策略接入三次冻结全部通过后才可以标记为完成。

## 当前证据

- Phase 0A：提交 `3266fea1f7cd4f340ae34dceeb74f86c455af009`，冻结全分支与产品基线。
- Phase 0B：提交 `10a9bf0afc0c9ea24267cb4a2b5b31e8fa791a0b`，通过 [行为评测契约](./agent-eval-contract.md)；Python `244 passed, 1 skipped`，前端 `45 passed`，生产构建通过。
- 视觉验收：`1280x720` 与 `390x844` 无水平溢出，聚合 API/UI 不暴露隐藏用例和盲评身份；详见 [UI E2E JSON](./agent-eval-contract-ui-e2e.json)。
- 解释边界：Phase 0B 的 `contract_control_probe` 只证明评测合同与管线有效，不代表当前 Agent 已完成或达到 GPT 能力。
- Chapter 4：提交 `3168b61`，机器门禁 `11/11`，Python `254 passed, 1 skipped`，前端 `45 passed`，生产构建和桌面/窄屏模型能力选择器通过；详见 [Chapter 4 报告](./ch04-harness-config.md)。
- Chapter 5：提交 `5b200f22`，机器门禁 `14/14`，Python `267 passed, 1 skipped`，前端 `47 passed`，生产构建通过；真实产品探针证明 plan 进入 JSONL trace 与 SSE，桌面/窄屏均无水平溢出；详见 [Chapter 5 报告](./ch05-todo-planning.md)。

- Chapter 6–7：提交 `ca8a2bd`，机器门禁 `15/15`，Python `279 passed, 1 skipped`，前端 `49 passed`，生产构建通过；真实产品探针把 10 条长历史压缩为 4 条模型可见消息、汇总 8 条旧消息，摘要正文未进入公开 trace/SSE，桌面与 390px 布局均无水平溢出；详见 [Chapter 6–7 报告](./ch06-07-context.md)。

- Chapter 8：提交 `2f5af037c3ac55f7c6fa29a9a1c2439ccd5935d3`，机器门禁 `18/18`，Python `288 passed, 1 skipped`，前端 `52 passed`，生产构建与行为契约通过；故障注入覆盖瞬态重试、上下文超限压缩重试、兼容 fallback、工具失败观察与安全 UI。桌面和 `390x844` 均无水平溢出，未公开 provider response body；详见 [Chapter 8 报告](./ch08-provider-recovery.md)。

- Chapter 9：提交 `ecf9e93e2fbcefbb0eae84cc90212419ebf443f0`，机器门禁 `14/14`，Python `295 passed, 1 skipped`，前端 `54 passed`，生产构建与 24 条行为观察通过。三级 Skill 目录采用确定性覆盖、元数据优先和按需加载；权限/工具依赖失败时关闭，公开 trace、SSE 与 UI 均不暴露 Skill 正文。桌面与 `390x844` 无水平溢出、无控制台错误；详见 [Chapter 9 报告](./ch09-skills-runtime.md)。

- Chapter 10：提交 `ca5e20a4b19ce9036878b84205a10fa670972f33`，机器门禁 `16/16`，Python `305 passed, 1 skipped`，前端 `56 passed`，生产构建与 24 条行为控制观察通过。Memory 具备租户/用户/Agent/会话隔离、显式写入、候选审核、版本与时间有效性、遗忘和可验证硬删除；本地统一语料检索门中 hybrid 达到 `6/6` top-1、关键题 `3/3`。Mem0/MEM1 和公共 benchmark 尚未运行，报告明确标记为 `not_executed`；详见 [Chapter 10 报告](./ch10-memory.md)。

- Chapters 12–13：提交 `8ebc0351ae5d4890f5e985c2e24573fdcabe23b4`，机器门禁 `15/15`，Python `314 passed, 1 skipped`，前端 `58 passed`，生产构建与 24 条行为控制观察通过。真实 `KlaraLoop` 现要求 `web_fetch -> evidence_submit -> verifier`，拒绝 snippet 冒充来源、dangling/duplicate/stale/irrelevant/contradicted 证据和伪造 witness；关键确定性金标的 citation precision/recall、contradiction recall、abstention accuracy 均为 `1.0`。这不是开放域完美声明；详见 [Chapters 12–13 报告](./ch12-13-evidence-runtime.md)。

- Permission Engine：分支 `codex/permission-engine`，确定性门禁 `25/25`，关键隔离与绕过通过率 `1.0`，原始工具参数泄漏 `0`；Python `325 passed, 1 skipped`，前端 `60 passed`，生产构建通过。真实浏览器完成 pending → allow once → revoke，桌面无水平溢出；窄屏由组件与响应式 CSS 门禁验证。详见 [Permission Engine 报告](./permission-engine.md)。

当前顺序门禁已经进入 `ch14-durable-tasks`；Chapter 11 按既定范围延期，不计为通过。
