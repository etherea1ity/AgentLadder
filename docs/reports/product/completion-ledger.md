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
| ch14-durable-tasks | `codex/ch14-durable-tasks` | passed |
| ch15-background-scheduler | `codex/ch15-background-scheduler` | passed |
| ch17-mcp | `codex/ch17-mcp` | passed |
| ch16-subagents-team-worktree | `codex/ch16-subagents-team-worktree` | passed |
| ch18-production-runtime | `codex/ch18-production-runtime` | passed |
| agent-product-polish | `codex/agent-product-polish` | passed |
| agent-runtime-integration | `codex/agent-runtime-integration` | passed |
| agent-product-benchmarks | `codex/agent-product-external-benchmarks` | passed |
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

- Chapter 14：提交 `38b46d94982b1847f50e553e0ff58bf87d4e6dc4`，确定性门禁 `21/21`，关键恢复/隔离/幂等通过率 `1.0`，公共秘密泄漏 `0`；Python `341 passed, 1 skipped`，前端 `62 passed`，生产构建和 24 条行为控制观察通过。真实浏览器完成 ready → detail → cancelled，桌面无水平溢出；窄屏由组件与响应式 CSS 门禁验证。详见 [Chapter 14 报告](./ch14-durable-tasks.md)。

- Chapter 15：提交 `77e6eb81f906588dacc646bb12835be70804f5d6`，确定性门禁 `19/19`，关键调度率 `1.0`，公共秘密泄漏 `0`；Python `355 passed, 1 skipped`，前端 `64 passed`，生产构建与 24 条行为控制观察通过。真实浏览器验证调度时间线、权限路径和桌面/移动布局；详见 [Chapter 15 报告](./ch15-background-scheduler.md)。

- Chapter 17：提交 `080b35b0952992cefc804e5b7ba027456da922dd`，确定性门禁 `19/19`，关键 MCP 率 `1.0`，公共秘密泄漏 `0`；Python `371 passed, 1 skipped`，前端 `66 passed`，生产构建与 24 条行为控制观察通过。真实浏览器完成配置 → 权限阻断 → allow once → stdio 协议协商，桌面与 `390x844` 均无水平溢出且控制台无错误或警告；详见 [Chapter 17 报告](./ch17-mcp.md)。

- Chapter 16：提交 `9643d5fd37851a1fd21b725f30a387626381c67e`，确定性门禁 `19/19`，关键委派/隔离率 `1.0`，公共秘密泄漏 `0`；Python `380 passed, 1 skipped`，前端 `68 passed`，生产构建与 24 条行为控制观察通过。真实浏览器完成创建阻断 → 精确审批 → allow once → 队友出现，桌面与 `390x844` 无水平溢出且控制台无错误/警告；真实 Git 测试覆盖隔离 Worktree 创建和安全移除。详见 [Chapter 16 报告](./ch16-subagents-team-worktree.md)。

- Chapter 18：确定性门禁 `25/25`，关键合同通过率 `1.0`，公共秘密泄漏与 P0 奇怪回答均为 `0`；Python `403 passed, 2 skipped`（其中 PostgreSQL 测试在常规无 DSN 回归中跳过，并已单独对真实 PostgreSQL 16 通过），前端 `68 passed`，生产构建与冻结回归 control 通过。除签名 bearer/RBAC、tenant+owner 隔离、幂等 lease queue/Outbox、脱敏 trajectory 与 CLI 外，还补齐 SQLite backup/restore/integrity/retention、OIDC RS256/JWKS/撤销 adapter、通用 Agent 状态持久化，并通过一次性 PostgreSQL 16 的真实 migration/isolation/JSONB/queue/lease/Outbox 集成测试；外部 OIDC provider smoke 明确为 `not_executed`。详见 [Chapter 18 报告](./ch18-production-runtime.md)。

- Agent Product Polish：`15/15` 产品检查通过，定向 Python `64 passed`，前端 `71 passed`，生产构建通过；真实浏览器验证 Overview、Trace、评测历史与移动导航。两项 P0 反例——取消后尾事件/隐式复活和 DeepSeek DSML 答案泄漏——均已修复并加入回归；旧 raw provider reasoning 与底层 JSONL 不再跨越 API 公共边界。详见 [Product Polish 报告](./agent-product-polish.md)。

- 主 Agent 运行时集成：API 所用 `KlaraHarness` 现注入与 UI 相同的任务、调度、团队与 Worktree 持久服务，共暴露 `14` 个真实模型工具；写操作仍由精确权限门禁控制。确定性门禁 `14/14`，DeepSeek V4 Flash 冻结烟测 `3/3`、检查 `14/14`、未授权写入 `0`、P0 奇怪回答 `0`；全量 Python `424 passed, 2 skipped`，定向 `40 passed`，前端 `71 passed`，生产构建通过。模型观察与公共 Trace 均采用最小披露；详见 [运行时集成报告](./agent-runtime-integration.md)。

- Agent Product Benchmarks 本地准备：KlaraBench v2 的 `41/41` 条脚本参考观察均通过真实 Harness，修复了本地状态请求被错误导向 Web Research 的问题，并固定 LoCoMo、LongMemEval、MemoryAgentBench、AgentBench、tau2、Mem0、MEM1、BEAM 的官方来源契约。LoCoMo 检索 Recall@5 为 `0.630588`、Hit@5 为 `0.68`、MRR 为 `0.439`，不冒充回答正确率。真实候选运行器严格执行零预算边界，脚本校准不冒充真实参考成绩，并提供与候选报告哈希绑定、要求完整覆盖的独立参考/裁判/盲人评标签合并器。该本地准备点全量 Python `443 passed, 2 skipped`，前端 `71` 项测试、生产构建和 diff 检查均通过；当时尚未执行的外部实测由下一条更新。详见 [基准报告](./agent-product-benchmarks.md)。

- Agent Product Benchmarks 外部实测：固定官方版本完成 τ2 mock-domain `10` 题、AgentBench DBBench 固定 `5` 题与计数题 `3/3` 重复稳定性，以及 LoCoMo 同回答模型 `6` 系统、`600` 问答对。τ2 与 AgentBench 的官方成功率均为 `0.8`，候选侧可控动作指标均为 `1.0`；两个官方零分案例保留原分，并单独记录经复现的评测器/标签缺陷。LoCoMo full-context F1 为 `0.543081`，hybrid F1 为 `0.461914`、Recall@20 为 `0.73402`，总 Token 相对 full-context 减少 `95.6272%`。全量 Python `478 passed, 2 skipped`、前端 `71 passed`、生产构建通过，P0 奇怪回答为 `0`。这不代表 GPT 等价；详见 [外部实测报告](./agent-product-external-benchmarks.md)。

当前顺序门禁已经进入 `agent-product-freeze`；Chapter 11 按既定范围延期，不计为通过。两套 Qwen 凭据均返回 HTTP 401，独立盲人评审与 Mem0/MEM1/BEAM 正式同条件分数仍缺失，因此 Agent Product Freeze 尚未通过，模型训练保持禁用。
