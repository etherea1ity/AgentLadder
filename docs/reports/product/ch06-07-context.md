# Chapter 6–7 上下文门禁

语言：中文 | [English](./ch06-07-context.en.md)

Status: **PASS**

- 评分器: `klara.chapter06-07-context.v1`
- 门禁类型: `deterministic_product_gate`
- 检查: `15/15`

## 验收检查

| 检查 | 结果 |
| --- | --- |
| chapter06_bilingual_tutorial_exists | PASS |
| chapter07_bilingual_tutorial_exists | PASS |
| compaction_respects_budget | PASS |
| context_policy_frozen_in_run_profile | PASS |
| current_request_is_preserved | PASS |
| frontend_shows_safe_context_budget_status | PASS |
| history_compacts_before_first_llm | PASS |
| history_is_budgeted_not_fixed_count_truncated | PASS |
| named_context_sections_reach_model | PASS |
| precompact_hook_is_projected | PASS |
| private_summary_absent_from_public_trace | PASS |
| private_summary_reaches_model | PASS |
| public_events_expose_metrics_not_summary | PASS |
| stage_manifest_exists | PASS |
| tool_micro_compaction_preserves_join_id | PASS |

## 公开压缩证据

```json
{
  "after_estimated_tokens": 265,
  "before_estimated_tokens": 1100,
  "budget_tokens": 384,
  "messages_after": 3,
  "messages_before": 11,
  "messages_hard_trimmed": 0,
  "messages_summarized": 8,
  "strategy": "tool_micro_compaction_then_extractive_session_summary",
  "summary_content_exposed": false,
  "summary_present": true,
  "summary_sha256": "b9a02789cd51d5f3048f5b00f8b188689e090a12ac1dd2572fdd28d16a962106",
  "tool_results_micro_compacted": 0
}
```

## 解释边界

通过证明了确定性的本地上下文组装、首次调用前预算约束、近期消息保留、工具微压缩、私有摘要边界、公开 trace/SSE 投影和安全的前端状态。它不代表语义 LLM 摘要、长期记忆、RAG 检索或学习式上下文选择已经完成。
