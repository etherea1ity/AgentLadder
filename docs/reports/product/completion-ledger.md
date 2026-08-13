# AgentLadder 完成台账

语言：中文 | [English](./completion-ledger.en.md)

模式：`local-pre-hku`

| 目标 | 分支 | 状态 |
| --- | --- | --- |
| phase-0a-baseline | `codex/agent-product-baseline` | passed |
| phase-0b-agent-eval-contract | `codex/agent-eval-contract` | passed |
| ch04-harness-config | `codex/ch04-harness-config` | passed |
| ch05-todo-planning | `codex/ch05-todo-planning` | pending |
| ch06-07-context | `codex/ch06-07-context` | pending |
| ch08-provider-recovery | `codex/ch08-provider-recovery` | pending |
| ch09-skills-runtime | `codex/ch09-skills-runtime` | pending |
| ch10-memory | `codex/ch10-memory` | pending |
| ch11-formal-rag | `none` | deferred_by_scope |
| ch12-13-evidence-runtime | `codex/ch12-13-evidence-runtime` | pending |
| permission-engine | `codex/permission-engine` | pending |
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

`deferred_by_scope` 不是通过，`pending` 也不是部分完成。只有所有本地强制目标通过并同步到 GitHub 后，整个仓库才可以标记为 `local pre-HKU freeze passed`。

## 当前证据

- Phase 0A：提交 `3266fea1f7cd4f340ae34dceeb74f86c455af009`，冻结全分支与产品基线。
- Phase 0B：提交 `10a9bf0afc0c9ea24267cb4a2b5b31e8fa791a0b`，通过 [行为评测契约](./agent-eval-contract.md)；Python `244 passed, 1 skipped`，前端 `45 passed`，生产构建通过。
- 视觉验收：`1280x720` 与 `390x844` 无水平溢出，聚合 API/UI 不暴露隐藏用例和盲评身份；详见 [UI E2E JSON](./agent-eval-contract-ui-e2e.json)。
- 解释边界：Phase 0B 的 `contract_control_probe` 只证明评测合同与管线有效，不代表当前 Agent 已完成或达到 GPT 能力。
- Chapter 4：提交 `3168b61`，机器门禁 `11/11`，Python `254 passed, 1 skipped`，前端 `45 passed`，生产构建和桌面/窄屏模型能力选择器通过；详见 [Chapter 4 报告](./ch04-harness-config.md)。

当前顺序门禁已经进入 `ch05-todo-planning`。
