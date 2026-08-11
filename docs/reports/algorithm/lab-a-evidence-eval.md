# Lab A - Evidence And Trajectory Evaluation

Status: **PASS**

- Stage: `lab-a-evidence-eval`
- Scorer: `klara.evidence-eval.v1`
- Evaluated at: `2026-08-11T00:00:00+00:00`
- Fixture SHA-256: `97e907508177ad6eb137eaa77ea004e8d78073f58e50ce4ce99d5d746ac7a57e`
- Trajectory SHA-256: `271d05c607fdd77c24e75fe68a01fbae2aa6ba0f95da458737d6c91b5736ab33`
- Deterministic export SHA-256: `a1c2f1df4c88f61f940e2ef30905cf7b22d29fd9b93ad092e552aed69d08c19b`

## Dataset Gate

| Measure | Value |
| --- | ---: |
| total_records | 2 |
| valid_records | 2 |
| schema_validation_rate | 1.000000 |
| linkage_checks | 60 |
| linkage_passed | 60 |
| id_linkage_rate | 1.000000 |
| leakage_finding_count | 0 |

## Quality Metrics

| Metric | Value |
| --- | ---: |
| abstention_accuracy | 1.000000 |
| citation_precision | 1.000000 |
| citation_recall | 1.000000 |
| claim_support_accuracy | 1.000000 |
| contradiction_recall | 1.000000 |
| evidence_selection_precision | 1.000000 |
| evidence_selection_recall | 1.000000 |
| tool_argument_exactness | 1.000000 |
| tool_decision_accuracy | 1.000000 |

## Operational Totals

| Measure | Value |
| --- | ---: |
| cost_usd_total | 0.000420 |
| input_tokens_total | 171 |
| latency_ms_total | 76.750000 |
| output_tokens_total | 52 |
| tokens_total | 223 |

## Acceptance Checks

| Check | Result |
| --- | --- |
| abstention_accuracy | PASS |
| citation_precision | PASS |
| citation_recall | PASS |
| claim_support_accuracy | PASS |
| contradiction_recall | PASS |
| deterministic_export_hash | PASS |
| evidence_selection_precision | PASS |
| evidence_selection_recall | PASS |
| id_linkage | PASS |
| schema_validation | PASS |
| tool_argument_exactness | PASS |
| tool_decision_accuracy | PASS |
| zero_secret_or_reasoning_leaks | PASS |

## Interpretation

The fixture covers supported, contradicted, insufficient, stale, and irrelevant evidence. A required claim is released only when an admissible source has an explicit supported link and citation. Contradicted or insufficient required claims force abstention.

Operational totals are fixture measurements for scorer plumbing, not provider performance claims.
