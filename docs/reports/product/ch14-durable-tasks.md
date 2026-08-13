# Chapter 14 Durable Task 门禁

语言：中文 | [English](./ch14-durable-tasks.en.md)

Status: **PASS**

- 评分器: `klara.chapter14-durable-tasks.v1`
- 检查: `21/21`
- 关键恢复/隔离/幂等通过率: `1.000`
- 公共面秘密泄漏: `0`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| api_exposes_full_lifecycle | PASS |
| artifact_public_uris_drop_queries | PASS |
| bilingual_tutorial_exists | PASS |
| cancellation_propagates_to_descendants | PASS |
| checkpoint_hash_and_sequence_persist | PASS |
| checkpoint_payload_not_public | PASS |
| completion_requires_declared_artifacts_and_evidence | PASS |
| dependency_waits_then_promotes | PASS |
| effect_receipt_prevents_duplicate_execution | PASS |
| exclusive_active_lease_and_forgery_blocked | PASS |
| expired_attempt_is_immutable_abandoned_history | PASS |
| lease_token_never_persisted_raw | PASS |
| pause_resume_block_fail_paths_are_valid | PASS |
| progress_is_persisted | PASS |
| restart_recovers_latest_checkpoint | PASS |
| retry_attempt_budget_is_enforced | PASS |
| run_service_uses_durable_task_lifecycle | PASS |
| running_child_attempt_closes_cancelled | PASS |
| stage_manifest_exists | PASS |
| tenant_owner_isolation_is_opaque | PASS |
| ui_projects_real_task_api_and_recovery_states | PASS |

## 问题—回答一致性探针

- 问题: The worker died after sending a notification. Can the recovered task safely continue?
- 参考回答: Yes, after the lease expires: mark the old attempt abandoned, restore the latest checkpoint, reuse the committed idempotency receipt instead of sending again, and only complete after required artifacts and evidence exist.
- 候选观察: Recovered checkpoint 1 in attempt 2; the notification receipt was already committed, so no duplicate effect was executed. Completion remained blocked until report and source evidence were recorded.
- P0 奇怪回答: `0`

## 限制

- The deterministic gate proves the frozen SQLite single-host state machine, not distributed consensus.
- Generic lease-expiry recovery is implemented; automatic recurring scheduling and restart scanning belong to Chapter 15.
- This contract-control probe is not independent model-judge or human parity evidence.
