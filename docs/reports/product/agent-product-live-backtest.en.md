# Agent Product Live Backtest

Language: [Chinese](./agent-product-live-backtest.md) | English

Status: **blocked_external_gates**

- Model: `deepseek/deepseek-v4-flash`
- Runner: `klara.behavior-live-runner.v6`
- Deterministic product gate: `PASS`
- Agent Product Freeze: `FAIL`

## Metrics

| Metric | Value |
| --- | ---: |
| main_observations | 41 |
| main_deterministic_rate | 1.0 |
| main_critical_rate | 1.0 |
| main_p0_count | 0 |
| main_provider_error_count | 0 |
| main_estimated_cost_usd | 0.015431499999999999 |
| stage_observations | 21 |
| stage_deterministic_rate_before_todo_repair | 0.9523809523809523 |
| todo_repair_rate | 1.0 |
| judge_scored | 0 |
| human_scored | 0 |
| live_tooling_cases | 3 |
| live_tooling_tokens | 7468 |
| locomo_hybrid_recall_at_5 | 0.630588 |
| locomo_hybrid_hit_at_5 | 0.68 |
| longmemeval_contract_questions | 60 |
| memory_agent_bench_rows | 146 |

## Checks

| Check | Result |
| --- | --- |
| reference_runtime_calibration_41_of_41 | PASS |
| deepseek_live_observation_coverage_41_of_41 | PASS |
| deepseek_live_overall_deterministic_41_of_41 | PASS |
| deepseek_live_critical_20_of_20 | PASS |
| deepseek_live_all_repeat_stability | PASS |
| deepseek_live_p0_zero | PASS |
| deepseek_live_provider_errors_zero | PASS |
| todo_repair_live_3_of_3 | PASS |
| stage_critical_15_of_15 | PASS |
| live_qwen_auth_to_deepseek_fallback | PASS |
| live_evidence_mcp_team_tool_decisions_3_of_3 | PASS |
| locomo_retrieval_gate | PASS |
| longmemeval_oracle_contract | PASS |
| memory_agent_bench_all_split_contracts | PASS |
| mem0_mem1_beam_pinned_source_contracts | PASS |
| agentbench_tau2_pinned_source_contracts | PASS |
| all_16_frozen_branches_audited | PASS |
| qwen_candidate_available | FAIL |
| independent_cross_provider_judge_41_of_41 | FAIL |
| blind_human_review_41_of_41 | FAIL |
| official_agentbench_comparable_score | FAIL |
| official_tau2_comparable_score | FAIL |
| memory_same_model_answer_quality_matrix | FAIL |
| official_mem0_comparable_score | FAIL |
| official_mem1_gpu_score | FAIL |
| official_beam_score | FAIL |

## Codex Public Reference

The Codex-authored public answers and action paths were replayed through the real Harness. This is an auditable public-reference comparison, not a claim that an OpenAI API reference model was called.

## Regression History

| Stage | Success | P0 |
| --- | ---: | ---: |
| initial_live_baseline | 0.341463 | 24 |
| post_initial_repairs | 0.414634 | 10 |
| pre_response_contract | 0.804878 | 3 |
| pre_clarification_state_fix | 0.975610 | 0 |
| final_runner_v6 | 1.000000 | 0 |

## Blockers

- Both locally discovered Qwen credential candidates returned HTTP 401, so candidate B and the cross-provider judge could not run.
- The 41-item blind human review queue is generated, but no human labels have been supplied; labels were not fabricated.
- AgentBench and tau2 source contracts are pinned, but their official comparable graders have not run.
- LoCoMo retrieval and the LongMemEval/MemoryAgentBench data contracts pass, but the same-answer-model memory matrix and official Mem0, MEM1, and BEAM scores have not run.

## Training Boundary

Agent Product Freeze remains false until the independent judge, blind human review, official public-agent scores, and comparable memory-system matrix are complete.
