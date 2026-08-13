# Agent Behavior Evaluation

Language: [Chinese](./agent-eval-contract.md) | English

Status: **PASS**

- Gate kind: `contract_control_probe`
- Scorer: `klara.behavior-scorer.v1`
- Fixture SHA-256: `c2521f22422d5775f424b51104e47585a760d0ba09b38bc7ce0b7bdb01ae3732`
- Observations: `24`
- Interpretation: Validates schemas, graders, thresholds, split isolation, report rendering, and review plumbing. It does not measure the current Agent product.

## Metrics

| Metric | Value |
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

## Acceptance Checks

| Check | Result |
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

## Interpretation Boundary

A passing report proves non-inferiority only on the frozen cases, tools, permissions, budgets, reference version, and graders. It is not a claim of general ChatGPT equivalence.
