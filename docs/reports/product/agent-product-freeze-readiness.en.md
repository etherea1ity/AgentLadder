# Agent Product Freeze Readiness

Language: [Chinese](./agent-product-freeze-readiness.md) | English

- Evidence reconciliation stage: `PASS`
- Agent Product Freeze: `BLOCKED`
- Model training allowed: `false`

## Current Measured Truth

- Architecture gates: `12/12`.
- Behavior observations: `41`, critical `1.0`, normal `1.0`, P0 `0`.
- LoCoMo F1: direct `0.455354`, Agent `0.437246`, delta `-0.018108`.
- LoCoMo Recall@20: direct `0.767917`, Agent `0.782417`, delta `0.0145`.
- AgentBench subset: `0.8`; tau2 subset: `0.8`.
- Stage verification: Python `519` collected / `2` skipped; web `71` tests in `20` files; build `true`.

## Interpretation Boundary

- Agent retrieval recall exceeds the same-model direct baseline, while answer F1 remains below it.
- No Mem0, MEM1, BEAM, GPT, Qwen, general Agent-framework, or ChatGPT superiority claim is made.

## Freeze Blockers

- `independent-model-judge`: The frozen Qwen judge credential returned HTTP 401; a distinct independent judge has not scored the 41 observations.
- `blind-human-review`: No independent blind-human labels exist for the frozen comparison queue.

## Resource-dependent Expansion

- `official-mem1-gpu-comparison`: The pinned MEM1 7B rollout requires a comparable GPU evaluation run.
- `beam-scale-comparison`: No licensed, hashed BEAM snapshot is available for a comparable scale run.
- `gaia-public-subset`: A frozen publicly permitted GAIA subset has not yet been executed through the current runtime.
