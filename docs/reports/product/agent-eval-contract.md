# Agent 行为评测

语言：中文 | [English](./agent-eval-contract.en.md)

Status: **PASS**

- 门禁类型: `contract_control_probe`
- Scorer: `klara.behavior-scorer.v1`
- Fixture SHA-256: `c2521f22422d5775f424b51104e47585a760d0ba09b38bc7ce0b7bdb01ae3732`
- Observations: `24`
- 解释: 验证 schema、评分器、阈值、split 隔离、报告渲染和盲评连接；它不衡量当前 Agent 产品能力。

## 指标

| 指标 | 值 |
| --- | ---: |
| candidate_reference_success_rate | 1.000000 |
| critical_deterministic_rate | 1.000000 |
| human_acceptability_rate | 1.000000 |
| judge_equivalent_or_better_rate | 1.000000 |
| normal_task_success_rate | 1.000000 |
| overall_task_success_rate | 1.000000 |
| p0_count | 0 |
| reference_gap | 0.000000 |
| reference_success_rate | 1.000000 |
| severe_answer_mismatch_rate | 0.000000 |
| total_cost_usd | 0.000000 |
| total_latency_ms | 1200 |
| total_tokens | 768 |

## 验收检查

| 检查 | 结果 |
| --- | --- |
| critical_deterministic | PASS |
| critical_repeat_stability | PASS |
| documentation_pairs | PASS |
| human_acceptability | PASS |
| human_review_queue_empty_after_control_labels | PASS |
| independent_judge | PASS |
| normal_task_success | PASS |
| p0_zero | PASS |
| reference_non_inferiority | PASS |
| severe_answer_mismatch | PASS |

## 解释边界

通过只证明候选在冻结用例、工具、权限、预算、参考版本和评分器上的非劣性；它不代表普遍达到 ChatGPT 能力。
