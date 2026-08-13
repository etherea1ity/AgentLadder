# AgentLadder Completion Ledger

Language: [Chinese](./completion-ledger.md) | English

Mode: `full-end-to-end`

| Objective | Branch | Status |
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

`deferred_by_scope` is not a pass, and `pending` is not partial completion. No new HKU training may begin before Agent Product Freeze passes. The whole project may only be called complete after the Agent, model/data, and learned-policy integration freezes all pass.

## Current Evidence

- Phase 0A: commit `3266fea1f7cd4f340ae34dceeb74f86c455af009` freezes the all-branch and product baseline.
- Phase 0B: commit `10a9bf0afc0c9ea24267cb4a2b5b31e8fa791a0b` passes the [behavior evaluation contract](./agent-eval-contract.en.md); Python reports `244 passed, 1 skipped`, frontend reports `45 passed`, and the production build passes.
- Visual acceptance: `1280x720` and `390x844` have no horizontal overflow, while the aggregate API/UI exposes neither hidden cases nor blind-review identities; see [UI E2E JSON](./agent-eval-contract-ui-e2e.json).
- Interpretation boundary: the Phase 0B `contract_control_probe` proves only that the evaluation contract and plumbing work. It does not mean the current Agent is complete or GPT-equivalent.
- Chapter 4: commit `3168b61` passes `11/11` machine checks, Python `254 passed, 1 skipped`, frontend `45 passed`, the production build, and desktop/narrow model-capability picker acceptance; see the [Chapter 4 report](./ch04-harness-config.en.md).
- Chapter 5: commit `5b200f22` passes `14/14` machine checks, Python `267 passed, 1 skipped`, frontend `47 passed`, and the production build. A real product probe records the plan in JSONL trace and SSE, while desktop and narrow layouts have no horizontal overflow; see the [Chapter 5 report](./ch05-todo-planning.en.md).

- Chapters 6–7: commit `ca8a2bd` passes `15/15` machine checks, Python `279 passed, 1 skipped`, frontend `49 passed`, and the production build. A real product probe compresses 10 long history messages into 4 model-visible messages and summarizes 8 old messages; summary content never enters public trace/SSE, and desktop plus 390px layouts have no horizontal overflow. See the [Chapters 6–7 report](./ch06-07-context.en.md).

- Chapter 8: commit `2f5af037c3ac55f7c6fa29a9a1c2439ccd5935d3` passes `18/18` machine checks, Python `288 passed, 1 skipped`, frontend `52 passed`, the production build, and the behavior contract. Fault injection covers transient retry, context-length compaction retry, compatible fallback, tool-failure observations, and the safe recovery UI. Desktop and `390x844` layouts have no horizontal overflow, and the provider response body is not exposed. See the [Chapter 8 report](./ch08-provider-recovery.en.md).

- Chapter 9: commit `ecf9e93e2fbcefbb0eae84cc90212419ebf443f0` passes `14/14` machine checks, Python `295 passed, 1 skipped`, frontend `54 passed`, the production build, and 24 behavior observations. The three-scope catalog has deterministic precedence, metadata-first discovery, and explicit on-demand loading; tool or permission dependency failures close safely, while public trace, SSE, and UI expose no Skill body. Desktop and `390x844` layouts have no horizontal overflow or console errors. See the [Chapter 9 report](./ch09-skills-runtime.en.md).

- Chapter 10: commit `ca5e20a4b19ce9036878b84205a10fa670972f33` passes `16/16` machine checks, Python `305 passed, 1 skipped`, frontend `56 passed`, the production build, and 24 behavior-control observations. Memory now provides tenant/user/agent/session isolation, explicit writes, candidate review, versioned temporal validity, forgetting, and verified hard deletion. On the same local retrieval corpus, hybrid reaches `6/6` top-1 and `3/3` critical top-1. Mem0/MEM1 and public benchmarks remain explicitly `not_executed`; see the [Chapter 10 report](./ch10-memory.en.md).

- Chapters 12–13: commit `8ebc0351ae5d4890f5e985c2e24573fdcabe23b4` passes `15/15` machine checks, Python `314 passed, 1 skipped`, frontend `58 passed`, the production build, and 24 behavior-control observations. The real `KlaraLoop` now requires `web_fetch -> evidence_submit -> verifier`, rejecting snippets-as-sources, dangling/duplicate/stale/irrelevant/contradicted evidence, and forged witnesses. Critical deterministic gold citation precision/recall, contradiction recall, and abstention accuracy are all `1.0`. This is not an open-domain perfection claim; see the [Chapters 12–13 report](./ch12-13-evidence-runtime.en.md).

- Permission Engine: branch `codex/permission-engine` passes `25/25` deterministic checks with a `1.0` critical isolation/bypass rate and `0` raw tool-argument leaks. Python reports `325 passed, 1 skipped`, frontend reports `60 passed`, and the production build passes. A real browser journey completed pending → allow once → revoke with no desktop horizontal overflow; narrow layout is backed by component and responsive-CSS gates. See the [Permission Engine report](./permission-engine.en.md).

The sequential gate is now at `ch14-durable-tasks`; Chapter 11 remains deferred by the agreed scope and is not counted as passed.
