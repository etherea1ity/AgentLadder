# Chapter 14 Durable Task Gate

Language: [Chinese](./ch14-durable-tasks.md) | English

Status: **PASS**

- Scorer: `klara.chapter14-durable-tasks.v1`
- Checks: `21/21`
- Critical recovery/isolation/idempotency rate: `1.000`
- Public secret leaks: `0`

## Acceptance Checks

| Check | Result |
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

## Question/Answer Consistency Probe

- Question: The worker died after sending a notification. Can the recovered task safely continue?
- Reference: Yes, after the lease expires: mark the old attempt abandoned, restore the latest checkpoint, reuse the committed idempotency receipt instead of sending again, and only complete after required artifacts and evidence exist.
- Candidate observation: Recovered checkpoint 1 in attempt 2; the notification receipt was already committed, so no duplicate effect was executed. Completion remained blocked until report and source evidence were recorded.
- P0 strange responses: `0`

## Limitations

- The deterministic gate proves the frozen SQLite single-host state machine, not distributed consensus.
- Generic lease-expiry recovery is implemented; automatic recurring scheduling and restart scanning belong to Chapter 15.
- This contract-control probe is not independent model-judge or human parity evidence.
