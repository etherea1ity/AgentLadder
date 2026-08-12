# Lab C - Multi-Teacher Public-Trajectory Distillation

Status: **PASS**

- Evaluated at: `2026-08-12T07:15:30.190285+00:00`
- Source bundle SHA-256: `29eb3e06a33069b0fde2152e960aa7c199418a7b3cf21576fcfd1e7c8212f2a6`
- Slurm job: `133913`
- Teachers: `deepseek, qwen`
- Supervision: `hard_label_sft`
- API-teacher KL weight: `0.0`
- Base checkpoint SHA-256: `ea885bc2e6cb5aebacb576b85c1c61876a711962842a9e1ac84a1f677895d9f3`
- Distilled checkpoint SHA-256: `90962b25e5a67bd6978a6ee8408f62563539765dc9f7ee28e51491f9d95d56be`

## Dataset Safety

| Measure | Value |
| --- | ---: |
| total_examples | 28 |
| train_examples | 16 |
| validation_examples | 4 |
| test_examples | 8 |
| schema_validation_rate | 1.000000 |
| redaction_pass_rate | 1.000000 |
| deduplication_pass_rate | 1.000000 |

## Student Result

| Measure | Value |
| --- | ---: |
| pre_sft_tool_decision_accuracy | 0.125000 |
| post_sft_tool_decision_accuracy | 1.000000 |
| validation_accuracy | 1.000000 |
| train_loss_first | 5.081444 |
| train_loss_final | 0.004436 |
| duration_seconds | 2.084231 |
| peak_allocated_bytes | 61149696 |

## Evidence-Control Regression

- Frozen baseline SHA-256: `9f13b372ff7dffc1287f18eea4b0a810a6ab91873ef6f593e42957aa1fc66d6f`
- Current rerun passed: `True`
- Metrics at or above baseline: `True`

## Acceptance Checks

| Check | Result |
| --- | --- |
| api_teacher_hard_labels_only | PASS |
| base_checkpoint_hash_verified | PASS |
| checkpoint_hash_verified | PASS |
| checkpoint_reload_exact | PASS |
| deduplication_complete | PASS |
| evidence_control_not_regressed | PASS |
| finite_gradients | PASS |
| gpu_peak_under_limit | PASS |
| heldout_accuracy_improved | PASS |
| post_sft_test_accuracy | PASS |
| public_schema_validated | PASS |
| qwen_and_deepseek_present | PASS |
| redaction_complete | PASS |
| single_frozen_manifest | PASS |
| slurm_cuda_execution | PASS |
| split_hashes_disjoint | PASS |
| validation_accuracy | PASS |

## Scope

This run uses a repository-owned offline public-contract fixture to prove multi-teacher ingestion, redaction, deduplication, disjoint splits, hard-label SFT, and evaluation. It is not an online Qwen or DeepSeek quality benchmark and contains no teacher hidden reasoning, raw prompts, tool arguments, or raw tool results.
