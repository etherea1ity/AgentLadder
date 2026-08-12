# Agent 产品基线

语言：中文 | [English](./agent-product-baseline.en.md)

状态：**通过**

- 分支：`codex/agent-product-baseline`
- 父提交：`b440df32c71df56c892b4657c392e37f9ea53e9a`
- 源码包 SHA-256：`94bc0bc8df0237ad13e496d0e4a93b854c5f63b4cce80aa79f2c9dc0f9d11898`
- 已审计 refs：`27`
- 不同文档 blobs：`77`
- 安全模式：local pre-HKU；不连接 VPN/SSH，不传输，不运行 Slurm，不做本地重训练

## 回归基线

| 范围 | 结果 |
| --- | --- |
| Python | 228 passed, 1 skipped |
| 前端 | 42 passed |
| 生产构建 | PASS |
| 被跟踪的疑似秘密文件 | 0 |

## 能力真值

| 能力 | 状态 | 证据 |
| --- | --- | --- |
| ch01-03 | passed | historical chapter branches and 228-test baseline |
| algorithm-suite | passed | b440df3 freeze; cloud reports retained |
| ch04-harness-config | partial | KlaraHarness exists; immutable run profile/capability negotiation absent |
| ch05-todo-planning | missing | no plan state machine, persistence, events, API, or Plan UI |
| ch06-07-context | partial | timestamps/history and web compaction exist; full budget/provenance compaction absent |
| ch08-provider-recovery | partial | provider routing exists; bounded retry/idempotency/circuit breaker absent |
| ch09-skills-runtime | missing | no runtime catalog, precedence, progressive loading, API, or UI |
| ch10-memory | missing | no durable typed memory service, deletion guarantee, benchmark, API, or UI |
| ch11-formal-rag | deferred_by_scope | explicit user-approved omission |
| ch12-13-evidence-runtime | partial | contracts/evaluator exist; final-answer/API/UI integration incomplete |
| permission-engine | missing | PreToolUse placement is not a scoped permission engine |
| ch14-durable-tasks | missing | no leases/checkpoints/dependencies/restart recovery/API/UI |
| ch15-scheduler | missing | no durable schedules, DST/misfire/overlap, API, or UI |
| ch17-mcp | missing | no MCP lifecycle, transport, permission routing, API, or UI |
| ch16-teams-worktrees | missing | no delegation runtime, team state, worktree lifecycle, API, or UI |
| ch18-production-runtime | missing | local JSON store only; no migrations/queue/OIDC/RBAC/tenant proof |
| product-ui-polish | partial | chat/thinking/debug exist; product control surfaces absent |
| agent-benchmarks | missing | algorithm fixture evaluator is not KlaraBehaviorCase/public agent benchmark harness |
| model-kv-cache | missing | training attention has no typed prefill/decode cache |
| real-trajectory-data | partial | fixture exporter exists; real authorized dataset freeze absent |
| hku-upload-package | partial | algorithm scripts exist; full product/model upload inventory and preflight absent |

## 分支文档矩阵

| Ref | 角色 | Ahead/behind | 文档 | 决策 | 独特教学价值 |
| --- | --- | ---: | ---: | --- | --- |
| `chapter-2-tool-calling` | foundation_chapter | +0/-72 | 12 | preserve Chapter 2 tool boundary | what-stays-the-same tool boundary and real incident walkthrough |
| `codex/agent-product-baseline` | product_stage | +0/-0 | 32 | current baseline work branch | no additional unique lesson selected |
| `codex/algorithm-suite-freeze` | algorithm_freeze | +0/-0 | 32 | authoritative product parent and lab evidence | causal Advanced Lab contract and cloud-verified algorithm lineage |
| `codex/ch03-algorithm-roadmap` | algorithm_plan | +0/-6 | 18 | preserve planning decision record | no additional unique lesson selected |
| `codex/lab-a-evidence-eval` | algorithm_stage | +0/-5 | 19 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `codex/lab-b-tiny-pretrain` | algorithm_stage | +0/-4 | 21 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `codex/lab-c-trajectory-distillation` | algorithm_stage | +0/-3 | 22 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `codex/lab-d-tiny-moe` | algorithm_stage | +0/-2 | 23 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `codex/lab-e-fp16-fp4` | algorithm_stage | +0/-1 | 24 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `codex/lab-e-tiny-sparse-moe` | algorithm_stage | +0/-2 | 23 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `codex/lab-h-fp16-fp4` | algorithm_stage | +0/-1 | 24 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `main` | foundation_chapter | +0/-90 | 9 | preserve Chapter 1 teaching checkpoint | mechanism-first minimal loop and bilingual root/chapter mirror |
| `origin/chapter-1-minimal-loop` | foundation_chapter | +0/-90 | 9 | preserve Chapter 1 teaching checkpoint | mechanism-first minimal loop and bilingual root/chapter mirror |
| `origin/chapter-2-tool-calling` | foundation_chapter | +0/-72 | 12 | preserve Chapter 2 tool boundary | what-stays-the-same tool boundary and real incident walkthrough |
| `origin/chapter-3-hooks-and-trace` | foundation_chapter | +0/-7 | 17 | preserve Chapter 3 trace/activity boundary | public activity, provider reasoning, trace, and debug separation |
| `origin/codex/algorithm-suite-freeze` | algorithm_freeze | +0/-0 | 32 | authoritative product parent and lab evidence | causal Advanced Lab contract and cloud-verified algorithm lineage |
| `origin/codex/ch03-algorithm-roadmap` | algorithm_plan | +0/-6 | 18 | preserve planning decision record | no additional unique lesson selected |
| `origin/codex/lab-a-evidence-eval` | algorithm_stage | +0/-5 | 19 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `origin/codex/lab-b-tiny-pretrain` | algorithm_stage | +0/-4 | 21 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `origin/codex/lab-c-trajectory-distillation` | algorithm_stage | +0/-3 | 22 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `origin/codex/lab-d-tiny-moe` | algorithm_stage | +0/-2 | 23 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `origin/codex/lab-e-fp16-fp4` | algorithm_stage | +0/-1 | 24 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `origin/codex/lab-e-tiny-sparse-moe` | algorithm_stage | +0/-2 | 23 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `origin/codex/lab-h-fp16-fp4` | algorithm_stage | +0/-1 | 24 | preserve verified stacked experiment | one-gate experiment branch with machine and Markdown reports |
| `origin/main` | foundation_chapter | +0/-67 | 12 | preserve Chapter 2 tool boundary | what-stays-the-same tool boundary and real incident walkthrough |
| `origin/rag` | legacy_design_source | +21/-112 | 19 | port evidence contracts; never merge package tree | EvidencePack, SourceCard, Citation, DecisionRecord, insufficient evidence |
| `v0.3-agentic-rag` | legacy_design_source | +19/-112 | 6 | port evidence contracts; never merge package tree | EvidencePack, SourceCard, Citation, DecisionRecord, insufficient evidence |

## 决策

以 `b440df3` 的 `codex/algorithm-suite-freeze` 作为权威父提交：它同时包含最新 Chapter 3 祖先和已验证算法 overlay。Chapter 1–3 历史 refs 保持为不可改写的教学检查点；旧 RAG 分支只作为设计来源。

下一质量门是 `codex/agent-eval-contract`。在共享行为 schema、确定性评分器、冻结数据切分、同源报告和文档验证器通过前，Chapter 4 不得声称完成。
