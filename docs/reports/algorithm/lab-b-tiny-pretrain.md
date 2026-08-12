# Lab B - Repository-Native Tiny Pretraining

Status: **PASS**

- Experiment: `lab-b-tiny-pretrain`
- Evaluated at: `2026-08-12T06:45:38.469210+00:00`
- Parent commit: `445fad2ba6b3284478276ee0f4e815946218221e`
- Source bundle SHA-256: `aeb7a710de21340a9fecf5914c48954355d290564654f48fea714ff2e1d3cf1c`
- Slurm job: `133910`
- Device: `cuda`
- Precision: `fp32`
- Parameters: `821120`
- Checkpoint SHA-256: `ea885bc2e6cb5aebacb576b85c1c61876a711962842a9e1ac84a1f677895d9f3`
- Checkpoint logit max abs diff: `0.000000000` (atol `0.000001000`)

## Training Result

| Measure | Value |
| --- | ---: |
| initial_loss | 5.601286 |
| final_loss | 0.163015 |
| loss_reduction_fraction | 0.970897 |
| duration_seconds | 1.609122 |
| peak_allocated_bytes | 61149696 |

## Reproducibility And Hardware

- CPU hash A: `17496378a884e2ef9598c5b2785df44e95194c799ef06439400770c1c88e473a`
- CPU hash B: `17496378a884e2ef9598c5b2785df44e95194c799ef06439400770c1c88e473a`
- GPU: `NVIDIA GeForce RTX 4080 SUPER`
- GPU smoke peak bytes: `37617664`
- Generated text: `Klara checks evidence cioce ck`

## Artifact Hashes

| Artifact | SHA-256 |
| --- | --- |
| config_sha256 | `34b1602b88541ea794c77e9c02d5f43ea44e4d28f4c8bcb73fd5cdbee23ac7f7` |
| data_sha256 | `5d4056431d15921a7011785a5044944e118e573a809aa3cba6bf75313556eb2b` |
| model_state_sha256 | `6f7ecf0b15efde713e8fe4c442097bf7760141cf23839fb68ad98120cbbecc0e` |
| restored_model_state_sha256 | `6f7ecf0b15efde713e8fe4c442097bf7760141cf23839fb68ad98120cbbecc0e` |
| scorer_sha256 | `5b76c15a2d1429d3b8df479320e46a3499fcddebe4bc387f20fe8831400156aa` |

## Acceptance Checks

| Check | Result |
| --- | --- |
| checkpoint_hash_verified | PASS |
| checkpoint_logits_within_tolerance | PASS |
| checkpoint_reload_exact | PASS |
| cpu_same_seed_reproducible | PASS |
| cuda_training | PASS |
| finite_gradients | PASS |
| gpu_smoke_available | PASS |
| gpu_smoke_finite_and_under_limit | PASS |
| loss_reduction | PASS |
| slurm_execution | PASS |
| training_peak_under_limit | PASS |

## Scope

This is a from-scratch teaching Transformer with byte tokens, RMSNorm, RoPE, grouped-query causal attention, and a SwiGLU-style dense feed-forward block. The fixed micro-corpus run proves the training and checkpoint path; it is not a general language-quality claim.
