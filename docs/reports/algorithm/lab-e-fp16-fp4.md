# Lab E - CUDA FP16 And Packed FP4/W4A16

Status: **PASS**

- Evaluated at: `2026-08-12T07:55:37.540363+00:00`
- Source bundle SHA-256: `d321f5e1aae49dd8a0b7d6f217148498cc34b84f7bcf5ee0e424d65e6b1f88bb`
- Slurm job: `133917`
- Base checkpoint SHA-256: `90962b25e5a67bd6978a6ee8408f62563539765dc9f7ee28e51491f9d95d56be`
- FP4 format: `klara.fp4-e2m1-block.v1`
- Compute disclosure: `W4A16 dequantized compute; not native FP4 tensor-core compute`

## FP16 AMP

| Measure | Value |
| --- | ---: |
| initial_loss | 5.553232 |
| final_loss | 3.796651 |
| duration_seconds | 0.776726 |
| peak_allocated_bytes | 56844800 |
| fp16_fp32_logit_max_abs_diff | 0.001296669 |
| declared_atol | 0.020000000 |

## Packed FP4 Storage

- Quantized gated tensors: `12`
- FP16 baseline bytes: `1179648`
- Packed codes + scales bytes: `313344`
- Saving fraction: `0.734375`
- Block size: `64`
- QAT triggered: `False`

## Held-Out Tool Decisions

| Model | Accuracy |
| --- | ---: |
| FP32 | 1.000000 |
| W4A16 | 1.000000 |
| degradation | 0.000000 |

## Acceptance Checks

| Check | Result |
| --- | --- |
| base_checkpoint_hash_verified | PASS |
| block_metadata_versioned | PASS |
| dequantized_compute_disclosed | PASS |
| e2m1_all_codes_round_trip | PASS |
| fp16_finite | PASS |
| fp16_fp32_within_tolerance | PASS |
| gpu_peak_under_limit | PASS |
| nibble_odd_even_round_trip | PASS |
| qat_on_quality_failure | PASS |
| real_cuda_fp16_amp | PASS |
| slurm_cuda_execution | PASS |
| storage_saving | PASS |
| w4a16_artifact_reload | PASS |
| w4a16_finite | PASS |
| w4a16_quality | PASS |

## Limitations

The packed artifact stores E2M1 nibbles and FP16 per-block scales. Inference dequantizes those weights to the activation dtype before a standard dense matrix multiplication. This is W4A16 dequantized compute, not native FP4 hardware execution.
