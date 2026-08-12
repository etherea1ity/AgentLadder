# AgentLadder Algorithm Suite Freeze

Status: **PASS**

- Slurm job: `133919`
- Source bundle: `3789e4d5395f44ac121045f73214ac9909096963a4e0b2981f166d112956d106`
- Parent commit: `573aecf5d5fbb0008af2f99eb4d82b4dd9cabb20`
- Full Python suite: `229 passed, 0 skipped`
- Frontend dependency added: `False`

## Measured Matrix

| Workstream | Reproduced result |
| --- | --- |
| Evidence/eval | schema 1.000; linkage 1.000; leaks 0; citation P/R 1.000/1.000; abstention 1.000 |
| Tiny dense | 821120 params; loss 5.601286 -> 0.163015; reduction 97.090% |
| Distillation | deepseek,qwen; 28 public examples; held-out accuracy 0.125 -> 1.000 |
| Sparse MoE | 4 experts, top-2; 2592640 params; loss reduction 98.029%; load ratio 1.081 |
| FP16/FP4 | logit max diff 0.001296669; packed saving 73.438%; W4A16 accuracy 1.000 |

## Acceptance Checks

| Check | Result |
| --- | --- |
| all_stage_reports_pass | PASS |
| dense_to_distillation_checkpoint_lineage | PASS |
| distillation_to_fp4_checkpoint_lineage | PASS |
| full_python_suite_passed | PASS |
| moe_comparison_uses_dense_data | PASS |
| no_frontend_dependency_added | PASS |
| precision_run_uses_dense_data | PASS |
| single_deployment | PASS |
| single_parent_commit | PASS |
| single_slurm_job | PASS |
| single_source_bundle | PASS |
| source_state_matches_reports | PASS |
| teacher_manifest_lineage | PASS |

## Interpretation Boundary

Each value preserves its stage-specific scorer and fixture. There is no synthetic overall quality score. The distillation result is an offline public-contract fixture result, the dense/MoE runs are micro-corpus training checks, and W4A16 uses packed FP4 storage with dequantized dense compute rather than native FP4 tensor-core execution.
