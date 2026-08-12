# Final Experiment Report

Authoritative run: HKU Slurm Job `133919`

Source bundle: `3789e4d5395f44ac121045f73214ac9909096963a4e0b2981f166d112956d106`

Compute node: `gpu-4080-409`, NVIDIA GeForce RTX 4080 SUPER

Slurm result: `COMPLETED`, exit `0:0`, runtime 37 seconds

## Reproduced Matrix

| Workstream | Final same-job result |
| --- | --- |
| Evidence/eval | schema 1.0; linkage 1.0; leakage findings 0; citation precision/recall 1.0/1.0; abstention 1.0 |
| Tiny dense | 821,120 parameters; loss 5.601286 -> 0.163015; 97.09% reduction |
| Distillation | 28 public examples from Qwen and DeepSeek; held-out tool decision 0.125 -> 1.0; validation 1.0 |
| Sparse MoE | four experts, top-2; 2,592,640 parameters; 98.03% loss reduction; training load ratio 1.081 |
| FP16/FP4 | FP16/FP32 logit max diff 0.001296669; packed saving 73.4375%; W4A16 held-out accuracy 1.0 |
| Regression | 229/229 cloud Python tests passed; no frontend path in packaged changes |

## Checkpoint Lineage

The final job generates each dependency before consuming it:

```text
Lab B tiny_dense.pt
  SHA ea885bc2...d9f3
-> Lab C tiny_distilled.pt
  SHA f0ffb11b...4173
-> Lab H W4A16 evaluation
```

The dense/MoE control checkpoints reproduce the earlier hashes:

- dense control: `e72b039305f315a144507002dcaaddb7e55bee520964e014e7f6c8214e3d7026`
- sparse MoE: `34ea4940b26058eb1ae59e343fb01d549a18a6c0b85289b3f8faa12b845c5286`
- FP16 AMP: `9b034f4f8ee7fc69610bf392770a472e2d0150cd975f1cc04a297b2487cd2587`
- W4A16: `ec657738769030127e29ae608b2f293907197746e137fa7c81fb36262a20d492`

## Evidence Location

Cloud checkpoints and complete logs remain under:

```text
/userhome/cs2/u3665453/AgentLadder/artifacts/algorithm-suite-freeze/job-133919/
```

The repository contains the final JSON/Markdown report. No checkpoint was
downloaded during final report retrieval.
