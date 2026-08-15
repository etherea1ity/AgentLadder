# AgentLadder 完成账本

语言：中文 | [English](./completion-ledger.en.md)

- 当前阶段: `agent-product-freeze`
- 模式: `full-end-to-end`
- 更新时间: `2026-08-15T04:23:30.103864+00:00`

## 目标状态

| 目标 | 状态 | 分支 |
| --- | --- | --- |
| `phase-0a-baseline` | `passed` | `codex/agent-product-baseline` |
| `phase-0b-agent-eval-contract` | `passed` | `codex/agent-eval-contract` |
| `ch04-harness-config` | `passed` | `codex/ch04-harness-config` |
| `ch05-todo-planning` | `passed` | `codex/ch05-todo-planning` |
| `ch06-07-context` | `passed` | `codex/ch06-07-context` |
| `ch08-provider-recovery` | `passed` | `codex/ch08-provider-recovery` |
| `ch09-skills-runtime` | `passed` | `codex/ch09-skills-runtime` |
| `ch10-memory` | `passed` | `codex/ch10-memory` |
| `ch11-formal-rag` | `deferred_by_scope` | `none` |
| `ch12-13-evidence-runtime` | `passed` | `codex/ch12-13-evidence-runtime` |
| `permission-engine` | `passed` | `codex/permission-engine` |
| `ch14-durable-tasks` | `passed` | `codex/ch14-durable-tasks` |
| `ch15-background-scheduler` | `passed` | `codex/ch15-background-scheduler` |
| `ch17-mcp` | `passed` | `codex/ch17-mcp` |
| `ch16-subagents-team-worktree` | `passed` | `codex/ch16-subagents-team-worktree` |
| `ch18-production-runtime` | `passed` | `codex/ch18-production-runtime` |
| `agent-product-polish` | `passed` | `codex/agent-product-polish` |
| `agent-runtime-integration` | `passed` | `codex/agent-runtime-integration` |
| `agent-product-benchmarks` | `passed` | `codex/agent-product-external-benchmarks` |
| `agent-product-freeze-readiness` | `passed` | `codex/agent-product-freeze-readiness` |
| `agent-product-freeze` | `blocked_external` | `codex/agent-product-freeze` |
| `model-kv-cache` | `pending` | `codex/model-kv-cache` |
| `real-trajectory-collector` | `pending` | `codex/real-trajectory-collector` |
| `real-trajectory-dataset` | `pending` | `codex/real-trajectory-dataset` |
| `hku-upload-ready` | `pending` | `codex/local-pre-hku-freeze` |
| `hku-policy-model-baselines` | `pending` | `codex/hku-policy-model-baselines` |
| `hku-policy-distillation` | `pending` | `codex/hku-policy-distillation` |
| `hku-precision-serving` | `pending` | `codex/hku-precision-serving` |
| `learned-policy-shadow` | `pending` | `codex/learned-policy-shadow` |
| `learned-policy-canary` | `pending` | `codex/learned-policy-canary` |
| `learned-policy-integration` | `pending` | `codex/learned-policy-integration` |
| `model-integration-freeze` | `pending` | `codex/model-integration-freeze` |

## 剩余失败

### `agent-product-benchmarks`

- The frozen Qwen judge credential returned HTTP 401; a distinct independent judge has not scored the 41 observations.
- No independent blind-human labels exist for the frozen comparison queue.
- docker/mem0/Dockerfile references deleted branch feat/v3-pipeline
- The pinned MEM1 7B rollout requires a comparable GPU evaluation run.
- No licensed, hashed BEAM snapshot is available for a comparable scale run.
- A frozen publicly permitted GAIA subset has not yet been executed through the current runtime.

### `agent-product-freeze`

- The frozen Qwen judge credential returned HTTP 401; a distinct independent judge has not scored the 41 observations.
- No independent blind-human labels exist for the frozen comparison queue.
- docker/mem0/Dockerfile references deleted branch feat/v3-pipeline
