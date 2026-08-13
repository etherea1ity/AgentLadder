# Chapter 15 Background Scheduler 门禁

语言：中文 | [English](./ch15-background-scheduler.en.md)

Status: **PASS**

- 评分器: `klara.chapter15-background-scheduler.v1`
- 检查: `19/19`
- 关键调度语义通过率: `1.000`
- 公共面秘密泄漏: `0`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| api_exposes_state_actions_retry_and_read | PASS |
| background_runner_has_start_stop_and_serial_tick | PASS |
| bilingual_tutorial_exists | PASS |
| chat_notification_is_model_hidden_and_idempotent | PASS |
| duplicate_tick_does_not_duplicate_occurrence | PASS |
| iana_timezone_and_spring_dst_gap_policy | PASS |
| misfire_skip_is_audited_without_task | PASS |
| notification_delivery_is_retried_and_acknowledged | PASS |
| occurrence_id_is_deterministic_and_nonsecret | PASS |
| one_shot_materializes_one_durable_task | PASS |
| overlap_queues_at_most_one | PASS |
| pause_resume_cancel_are_persisted | PASS |
| schedule_lease_token_is_not_persisted_raw | PASS |
| scheduler_dispatches_through_existing_run_service | PASS |
| stage_manifest_exists | PASS |
| tenant_owner_isolation_is_opaque | PASS |
| terminal_notification_survives_delivery_failure | PASS |
| ui_reads_real_scheduler_contract | PASS |
| ui_shows_timezone_recurrence_next_run_and_history | PASS |

## 问题—回答一致性探针

- 问题: 每天纽约时间 02:30 运行；夏令时跳过、进程重启或上次还没结束时怎么办？
- 参考回答: 春季缺失时刻前移到首个有效分钟；同一 occurrence ID 只创建一个 durable task；重启重新投递未终结项；重叠只排队一次；通知失败后持久化重试。
- 候选观察: DST gap resolved to 07:00 UTC, duplicate tick created zero work, one overlap was queued, and the persisted notification delivered on retry.
- P0 奇怪回答: `0`

## 限制

- The gate proves the frozen single-host SQLite scheduler, not multi-region consensus.
- The API worker polls one configured local tenant; Chapter 18 adds authenticated multi-tenant workers.
- The behavior item is a deterministic self/reference consistency probe, not an independent human or model-judge comparison.
