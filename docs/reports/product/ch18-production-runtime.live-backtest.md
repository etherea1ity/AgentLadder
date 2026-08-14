# Chapter 18 生产运行时门禁

语言：中文 | [English](./ch18-production-runtime.live-backtest.en.md)

Status: **PASS**

- 评分器: `klara.chapter18-production-runtime.v1`
- 检查: `25/25`
- 关键合同通过率: `1.000`
- 公共面秘密泄漏: `0`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| bilingual_tutorial_exists | PASS |
| forged_job_lease_is_rejected | PASS |
| forward_only_restore_and_retention_policy_exist | PASS |
| generic_state_covers_all_agent_domains_with_owner_scope | PASS |
| idempotency_reuses_exact_payload_only | PASS |
| job_api_never_projects_payload_or_result | PASS |
| oidc_discovery_jwks_rs256_and_revocation_exist | PASS |
| postgres_adapter_matches_service_surface_and_skip_locked | PASS |
| production_api_exposes_auth_state_queue_stream_cancel_outbox_export_metrics | PASS |
| question_answer_consistency_and_no_strange_output | PASS |
| queue_executes_one_bounded_payload | PASS |
| raw_bearer_and_lease_are_not_persisted | PASS |
| regression_cli_contract_is_strict_and_passes_control | PASS |
| roles_separate_owner_and_worker_authority | PASS |
| session_and_job_rows_are_owner_isolated | PASS |
| signed_bearer_tampering_is_rejected | PASS |
| sqlite_integrity_and_verified_backup_pass | PASS |
| terminal_job_and_outbox_commit_together | PASS |
| trajectory_drops_prompts_arguments_results_and_reasoning | PASS |
| trajectory_export_requires_owner_visible_job | PASS |
| trajectory_is_versioned_hash_linked_and_loadable | PASS |
| trajectory_privacy_scanner_has_zero_findings | PASS |
| versioned_migrations_apply_and_verify | PASS |
| worker_has_cooperative_cancel_and_heartbeat | PASS |
| worker_heartbeat_and_public_events_exist | PASS |

## 问题—回答一致性探针

- 问题: What is 5 + 7?
- 参考答案: 12
- 候选答案: 12

## 限制

- This gate proves SQLite operations plus one disposable PostgreSQL 16 integration run; multi-region consensus and managed identity-provider deployment remain environment-specific operations.
- No owner-authorized external OIDC tenant was configured, so the live provider smoke is not executed; deterministic RS256/JWKS/claim/revocation tests cover the adapter itself.
- The queue executor seam is ready for the frozen Agent runtime, but learned-policy takeover remains forbidden until Agent Product Freeze and hidden-set gates pass.
- The trajectory bridge exports one deterministic public trace here; real licensed trajectory collection and contamination review are later frozen stages.
