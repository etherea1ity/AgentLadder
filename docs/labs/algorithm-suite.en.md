# AgentLadder Algorithm Lab Suite

Language: [Chinese](./algorithm-suite.md) | English

Roadmap: [Klara Roadmap](../skills/roadmap.md)

Final machine report: [Algorithm Suite Freeze](../reports/algorithm/algorithm-suite-freeze.md)

## Question And Falsifiable Hypothesis

Can Chapter 3 public traces support a reproducible evidence-control, evaluation,
tiny-Transformer, trajectory-distillation, sparse-MoE, and low-precision pipeline
without modifying `KlaraLoop`, depending on a frontend, or collecting hidden
chain of thought?

The hypothesis passes only if schema/linkage/leakage gates are green, unsupported
required claims abstain, the custom decoder trains and reloads, public Qwen and
DeepSeek labels improve held-out tool decisions, four-expert top-2 routing does
not collapse, precision semantics stay truthful, and all stages rerun in one HKU
Slurm job.

## Canonical Course Homes

| Work | Canonical home | Implementation |
| --- | --- | --- |
| Public trace and safe export | Chapter 3, Chapter 18, Lab A | `src/klara/eval` |
| Claim-level evidence control | Chapters 12–13, Lab A | `src/klara/services/evidence` |
| Tiny decoder pretraining | Lab B | `model.py`, `trainer.py` |
| Public-trajectory distillation | Lab C | `distillation.py` |
| Four-expert top-2 sparse MoE | Lab E | `moe.py` |
| CUDA FP16 and packed FP4/W4A16 | Lab H | `quantization.py` |
| End-to-end regression bridge | Chapter 18 | `eval/suite.py` |

Training consumes redacted exports and never becomes a second agent loop.
`klara.core` does not import evidence, evaluation, or training packages.

## Cloud Quick Experience

After following `C:\Users\jsj31\Desktop\HKU_GPU_FARM_HANDOFF.md` to establish
VPN/SSH access, run from the repository root:

```powershell
powershell -ExecutionPolicy Bypass -File scripts/hku/package_agentladder.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/submit_algorithm_suite.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/monitor_algorithm_suite.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/fetch_algorithm_suite_reports.ps1
```

The gateway performs setup only. `sbatch` runs formal computation on an RTX
4080, and fetch downloads reports, logs, and checksums while checkpoints remain
on HKU storage.

## Lab A: Evidence Control And Trajectory Evaluation

The deterministic gold fixture validates at 1.0 schema/linkage, zero
secret or hidden-reasoning findings, 1.0 citation precision/recall, and 1.0
abstention accuracy. These are fixture scores, not open-domain accuracy claims.

## Lab B: Repository-Native Tiny Transformer

The implementation is a repository-native 821,120-parameter, four-layer byte-level
decoder with RMSNorm, RoPE, GQA, and SwiGLU. On the fixed micro-corpus, 120 CUDA
FP32 steps reduce loss from 5.601286 to 0.163015 (97.09%), with exact checkpoint
logit replay.

## Lab C: Qwen + DeepSeek Public-Trajectory Distillation

The frozen 28-example public-contract manifest contains 14 Qwen and 14 DeepSeek
examples, disjoint 16/4/8 train/validation/test splits, hard-label SFT, and zero
API-teacher KL. Held-out tool-decision accuracy improves from 0.125 to 1.0 and
validation accuracy reaches 1.0. This is an offline contract-fixture result, not
an online teacher-quality benchmark.

## Lab E: Four-Expert Top-2 Sparse MoE

The model implements four experts with distinct token-level top-2 routing, normalized
selected weights, load balancing, and router z-loss. Under the same data, seed,
steps, optimizer, precision, and scorer, dense loss falls 84.90% and MoE loss
falls 98.03%. Training loads are `[1721, 1626, 1719, 1758]` (ratio 1.081), while
the balanced probe is `[16, 16, 16, 16]`.

## Lab H: CUDA FP16 And E2M1 FP4/W4A16

This path uses real CUDA FP16 autocast plus GradScaler. FP16/FP32 maximum logit
difference is 0.001296669 under a 0.02 threshold. Versioned E2M1 block FP4 packs
12 SwiGLU projections from 1,179,648 FP16 bytes to 313,344 code-plus-scale bytes,
saving 73.4375%. FP32 and W4A16 held-out accuracy are both 1.0, so the configured
quality-failure trigger correctly does not run QAT. Compute dequantizes W4
weights before dense GEMM; native FP4 execution is not claimed.

## Final Reproduction And Artifacts

HKU Job `133919` reran all stages sequentially from source bundle
`3789e4d5395f44ac121045f73214ac9909096963a4e0b2981f166d112956d106`
on `gpu-4080-409`. Slurm recorded `COMPLETED`, exit `0:0`, 37 seconds, and
229/229 Python tests passed.

The suite creates no synthetic cross-task quality score. Every metric retains
its own fixture, scorer, manifest, and checkpoint hash. Cloud artifacts remain at:

```text
/userhome/cs2/u3665453/AgentLadder/artifacts/algorithm-suite-freeze/job-133919/
```

## Limitations

- Gold data and the micro-corpus are deliberately small mechanism tests.
- Distillation is an offline public-contract fixture, not an online teacher ranking.
- MoE has no distributed expert parallelism, fused kernel, or active-FLOP-matched benchmark.
- FP4 covers gated projections and dequantized W4A16 compute, not native FP4 compute.
- QAT is implemented and gated but did not trigger because PTQ quality did not regress.
- No frontend dependency, production authentication, large-corpus evaluation, or distributed training was added.
