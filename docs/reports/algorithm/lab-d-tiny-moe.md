# Lab D - Four-Expert Top-2 Sparse MoE

Status: **PASS**

- Evaluated at: `2026-08-12T07:28:25.578663+00:00`
- Source bundle SHA-256: `c37b4f78d0ded9506d3618ff4f20d2a6a0c6e38068ac7528cb1f4b0d506d4d6d`
- Slurm job: `133915`
- Experts: `4`
- Routing: `token-level top-2 distinct`
- Scorer SHA-256: `8bb864e27f59315b779c39ff7266c734814073d5ded4046e5e9454d1fb1975e0`

## Fair Dense/MoE Comparison

| Measure | Dense | MoE |
| --- | ---: | ---: |
| initial_loss | 5.575672 | 5.576783 |
| final_loss | 0.842148 | 0.109930 |
| loss_reduction_fraction | 0.848960 | 0.980288 |
| parameter_count | 821120 | 2592640 |
| duration_seconds | 1.515678 | 3.558638 |
| peak_allocated_bytes | 61149696 | 115504640 |

## Routing Diagnostics

- Balanced expert loads: `[16, 16, 16, 16]`
- Balanced max/min ratio: `1.000000`
- Balanced router entropy: `0.586484`
- Training-corpus expert loads: `[1721, 1626, 1719, 1758]`
- Training-corpus max/min ratio: `1.081181`
- Training-corpus router entropy: `1.250265`
- Selected top-2 weight sum mean: `1.000000000`
- Router z-loss: `1.617555`
- Router balance loss: `1.003725`

## Acceptance Checks

| Check | Result |
| --- | --- |
| auxiliary_loss_present | PASS |
| balanced_all_experts_used | PASS |
| balanced_load_ratio | PASS |
| collapse_detection_passed | PASS |
| dense_checkpoint_reload | PASS |
| dense_loss_reduction | PASS |
| exactly_four_experts | PASS |
| finite_forward_backward | PASS |
| gpu_peak_under_limit | PASS |
| identical_comparison_contract | PASS |
| moe_checkpoint_reload | PASS |
| moe_loss_reduction | PASS |
| router_entropy | PASS |
| selected_weights_normalized | PASS |
| slurm_cuda_execution | PASS |
| top2_distinct_routing | PASS |
| z_loss_present | PASS |

## Scope

Both models use the same fixed micro-corpus, seed, step budget, batching, optimizer settings, precision, and scorer. This proves the sparse routing and bounded training path; it is not a broad language-quality benchmark.
