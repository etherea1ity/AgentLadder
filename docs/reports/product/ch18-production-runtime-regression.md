# 生产 Agent 回归门禁

语言：中文 | [English](./ch18-production-runtime-regression.en.md)

Status: **PASS**

- 评分器: `klara.production-regression.v1`
- 数据集 SHA-256: `c2521f22422d5775f424b51104e47585a760d0ba09b38bc7ce0b7bdb01ae3732`

## 验收检查

| 检查 | 结果 |
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

## 资源比率

| Metric | Candidate / baseline |
| --- | ---: |
| cost | 1.000000 |
| latency | 1.000000 |
| tokens | 1.000000 |

通过仅证明候选在同一份冻结 fixture、split 哈希、评分器与预算下没有回退。
