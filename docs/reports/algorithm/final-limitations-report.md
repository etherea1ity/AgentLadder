# Final Limitations Report

## Measured Boundaries

- Evidence metrics use five deterministic gold cases and two trajectory records.
  A score of 1.0 is a regression-fixture result, not open-domain perfection.
- Dense and MoE loss results use one fixed micro-corpus. They prove trainability,
  checkpointing, and controlled comparison, not general language capability.
- Distillation uses an offline repository-owned public-contract fixture. It
  proves Qwen/DeepSeek manifest handling and hard-label SFT; it is not an online
  teacher-quality, latency, token, or cost benchmark.
- The MoE comparison holds data, seed, steps, optimizer, precision, and scorer
  constant, but is not parameter matched or active-FLOP matched and uses no
  distributed expert parallelism or fused kernels.
- FP4 covers the 12 gated SwiGLU projections. Packed storage includes nibble
  codes and FP16 scales, but inference dequantizes before dense GEMM. Native FP4
  tensor-core execution is unavailable and is not claimed.
- Fake-quant QAT is implemented behind a measured quality-failure trigger. The
  final W4A16 held-out score did not degrade, so QAT did not run.

## Deferred Work

- larger and independently curated evidence/task datasets;
- online teacher collection with consented cost/latency accounting;
- large-corpus pretraining and held-out perplexity benchmarks;
- parameter- or active-FLOP-matched MoE studies and expert specialization data;
- native low-precision kernels and device-specific throughput benchmarks;
- distributed training, expert parallelism, production serving, auth, and policy;
- production runtime deployment of any learned evidence policy;
- frontend work, which was explicitly excluded from this algorithm completion.

## Claim Policy

Resume and project claims may state that the mechanisms were implemented and
that the bounded HKU runs produced the recorded metrics. They must not describe
the fixture as production-scale, the offline teachers as a live benchmark, the
W4A16 path as native FP4 compute, or the tiny model as a general-purpose LLM.
