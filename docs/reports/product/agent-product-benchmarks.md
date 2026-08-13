# Agent 产品评测门禁

语言：中文 | [English](./agent-product-benchmarks.en.md)

Status: **FAIL**

本地确定性与来源契约工作已通过，但仍不允许进入 Agent Product Freeze。

## 本地已验证检查

| 检查 | 结果 |
| --- | --- |
| `runtime_reference_calibration_41_of_41` | PASS |
| `locomo_gold_evidence_retrieval` | PASS |
| `longmemeval_oracle_contract` | PASS |
| `memory_agent_bench_all_split_contracts` | PASS |
| `agentbench_and_tau2_source_contracts` | PASS |
| `mem0_mem1_beam_source_contracts` | PASS |
| `external_label_merger_is_frozen` | PASS |
| `paid_api_budget_is_zero` | PASS |
| `no_training_before_product_freeze` | PASS |

## 强制未完成检查

| 检查 | 结果 |
| --- | --- |
| `live_candidate_full_coverage` | FAIL |
| `reference_non_inferiority` | FAIL |
| `independent_model_judge_full_coverage` | FAIL |
| `blind_human_acceptability_at_least_0_95` | FAIL |
| `official_agentbench_score` | FAIL |
| `official_tau2_score` | FAIL |
| `official_mem0_same_model_score` | FAIL |
| `official_mem1_gpu_score` | FAIL |
| `official_beam_score` | FAIL |

## 实测结果

| 指标 | 数值 |
| --- | ---: |
| `klara_bench_cases` | 11 |
| `klara_bench_observations` | 41 |
| `klara_bench_critical_observations` | 20 |
| `locomo_questions` | 100 |
| `locomo_hybrid_evidence_recall_at_5` | 0.630588 |
| `locomo_hybrid_evidence_hit_at_5` | 0.68 |
| `locomo_hybrid_mrr` | 0.439 |
| `longmemeval_oracle_questions` | 60 |
| `memory_agent_bench_rows` | 146 |
| `memory_agent_bench_questions` | 3671 |
| `paid_live_candidate_observations` | 0 |
| `independent_judge_labels` | 0 |
| `blind_human_labels` | 0 |
| `official_public_agent_scores` | 0 |
| `official_memory_competitor_scores` | 0 |

## 外部阻塞

- `paid-api-budget`: The frozen paid API budget is USD 0, so the 41-observation live candidate and independent judge runs are prohibited. Approve a nonzero USD cap and frozen per-million input/output prices for the candidate and independent judge.
- `blind-human-review`: Blind acceptability cannot be inferred by the same system that generated or scored the candidate outputs. Collect blind labels after candidate outputs exist; target acceptance is at least 95%.
- `official-public-agent-scores`: AgentBench and tau2 source/task contracts pass, but official environments were not scored. Run the pinned official graders with frozen agent/user models and declared budget.
- `official-memory-competitor-scores`: Mem0, MEM1, and BEAM are pinned but their official comparable pipelines were not executed. Use identical data, answer/judge models, top-k, generation limits, and inference budgets; MEM1 additionally requires GPU rollout.

## 解释边界

41/41 脚本参考校准验证的是运行链路，不是当前模型质量；LoCoMo 只测检索，LongMemEval 与 MemoryAgentBench 当前只验证数据契约，不测答案准确率。本报告不声称普遍达到 ChatGPT，也不声称优于竞品。
