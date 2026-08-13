# Chapters 6-7 Context Gate

Language: [Chinese](./ch06-07-context.md) | English

Status: **PASS**

- Scorer: `klara.chapter06-07-context.v1`
- Gate kind: `deterministic_product_gate`
- Checks: `15/15`

## Acceptance Checks

| Check | Result |
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

## Public Compaction Evidence

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

## Interpretation Boundary

Passing proves deterministic local context assembly, pre-call budget enforcement, recent-message preservation, tool micro-compaction, private-summary boundaries, public trace/SSE projection, and the safe UI indicator. It does not claim semantic LLM summarization, durable memory, RAG retrieval, or learned context selection.
