# Algorithm Suite Freeze

Date: 2026-08-12

Status: frozen after HKU Slurm Job `133919`

## Implemented

- claim-level evidence control and abstention;
- redacted public trajectory export and deterministic evaluation;
- repository-native tiny dense Transformer;
- Qwen/DeepSeek public-contract hard-label distillation;
- four-expert token-level top-2 sparse MoE;
- real CUDA FP16 AMP and packed E2M1 FP4/W4A16;
- HKU source/deployment/checkpoint/report lineage;
- single-job final suite aggregation and bilingual lab documentation.

## Measured

- 229/229 cloud tests passed;
- dense loss reduction 97.09%;
- distillation held-out tool-decision accuracy 0.125 -> 1.0;
- MoE loss reduction 98.03%, training expert-load ratio 1.081;
- FP16/FP32 max logit difference 0.001296669;
- FP4 packed code-plus-scale storage saving 73.4375%;
- W4A16 held-out accuracy 1.0 with no quality degradation.

## Optional But Implemented

- fake-quant QAT with CUDA FP16 GradScaler, triggered only after PTQ quality
  breaches the configured threshold. It did not trigger in the frozen run.

## Deferred

- online teacher benchmark, broad datasets, large-model training, distributed
  MoE, fused/native FP4 kernels, production serving/auth, learned-policy rollout,
  and all new frontend work.

## Reproduction

```powershell
powershell -ExecutionPolicy Bypass -File scripts/hku/package_agentladder.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/submit_algorithm_suite.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/monitor_algorithm_suite.ps1
powershell -ExecutionPolicy Bypass -File scripts/hku/fetch_algorithm_suite_reports.ps1
```

The checkpoint archive remains cloud-only at:

```text
/userhome/cs2/u3665453/AgentLadder/artifacts/algorithm-suite-freeze/job-133919/
```
