# AgentLadder Completion Ledger

Language: [Chinese](./completion-ledger.md) | English

Mode: `local-pre-hku`

| Objective | Branch | Status |
| --- | --- | --- |
| phase-0a-baseline | `codex/agent-product-baseline` | passed |
| phase-0b-agent-eval-contract | `codex/agent-eval-contract` | passed |
| ch04-harness-config | `codex/ch04-harness-config` | passed |
| ch05-todo-planning | `codex/ch05-todo-planning` | passed |
| ch06-07-context | `codex/ch06-07-context` | passed |
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

`deferred_by_scope` is not a pass. `pending` is not partial completion. The whole repository may only be called `local pre-HKU freeze passed` after every locally mandatory objective is green and synchronized to GitHub.

## Current Evidence

- Phase 0A: commit `3266fea1f7cd4f340ae34dceeb74f86c455af009` freezes the all-branch and product baseline.
- Phase 0B: commit `10a9bf0afc0c9ea24267cb4a2b5b31e8fa791a0b` passes the [behavior evaluation contract](./agent-eval-contract.en.md); Python reports `244 passed, 1 skipped`, frontend reports `45 passed`, and the production build passes.
- Visual acceptance: `1280x720` and `390x844` have no horizontal overflow, while the aggregate API/UI exposes neither hidden cases nor blind-review identities; see [UI E2E JSON](./agent-eval-contract-ui-e2e.json).
- Interpretation boundary: the Phase 0B `contract_control_probe` proves only that the evaluation contract and plumbing work. It does not mean the current Agent is complete or GPT-equivalent.
- Chapter 4: commit `3168b61` passes `11/11` machine checks, Python `254 passed, 1 skipped`, frontend `45 passed`, the production build, and desktop/narrow model-capability picker acceptance; see the [Chapter 4 report](./ch04-harness-config.en.md).
- Chapter 5: commit `5b200f22` passes `14/14` machine checks, Python `267 passed, 1 skipped`, frontend `47 passed`, and the production build. A real product probe records the plan in JSONL trace and SSE, while desktop and narrow layouts have no horizontal overflow; see the [Chapter 5 report](./ch05-todo-planning.en.md).

- Chapters 6–7: commit `ca8a2bd` passes `15/15` machine checks, Python `279 passed, 1 skipped`, frontend `49 passed`, and the production build. A real product probe compresses 10 long history messages into 4 model-visible messages and summarizes 8 old messages; summary content never enters public trace/SSE, and desktop plus 390px layouts have no horizontal overflow. See the [Chapters 6–7 report](./ch06-07-context.en.md).

The sequential gate is now at `ch08-provider-recovery`.
