# Production Agent Regression Gate

Language: [Chinese](./ch18-production-runtime-regression.md) | English

Status: **PASS**

- Scorer: `klara.production-regression.v1`
- Fixture SHA-256: `c2521f22422d5775f424b51104e47585a760d0ba09b38bc7ce0b7bdb01ae3732`

## Acceptance Checks

| Check | Result |
| --- | --- |
| candidate_gate_passed | PASS |
| cost_budget | PASS |
| critical_non_regression | PASS |
| human_non_regression | PASS |
| judge_non_regression | PASS |
| latency_budget | PASS |
| normal_non_regression | PASS |
| overall_non_regression | PASS |
| p0_zero | PASS |
| reference_gap_non_regression | PASS |
| severe_mismatch_non_regression | PASS |
| token_budget | PASS |

## Resource Ratios

| Metric | Candidate / baseline |
| --- | ---: |
| cost | 1.000000 |
| latency | 1.000000 |
| tokens | 1.000000 |

A pass proves non-regression only on the identical frozen fixture, split hashes, scorer, and budgets.
